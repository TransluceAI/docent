import asyncio
import functools
import hashlib
from contextlib import asynccontextmanager
from itertools import product
from time import perf_counter
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Literal,
    ParamSpec,
    Sequence,
    TypedDict,
    TypeVar,
    cast,
    overload,
)
from uuid import uuid4

import anyio
from docent._env_util import ENV
from docent._log_util import get_logger
from sqlalchemy import URL, ColumnElement, delete, distinct, exists, func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from docent._ai_tools.diff import extract_states_and_diffs_2

from docent._ai_tools.attribute_extraction import (
    Attribute,
    AttributeStreamingCallback,
    extract_attributes,
)
from docent._ai_tools.clustering.cluster_generator import propose_clusters
from docent._db_service.schemas.base import SQLABase
from docent._db_service.schemas.tables import (
    SQLAAgentRun,
    SQLAAttribute,
    SQLADiffAttribute,
    SQLAFilter,
    SQLAFrameDimension,
    SQLAFrameGrid,
    SQLAJob,
    SQLAJudgment,
    SQLATranscript,
)
from docent._env_util import ENV
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.filters import (
    AttributePredicateFilter,
    ComplexFilter,
    FrameDimension,
    FrameFilter,
    Judgment,
    PrimitiveFilter,
)
from docent.data_models.metadata import BaseAgentRunMetadata
from docent.data_models.transcript import Transcript

logger = get_logger(__name__)


class _NotGiven:
    """Sentinel class to represent a value that was not given."""

    def __repr__(self):
        return "NOT_GIVEN"


NOT_GIVEN = _NotGiven()

T = TypeVar("T")
P = ParamSpec("P")


@overload
def time_this(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]: ...


@overload
def time_this(func: Callable[P, T]) -> Callable[P, T]: ...


def time_this(func: Callable[P, Any]) -> Callable[P, Any]:
    """
    Decorator that times the execution of a function and logs the duration.
    Preserves the function's type signature.

    Args:
        func: The function to be timed

    Returns:
        A wrapped function with the same signature as the original
    """

    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            start_time = perf_counter()
            result = await func(*args, **kwargs)
            end_time = perf_counter()
            logger.info(f"{func.__name__} took {end_time - start_time:.4f} seconds to execute")
            return result

        return async_wrapper
    else:

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            start_time = perf_counter()
            result = func(*args, **kwargs)
            end_time = perf_counter()
            logger.info(f"{func.__name__} took {end_time - start_time:.4f} seconds to execute")
            return result

        return sync_wrapper


class MarginalizationResult(TypedDict):
    marginals: dict[tuple[tuple[str, str], ...], Any | list[Judgment]]
    dim_ids_to_filter_ids: dict[str, list[str]]
    dims_dict: dict[str, FrameDimension] | None
    filters_dict: dict[str, FrameFilter] | None


def _extract_unique_transcript(transcripts: dict[str, Transcript]) -> Transcript:
    """Extract a unique transcript from a dict of transcripts."""
    if len(transcripts) != 1:
        raise ValueError("Expected exactly one transcript, got %d", len(transcripts))
    return list(transcripts.values())[0]


class DBService:
    """PostgreSQL database service for Frames."""

    # Singleton instance and async lock for thread‑safe initialization
    _instance: "DBService | None" = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(
        self,
        engine: AsyncEngine,
        Session: async_sessionmaker[AsyncSession],
    ):
        self.engine = engine
        self.Session = Session

    @classmethod
    async def init(cls):
        """Get or create a singleton instance of ``DBService``.

        Uses an :py:class:`asyncio.Lock` to guard the first‑time creation so that
        concurrent callers do not race to create multiple instances.
        """

        async with cls._lock:
            if cls._instance is not None:
                return cls._instance

            pg_host, pg_port, pg_user, pg_password, pg_database = (
                ENV.get("DOCENT_PG_HOST"),
                ENV.get("DOCENT_PG_PORT"),
                ENV.get("DOCENT_PG_USER"),
                ENV.get("DOCENT_PG_PASSWORD"),
                ENV.get("DOCENT_PG_DATABASE"),
            )

            # Check each database connection parameter individually
            if not pg_host:
                raise ValueError("Database host missing. Please ensure DOCENT_PG_HOST is set.")
            if not pg_port:
                raise ValueError("Database port missing. Please ensure DOCENT_PG_PORT is set.")
            if not pg_user:
                raise ValueError("Database user missing. Please ensure DOCENT_PG_USER is set.")
            if not pg_password:
                raise ValueError(
                    "Database password missing. Please ensure DOCENT_PG_PASSWORD is set."
                )
            if not pg_database:
                pg_database = "docent"
                logger.info("No database name provided; using `docent` as default")

            # Check that the target database is not 'postgres'
            if (target_database := pg_database) == "postgres":
                raise ValueError("Cannot use 'postgres' as a target database")

            # First create a connection to the default 'postgres' database
            url = URL.create(
                drivername="postgresql+asyncpg",
                username=pg_user,
                password=pg_password,
                host=pg_host,
                port=int(pg_port),
                database="postgres",  # Connect to default postgres database first
            )

            # Create the target database if it doesn't exist
            await cls._ensure_database_exists(url, target_database)

            # Now create the connection string for the target database
            connection_url = url.set(database=target_database)
            logger.info(f"Using database connection: {connection_url}")

            # Initialize engine with connection pooling
            engine = create_async_engine(
                connection_url,
                pool_size=25,
                max_overflow=25,
                pool_timeout=30,
                pool_recycle=1800,  # Recycle connections after 30 minutes
                pool_pre_ping=True,  # Check connection validity before use
            )

            # Create session factory
            Session = async_sessionmaker(
                bind=engine,
                autoflush=False,
                expire_on_commit=False,
            )

            # Initialize database tables if they don't exist
            await cls._ensure_tables_exist(engine)

            # Cache and return the singleton instance
            cls._instance = cls(engine, Session)
            return cls._instance

    @staticmethod
    async def _ensure_database_exists(url: URL, database_name: str) -> None:
        """
        Check if the requested database exists and create it if it doesn't.

        Args:
            url: Connection string to the default postgres database
            database_name: Name of the database to check/create
        """
        # Create a temporary engine connected to the default postgres database
        temp_engine = create_async_engine(url)

        try:
            # Check if the database exists
            async with temp_engine.connect() as conn:
                result = await conn.execute(
                    text(f"SELECT 1 FROM pg_database WHERE datname = '{database_name}'")
                )
                exists = result.scalar() is not None

            # If database doesn't exist, create it
            if not exists:
                logger.info(f"Database '{database_name}' not found. Creating...")
                # Create a new connection with AUTOCOMMIT isolation level for database creation
                # Database creation needs to be outside a transaction
                conn = await temp_engine.connect()
                conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
                try:
                    await conn.execute(text(f"CREATE DATABASE {database_name}"))
                    logger.info(f"Database '{database_name}' created successfully")
                finally:
                    await conn.close()
            else:
                logger.info(f"Database '{database_name}' already exists")
        finally:
            await temp_engine.dispose()

    @staticmethod
    async def _ensure_tables_exist(engine: AsyncEngine) -> None:
        """Create all tables if they don't exist."""
        async with engine.begin() as conn:
            await conn.run_sync(SQLABase.metadata.create_all)
        logger.info("Database tables initialized successfully")

    async def drop_all_tables(self) -> None:
        """
        Drop all tables in the database.
        WARNING: This will permanently delete all data.
        """
        # Safety check to prevent dropping tables from the postgres system database
        if self.engine.url.database == "postgres":
            raise ValueError("Refusing to drop tables from the 'postgres' system database")

        async with self.engine.begin() as conn:
            await conn.run_sync(SQLABase.metadata.drop_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide a transactional scope around a series of operations."""
        session = self.Session()
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            logger.error("Rolled back database transaction")
            raise
        finally:
            await session.close()

    #############
    # FrameGrid #
    #############

    async def create(
        self, fg_id: str | None = None, name: str | None = None, description: str | None = None
    ):
        fg_id = fg_id or str(uuid4())
        async with self.session() as session:
            session.add(SQLAFrameGrid(id=fg_id, name=name, description=description))
        logger.info(f"Created FrameGrid with ID: {fg_id}")
        return fg_id

    async def update_framegrid(
        self,
        fg_id: str,
        name: str | None | _NotGiven = NOT_GIVEN,
        description: str | None | _NotGiven = NOT_GIVEN,
    ):
        """
        Update the name and/or description of a FrameGrid.
        Fields set to `None` will be nulled in the database.
        Fields not provided (i.e., left as NOT_GIVEN) will be unchanged.
        """
        values_to_update = {}
        if name is not NOT_GIVEN:
            values_to_update["name"] = name
        if description is not NOT_GIVEN:
            values_to_update["description"] = description

        if not values_to_update:
            logger.info(f"No values provided to update FrameGrid {fg_id}")
            return

        async with self.session() as session:
            await session.execute(
                update(SQLAFrameGrid).where(SQLAFrameGrid.id == fg_id).values(**values_to_update)
            )
        logger.info(f"Updated FrameGrid {fg_id} with values: {values_to_update}")

    async def exists(self, fg_id: str) -> bool:
        async with self.session() as session:
            result = await session.execute(select(exists().where(SQLAFrameGrid.id == fg_id)))
            return result.scalar_one()

    async def delete_framegrid(self, fg_id: str) -> None:
        # Remove all references from framegrid to other dimensions or filters
        async with self.session() as session:
            await session.execute(
                update(SQLAFrameGrid)
                .where(SQLAFrameGrid.id == fg_id)
                .values(outer_dim_id=None, inner_dim_id=None, base_filter_id=None)
            )

        # First delete all filters associated with this framegrid
        filter_ids = await self._get_filter_ids(fg_id)
        await self._delete_filters(fg_id, filter_ids)

        # Then delete all dimensions
        dim_ids = await self._get_dim_ids(fg_id)
        await self._delete_dimensions(fg_id, dim_ids)

        # Delete all attributes
        async with self.session() as session:
            await session.execute(delete(SQLAAttribute).where(SQLAAttribute.fg_id == fg_id))

        # Delete all transcripts
        async with self.session() as session:
            await session.execute(delete(SQLATranscript).where(SQLATranscript.fg_id == fg_id))

        # Delete all agent runs
        async with self.session() as session:
            await session.execute(delete(SQLAAgentRun).where(SQLAAgentRun.fg_id == fg_id))

        # Finally delete the framegrid
        async with self.session() as session:
            await session.execute(delete(SQLAFrameGrid).where(SQLAFrameGrid.id == fg_id))
            logger.info(f"Deleted framegrid {fg_id}")

    async def get_fgs(self) -> Sequence[SQLAFrameGrid]:
        """
        List all FrameGrids in the database.
        """
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameGrid).order_by(SQLAFrameGrid.created_at.desc())
            )
            return result.scalars().all()

    async def get_base_filter(self, fg_id: str) -> FrameFilter | None:
        """
        Get the base filter for a given FrameGrid ID.
        """
        # Get base filter, using the associated frame grid
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFilter)
                .where(SQLAFrameGrid.id == fg_id)
                .join(SQLAFrameGrid, SQLAFrameGrid.base_filter_id == SQLAFilter.id)
            )
            raw = result.scalar_one_or_none()

        filter = raw.to_filter() if raw else None
        if filter is None:
            return None
        if not filter.supports_sql:
            raise ValueError(f"Base filter must support SQL, got {filter.type} from the database")

        return filter

    async def set_base_filter(self, fg_id: str, base_filter: ComplexFilter | None):
        if base_filter is not None:
            if base_filter.op != "and":
                raise ValueError(
                    f"Base filter must be a conjunction (AND) of filters, got {base_filter.op}"
                )

        # Delete old filter
        cur_base_filter = await self.get_base_filter(fg_id)
        if cur_base_filter:
            async with self.session() as session:
                await session.execute(
                    update(SQLAFrameGrid)
                    .where(SQLAFrameGrid.id == fg_id)
                    .values(base_filter_id=None)
                )
            await self._delete_filters(fg_id, [cur_base_filter.id])

        # Push filter
        if base_filter is not None:
            async with self.session() as session:
                session.add(SQLAFilter.from_filter(base_filter, fg_id, None))

        # Attach filter to fg
        async with self.session() as session:
            await session.execute(
                update(SQLAFrameGrid)
                .where(SQLAFrameGrid.id == fg_id)
                .values(base_filter_id=base_filter.id if base_filter else None)
            )

        if base_filter is not None:
            logger.info(f"Pushed and set base filter {base_filter.id}")
        else:
            logger.info("Removed base filter")

    async def set_io_dim_with_metadata_key(
        self, fg_id: str, metadata_key: str, type: Literal["inner", "outer"]
    ):
        # Check if there's a MECE dimension already with this metadata key
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameDimension).where(
                    SQLAFrameDimension.fg_id == fg_id,
                    SQLAFrameDimension.metadata_key == metadata_key,
                    SQLAFrameDimension.maintain_mece,
                )
            )
            existing_dims = result.scalars().all()
            io_dim_id = existing_dims[0].id if existing_dims else None

        # If not, create one
        if io_dim_id is None:
            new_dim = FrameDimension(
                name=metadata_key,
                metadata_key=metadata_key,
                maintain_mece=True,
            )
            await self.upsert_dim(fg_id, new_dim, upsert_filters=False)
            io_dim_id = new_dim.id

        # Update the framegrid
        async with self.session() as session:
            await session.execute(
                update(SQLAFrameGrid)
                .where(SQLAFrameGrid.id == fg_id)
                .values(**{f"{type}_dim_id": io_dim_id})
            )

        # After setting, make sure they're re-clustered
        await self.cluster_metadata_dim(fg_id, io_dim_id)

        # Delete unused metadata dimensions
        await self._delete_unused_metadata_dims(fg_id)

    async def _delete_unused_metadata_dims(self, fg_id: str):
        # Get inner/outer_dim_ids
        io_dims = await self.get_io_dims(fg_id)
        if io_dims is None:
            inner_dim_id, outer_dim_id = None, None
        else:
            inner_dim_id, outer_dim_id = io_dims
        dims_ids_to_keep = [d for d in [inner_dim_id, outer_dim_id] if d is not None]

        # Delete any metadata dimension that isn't one of those two
        dims = await self.get_dims(fg_id)
        for dim in dims:
            if dim.metadata_key is not None and dim.id not in dims_ids_to_keep:
                logger.info(f"Deleting unused metadata dimension {dim.id}")
                await self.delete_dimension(fg_id, dim.id)

    async def set_io_dims(self, fg_id: str, inner_dim_id: str | None, outer_dim_id: str | None):
        async with self.session() as session:
            await session.execute(
                update(SQLAFrameGrid)
                .where(SQLAFrameGrid.id == fg_id)
                .values(inner_dim_id=inner_dim_id, outer_dim_id=outer_dim_id)
            )

        # After setting, make sure they're re-clustered
        async with anyio.create_task_group() as tg:
            for dim_id in [outer_dim_id, inner_dim_id]:
                if dim_id is not None:
                    tg.start_soon(self.cluster_metadata_dim, fg_id, dim_id)

        # Delete unused metadata dimensions
        await self._delete_unused_metadata_dims(fg_id)

    async def get_io_dims(self, fg_id: str) -> tuple[str | None, str | None] | None:
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameGrid.inner_dim_id, SQLAFrameGrid.outer_dim_id).where(
                    SQLAFrameGrid.id == fg_id
                )
            )
            row = result.one_or_none()
            return tuple(row) if row is not None else None

    ######################
    # Search persistence #
    ######################

    async def get_attribute_searches_with_judgment_counts(
        self, fg_id: str, base_data_only: bool = True
    ):
        base_filter = await self.get_base_filter(fg_id) if base_data_only else None

        async with self.session() as session:
            query = select(SQLAFrameDimension.id, SQLAFrameDimension.attribute).where(
                SQLAFrameDimension.fg_id == fg_id, SQLAFrameDimension.attribute.is_not(None)
            )
            result = await session.execute(query)
            dim_ids_and_attributes = result.all()

        # Consolidate set of attributes
        for _, attribute in dim_ids_and_attributes:
            assert attribute is not None, "We filtered out null attributes, this should not happen"
        attributes = list(set(cast(str, attribute) for _, attribute in dim_ids_and_attributes))

        # Get counts for each attribute
        async with self.session() as session:
            query = (
                select(SQLAAttribute.attribute, func.count(distinct(SQLAAttribute.agent_run_id)))
                .where(SQLAAttribute.fg_id == fg_id, SQLAAttribute.attribute.in_(attributes))
                .group_by(SQLAAttribute.attribute)
            )
            # Filter to attributes for agent runs that match the base filter
            where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None
            if where_clause is not None:
                query = query.join(
                    SQLAAgentRun, SQLAAgentRun.id == SQLAAttribute.agent_run_id
                ).where(where_clause)

            print(query.compile(compile_kwargs={"literal_binds": True}))
            result = await session.execute(query)
        counts = {attr: count for attr, count in result.all()}

        # Return dims with counts
        num_total = await self.count_base_agent_runs(fg_id)
        return [
            {
                "dim_id": dim_id,
                "attribute": attribute,
                "num_judgments_computed": counts.get(attribute, 0),
                "num_total": num_total,
            }
            for dim_id, attribute in dim_ids_and_attributes
        ]

    ##########################
    # Dimensions and filters #
    ##########################

    async def _delete_filters(self, fg_id: str, filter_ids: list[str]):
        async with self.session() as session:
            # Delete judgments for filters
            judgment_result = await session.execute(
                delete(SQLAJudgment).where(
                    SQLAJudgment.filter_id.in_(filter_ids), SQLAJudgment.fg_id == fg_id
                )
            )
            if (count := judgment_result.rowcount) > 0:
                logger.info(f"Deleted {count} judgments across {len(filter_ids)} filters")

            # Delete the filters themselves
            filter_result = await session.execute(
                delete(SQLAFilter).where(SQLAFilter.id.in_(filter_ids), SQLAFilter.fg_id == fg_id)
            )
            if (count := filter_result.rowcount) > 0:
                logger.info(f"Deleted {count} filters")

    async def set_dim_loading_state(
        self,
        fg_id: str,
        dim_id: str,
        loading_clusters: bool | None = None,
        loading_marginals: bool | None = None,
    ):
        values = {}
        if loading_clusters is not None:
            values["loading_clusters"] = loading_clusters
        if loading_marginals is not None:
            values["loading_marginals"] = loading_marginals

        async with self.session() as session:
            await session.execute(
                update(SQLAFrameDimension).where(SQLAFrameDimension.id == dim_id).values(**values)
            )

    async def upsert_dim(self, fg_id: str, dim: FrameDimension, upsert_filters: bool = True):
        """
        Generalized dimension upsert method that handles creating or updating dimensions and their filters.

        Args:
            fg_id: Frame grid ID
            dim: The dimension to upsert
            upsert_filters: Whether to update filters as well. If True, will delete and recreate filters that have changed.
        """
        existing_dim = await self.get_dim(fg_id, dim.id, include_bins=upsert_filters)

        # Create SQLAlchemy objects for the dimension and its filters
        sqla_dim, sqla_filters = SQLAFrameDimension.from_frame_dimension(dim, fg_id)

        # Update or create the dimension
        async with self.session() as session:
            if existing_dim:
                sqla_dim, _ = SQLAFrameDimension.from_frame_dimension(dim, fg_id)
                values = {k: v for k, v in sqla_dim.__dict__.items() if not k.startswith("_sa_")}
                await session.execute(
                    update(SQLAFrameDimension)
                    .where(
                        SQLAFrameDimension.id == dim.id,
                        SQLAFrameDimension.fg_id == fg_id,
                    )
                    .values(values)
                )  # TODO(mengk): check result
                logger.info(f"Updated dimension {dim.id} properties")
            else:
                # Create new dimension
                session.add(sqla_dim)
                logger.info(f"Created new dimension {dim.id}")

        # Determine whether any filters need to be replaced or deleted
        if upsert_filters and existing_dim:
            # Index filters by ID for easy lookup
            existing_filters = {f.id: f for f in existing_dim.bins} if existing_dim.bins else {}
            new_filters = {f.id: f for f in dim.bins} if dim.bins else {}
            existing_filter_ids = set(existing_filters.keys())
            new_filter_ids = set(new_filters.keys())

            # Filters to delete: existing filters not in new filters
            filters_to_delete = existing_filter_ids - new_filter_ids
            logger.info(f"Found {len(filters_to_delete)} filters to delete")

            # For filters that exist in both sets, check if they've changed in content
            if filters_to_check := existing_filter_ids.intersection(new_filter_ids):
                changed_filter_ids: set[str] = set(
                    filter_id
                    for filter_id in filters_to_check
                    if existing_filters[filter_id] != new_filters[filter_id]
                )
                logger.info(f"Found {len(changed_filter_ids)} changed filters")
            else:
                changed_filter_ids = set()

            # Remove all deleted and changed filters
            filter_ids_to_remove = filters_to_delete | changed_filter_ids
            if filter_ids_to_remove:
                await self._delete_filters(fg_id, list(filter_ids_to_remove))

            # Add filters: never seen before + changed
            filter_ids_to_add = (new_filter_ids - existing_filter_ids) | changed_filter_ids
            sqla_filters = [f for f in sqla_filters if f.id in filter_ids_to_add]

        # Add new or changed filters
        if sqla_filters and upsert_filters:
            async with self.session() as session:
                session.add_all(sqla_filters)
                logger.info(f"Added {len(sqla_filters)} new or changed filters")

        # If this is a metadata dimension with maintain_mece, cluster it
        if dim.metadata_key is not None and dim.maintain_mece:
            await self.cluster_metadata_dim(fg_id, dim.id)

        return dim.id

    async def get_dim(self, fg_id: str, dim_id: str, include_bins: bool = True):
        result = await self._get_dims(fg_id, [dim_id], include_bins)
        return result[0] if result else None

    async def get_dims(
        self, fg_id: str, dim_ids: list[str] | None = None, include_bins: bool = True
    ) -> list[FrameDimension]:
        return await self._get_dims(fg_id, dim_ids, include_bins)

    async def _get_dim_ids(self, fg_id: str) -> list[str]:
        """
        Get all dimension IDs for a given FrameGrid ID.
        """
        # Get dimensions matching the requested IDs
        async with self.session() as session:
            query = select(SQLAFrameDimension.id).where(SQLAFrameDimension.fg_id == fg_id)
            result = await session.execute(query)
            return cast(list[str], result.scalars().all())

    async def _get_dims(
        self, fg_id: str, dim_ids: list[str] | None = None, include_bins: bool = True
    ) -> list[FrameDimension]:
        """
        Get all dimensions for a given FrameGrid ID.
        """
        # Get dimensions matching the requested IDs
        async with self.session() as session:
            query = select(SQLAFrameDimension).where(SQLAFrameDimension.fg_id == fg_id)
            # Restrict to requested IDs if provided; otherwise, get all dimensions
            if dim_ids:
                query = query.where(SQLAFrameDimension.id.in_(dim_ids))
            result = await session.execute(query)
            sqla_dims = result.scalars().all()

        async def _get_dim_bins(dim_id: str):
            async with self.session() as session:
                result = await session.execute(
                    select(SQLAFilter).where(SQLAFilter.dimension_id == dim_id)
                )
                sqla_dim_bins = result.scalars().all()
                return [sqla_dim_bin.to_filter() for sqla_dim_bin in sqla_dim_bins]

        if include_bins:
            # In parallel, get all bins for all dimensions
            dim_bins = dict(
                zip(
                    [dim.id for dim in sqla_dims],
                    await asyncio.gather(*[_get_dim_bins(dim.id) for dim in sqla_dims]),
                )
            )
        else:
            dim_bins = {}

        return [dim.to_frame_dimension(dim_bins.get(dim.id)) for dim in sqla_dims]

    async def _get_filter_ids(self, fg_id: str) -> list[str]:
        async with self.session() as session:
            query = select(SQLAFilter.id).where(SQLAFilter.fg_id == fg_id)
            result = await session.execute(query)
            return cast(list[str], result.scalars().all())

    async def _get_filters(
        self, fg_id: str, filter_ids: list[str] | None = None
    ) -> list[FrameFilter]:
        async with self.session() as session:
            query = select(SQLAFilter).where(SQLAFilter.fg_id == fg_id)
            if filter_ids:
                query = query.where(SQLAFilter.id.in_(filter_ids))
            result = await session.execute(query)
            sqla_filters = result.scalars().all()
            return [sqla_filter.to_filter() for sqla_filter in sqla_filters]

    async def get_filter(self, fg_id: str, filter_id: str) -> FrameFilter | None:
        filters = await self._get_filters(fg_id, [filter_id])
        assert len(filters) <= 1, f"Expected 1 filter, got {len(filters)}"
        return filters[0] if filters else None

    async def add_filter(self, fg_id: str, filter: FrameFilter):
        async with self.session() as session:
            session.add(SQLAFilter.from_filter(filter, fg_id, None))
            logger.info(f"Added filter {filter.id}")

        return filter.id

    async def set_filter(self, fg_id: str, filter_id: str, filter: FrameFilter):
        if filter_id != filter.id:
            raise ValueError(f"Filter ID mismatch: {filter_id} != {filter.id}")

        async with self.session() as session:
            await session.execute(
                update(SQLAFilter)
                .where(SQLAFilter.id == filter_id, SQLAFilter.fg_id == fg_id)
                .values(filter_json=filter.model_dump())
            )
            logger.info(f"Updated filter {filter_id}")

            # Also need to invalidate all the judgments involving this filter
            judgment_result = await session.execute(
                delete(SQLAJudgment).where(
                    SQLAJudgment.filter_id == filter_id, SQLAJudgment.fg_id == fg_id
                )
            )
            logger.info(
                f"Deleted {judgment_result.rowcount} judgments associated with updated filter {filter_id}"
            )

    async def delete_filter(self, fg_id: str, filter_id: str):
        await self._delete_filters(fg_id, [filter_id])

    async def delete_dimension(self, fg_id: str, dim_id: str):
        await self._delete_dimensions(fg_id, [dim_id])

    async def _delete_dimensions(self, fg_id: str, dim_ids: list[str]):
        # Get all filters on these dimensions and delete them
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFilter.id)
                .join(SQLAFrameDimension, SQLAFrameDimension.id == SQLAFilter.dimension_id)
                .where(
                    SQLAFrameDimension.fg_id == fg_id,
                    SQLAFrameDimension.id.in_(dim_ids),
                )
            )
            filter_ids = cast(list[str], result.scalars().all())
        await self._delete_filters(fg_id, filter_ids)

        # Get the attributes for the dimensions to be deleted
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameDimension.attribute)
                .where(
                    SQLAFrameDimension.id.in_(dim_ids),
                    SQLAFrameDimension.fg_id == fg_id,
                    SQLAFrameDimension.attribute.isnot(None),
                )
                .distinct()
            )
            attributes_to_check = result.scalars().all()

        # Then delete the dimensions
        async with self.session() as session:
            result = await session.execute(
                delete(SQLAFrameDimension).where(
                    SQLAFrameDimension.id.in_(dim_ids), SQLAFrameDimension.fg_id == fg_id
                )
            )
            logger.info(f"Deleted {result.rowcount} dimensions")

        # If no more dimensions use this attribute, then clear them from the database
        for attribute in attributes_to_check:
            # Check if any other dimensions use this attribute
            async with self.session() as session:
                result = await session.execute(
                    select(func.count())
                    .select_from(SQLAFrameDimension)
                    .where(
                        SQLAFrameDimension.fg_id == fg_id,
                        SQLAFrameDimension.attribute == attribute,
                    )
                )
                remaining_count = result.scalar_one()

            # If no dimensions use this attribute anymore, delete all attributes with this name
            if remaining_count == 0:
                async with self.session() as session:
                    delete_result = await session.execute(
                        delete(SQLAAttribute).where(
                            SQLAAttribute.fg_id == fg_id,
                            SQLAAttribute.attribute == attribute,
                        )
                    )
                    logger.info(
                        f"Cleared {delete_result.rowcount} attributes for '{attribute}' as no dimensions use it anymore"
                    )

    ##############
    # Agent Runs #
    ##############

    async def add_agent_runs(self, fg_id: str, agent_runs: list[AgentRun]):
        async with self.session() as session:
            # Add agent runs
            session.add_all([SQLAAgentRun.from_agent_run(ar, fg_id) for ar in agent_runs])
            # Add associated transcripts
            sqla_transcripts = [
                SQLATranscript.from_transcript(t, dk, fg_id, ar.id)
                for ar in agent_runs
                for dk, t in ar.transcripts.items()
            ]
            session.add_all(sqla_transcripts)
        logger.info(f"Pushed {len(agent_runs)} agent runs and {len(sqla_transcripts)} transcripts")

        # Get all MECE metadata dimensions associated with this FG
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameDimension.id).where(
                    SQLAFrameDimension.fg_id == fg_id,
                    SQLAFrameDimension.metadata_key.isnot(None),
                    SQLAFrameDimension.maintain_mece,
                )
            )
            mece_dim_ids = result.scalars().all()

        # Re-cluster all MECE metadata dimensions
        async with anyio.create_task_group() as tg:
            for dim_id in mece_dim_ids:
                tg.start_soon(self.cluster_metadata_dim, fg_id, dim_id)

    async def get_agent_runs(
        self,
        fg_id: str,
        agent_run_ids: list[str] | None = None,
        where_clause: ColumnElement[bool] | None = None,
        limit: int | None = None,
    ) -> list[AgentRun]:
        """
        Get all agent runs for a given FrameGrid ID.
        """
        async with self.session() as session:
            # Get ARs
            query = select(SQLAAgentRun).where(SQLAAgentRun.fg_id == fg_id)
            if agent_run_ids is not None:
                query = query.where(SQLAAgentRun.id.in_(agent_run_ids))
            if where_clause is not None:
                query = query.where(where_clause)
            if limit is not None:
                query = query.limit(limit)
            result = await session.execute(query)
            agent_runs_raw = result.scalars().all()

            # Get transcripts for those ARs
            agent_run_ids = [ar.id for ar in agent_runs_raw]
            result = await session.execute(
                select(SQLATranscript).where(SQLATranscript.agent_run_id.in_(agent_run_ids))
            )
            transcripts_raw = result.scalars().all()

        # Collate run_id -> transcripts
        agent_run_transcripts: dict[str, list[tuple[str, Transcript]]] = {}
        for t_raw in transcripts_raw:
            agent_run_transcripts.setdefault(t_raw.agent_run_id, []).append(
                t_raw.to_dict_key_and_transcript()
            )

        return [
            ar_raw.to_agent_run(
                transcripts={dk: t for dk, t in agent_run_transcripts.get(ar_raw.id, [])}
            )
            for ar_raw in agent_runs_raw
        ]

    async def get_agent_run(self, fg_id: str, agent_run_id: str) -> AgentRun | None:
        """
        Get an AgentRun from the database by its ID.
        """
        agent_runs = await self.get_agent_runs(fg_id, [agent_run_id])
        assert len(agent_runs) <= 1, f"Found {len(agent_runs)} AgentRuns with ID {agent_run_id}"
        return agent_runs[0] if agent_runs else None

    async def get_any_agent_run(self, fg_id: str) -> AgentRun | None:
        """
        Get an arbitrary AgentRun from the database for a given FrameGrid ID.
        """
        agent_runs = await self.get_agent_runs(fg_id, limit=1)
        return agent_runs[0] if agent_runs else None

    async def get_base_agent_runs(self, fg_id: str) -> list[AgentRun]:
        base_filter = await self.get_base_filter(fg_id)
        where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None
        return await self.get_agent_runs(fg_id, where_clause=where_clause)

    async def count_base_agent_runs(self, fg_id: str) -> int:
        base_filter = await self.get_base_filter(fg_id)
        where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None

        async with self.session() as session:
            query = (
                select(func.count()).select_from(SQLAAgentRun).where(SQLAAgentRun.fg_id == fg_id)
            )
            if where_clause is not None:
                query = query.where(where_clause)

            result = await session.execute(query)
            return result.scalar_one()

    async def get_metadata_with_ids(self, fg_id: str, base_data_only: bool = True):
        base_filter = await self.get_base_filter(fg_id) if base_data_only else None
        where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None

        async with self.session() as session:
            query = select(SQLAAgentRun.id, SQLAAgentRun.metadata_json).where(
                SQLAAgentRun.fg_id == fg_id
            )
            if where_clause is not None:
                query = query.where(where_clause)

            result = await session.execute(query)
            raw = result.all()
            return [(m[0], BaseAgentRunMetadata.model_validate(m[1])) for m in raw]

    ##############
    # Attributes #
    ##############

    async def get_agent_runs_without_attribute(
        self, fg_id: str, attribute: str, base_filter: FrameFilter | None = None
    ) -> list[AgentRun]:
        where_clause = ~exists().where(
            SQLAAttribute.agent_run_id == SQLAAgentRun.id,
            SQLAAttribute.attribute == attribute,
        )
        # If base_data_only is True, we need to join with the base filter judgments
        base_where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None
        if base_where_clause is not None:
            where_clause = where_clause & base_where_clause

        return await self.get_agent_runs(fg_id, where_clause=where_clause)

    async def get_attributes(
        self,
        fg_id: str,
        attribute: str,
        base_data_only: bool = True,
    ) -> list[Attribute]:
        base_filter = await self.get_base_filter(fg_id) if base_data_only else None
        return await self._get_attributes(
            fg_id,
            attribute,
            base_filter=base_filter,
        )

    async def _get_attributes(
        self,
        fg_id: str,
        attribute: str,
        attribute_callback: AttributeStreamingCallback | None = None,
        base_filter: FrameFilter | None = None,
        ensure_fresh: bool = True,
    ) -> list[Attribute]:
        # Ensure we have fresh attributes
        if ensure_fresh:
            await self._compute_attributes(
                fg_id,
                attribute,
                attribute_callback=attribute_callback,
                base_filter=base_filter,
            )

        async with self.session() as session:
            query = select(SQLAAttribute).where(
                SQLAAttribute.fg_id == fg_id,
                SQLAAttribute.attribute == attribute,
            )
            where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None
            if where_clause is not None:
                query = query.join(
                    SQLAAgentRun, SQLAAgentRun.id == SQLAAttribute.agent_run_id
                ).where(where_clause)

            result = await session.execute(query)
            return [a.to_attribute() for a in result.scalars().all()]

    async def compute_diffs(
        self,
        fg_id: str,
        experiment_id_1: str,
        experiment_id_2: str,
        diff_callback: (
            Callable[[str, str, list[str], list[str]], Coroutine[Any, Any, None]] | None
        ) = None,
    ):
        # TODO(vincent): intersect with a filter, maybe allow user to pass in attribute as well
        # get pairs of datapoints from fg_id where (sample_id, task_id, epoch_id) match
        # and the datapoints have the corresponding experiment_id's

        # TODO(vincent): flexible binning and comparisons

        datapoints = await self.get_agent_runs(fg_id)

        print(f"have {len(datapoints)} datapoints")

        # group by sample_id, task_id, epoch_id
        datapoints_by_sample_task_epoch: dict[tuple[str, str, str], list[AgentRun]] = {}
        for dp in datapoints:
            key = (
                str(dp.metadata.get("sample_id")),
                str(dp.metadata.get("task_id")),
                str(dp.metadata.get("epoch_id")),
            )
            if key not in datapoints_by_sample_task_epoch:
                datapoints_by_sample_task_epoch[key] = []
            datapoints_by_sample_task_epoch[key].append(dp)

        # Get existing diff results from database
        async with self.session() as session:
            result = await session.execute(
                select(SQLADiffAttribute).where(
                    SQLADiffAttribute.frame_grid_id == fg_id,
                )
            )
            existing_diffs = result.scalars().all()
            existing_diff_pairs = {
                (diff.data_id_1, diff.data_id_2): diff for diff in existing_diffs
            }

        print(f"have {len(existing_diff_pairs)} existing diffs")
        for k in existing_diff_pairs:
            print(existing_diff_pairs[k].claim)

        # First stream existing diffs
        if diff_callback is not None:
            for (data_id_1, data_id_2), _ in existing_diff_pairs.items():
                # Group diffs by data_id pairs
                diffs_by_pair: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
                for d in existing_diffs:
                    if d.data_id_1 == data_id_1 and d.data_id_2 == data_id_2:
                        pair = (d.data_id_1, d.data_id_2)
                        if pair not in diffs_by_pair:
                            diffs_by_pair[pair] = ([], [])
                        if d.claim:
                            diffs_by_pair[pair][0].append(d.claim)
                            diffs_by_pair[pair][1].append(d.evidence)

                # Stream each pair's diffs
                for (d1, d2), (claims, evidences) in diffs_by_pair.items():
                    await diff_callback(d1, d2, claims, evidences)

        tasks: list[Coroutine[Any, Any, list[tuple[str, str]]]] = []
        pairs_to_compute: list[tuple[str, str]] = []

        for datapoint_lists in datapoints_by_sample_task_epoch.values():
            first_pair_candidates = [
                dp for dp in datapoint_lists if dp.metadata.get("experiment_id") == experiment_id_1
            ]
            second_pair_candidates = [
                dp for dp in datapoint_lists if dp.metadata.get("experiment_id") == experiment_id_2
            ]

            if len(first_pair_candidates) > 0 and len(second_pair_candidates) > 0:
                first_dp = first_pair_candidates[0]
                second_dp = second_pair_candidates[0]

                # Check if we already have results for this pair
                if (first_dp.id, second_dp.id) not in existing_diff_pairs:
                    tasks.append(
                        extract_states_and_diffs_2(
                            first_dp,
                            second_dp,
                        )
                    )
                    pairs_to_compute.append((first_dp.id, second_dp.id))

        logger.info(f"Computing diffs for {len(tasks)} new pairs")

        # Compute diffs for pairs that don't have results yet
        results = await asyncio.gather(*tasks)

        # Store results in database
        to_upload: list[SQLADiffAttribute] = []
        for (data_id_1, data_id_2), diff_results in zip(pairs_to_compute, results):
            if len(diff_results) == 0:
                to_upload.append(
                    SQLADiffAttribute.from_diff_attribute(
                        data_id_1=data_id_1,
                        data_id_2=data_id_2,
                        attribute="",  # unused for now
                        attribute_idx=None,
                        claim="",
                        evidence="",
                        fg_id=fg_id,
                    )
                )
                if diff_callback is not None:
                    await diff_callback(data_id_1, data_id_2, [], [])
                continue
            diffs: list[str] = []
            evidences: list[str] = []
            for i, (claim, evidence) in enumerate(diff_results):
                to_upload.append(
                    SQLADiffAttribute.from_diff_attribute(
                        data_id_1=data_id_1,
                        data_id_2=data_id_2,
                        attribute="",  # unused for now
                        attribute_idx=i,
                        claim=claim,
                        evidence=evidence,
                        fg_id=fg_id,
                    )
                )
                diffs.append(claim)
                evidences.append(evidence)
            if diff_callback is not None:
                await diff_callback(data_id_1, data_id_2, diffs, evidences)

        if to_upload:
            async with self.session() as session:
                session.add_all(to_upload)
                logger.info(f"Pushed {len(to_upload)} diff attributes")
        return to_upload

    async def compute_attributes(
        self,
        fg_id: str,
        attribute: str,
        attribute_callback: AttributeStreamingCallback | None = None,
        base_data_only: bool = True,
    ):
        base_filter = await self.get_base_filter(fg_id) if base_data_only else None
        await self._compute_attributes(
            fg_id,
            attribute,
            attribute_callback=attribute_callback,
            base_filter=base_filter,
        )

    async def _compute_attributes(
        self,
        fg_id: str,
        attribute: str,
        attribute_callback: AttributeStreamingCallback | None = None,
        base_filter: FrameFilter | None = None,
    ):
        # If the attribute callback is set, the caller is expecting all results to be streamed back
        # So, retrieve them and send them
        if attribute_callback is not None:
            attrs = await self._get_attributes(
                fg_id, attribute, base_filter=base_filter, ensure_fresh=False
            )
            await attribute_callback(attrs)

        # Figure out which datapoints don't have the attribute
        datapoints = await self.get_agent_runs_without_attribute(
            fg_id, attribute, base_filter=base_filter
        )
        if not datapoints:
            logger.info(f"All datapoints already have attribute {attribute}")
            return
        else:
            logger.info(f"Computing attributes for {len(datapoints)} datapoints")

        extracted_attrs: list[Attribute] = []

        async def _save_and_callback(attributes: list[Attribute]):
            """When each attribute comes back, both call the callback and also save to
            a running list of attributes that will be uploaded to the database.
            """
            nonlocal extracted_attrs

            extracted_attrs.extend(attributes)
            if attribute_callback:
                await attribute_callback(attributes)

        async def _upload():
            """Upload the attributes we have to the database."""
            nonlocal extracted_attrs

            with anyio.CancelScope(shield=True):
                to_upload: list[SQLAAttribute] = [
                    SQLAAttribute.from_attribute(
                        attribute=attr,
                        fg_id=fg_id,
                    )
                    for attr in extracted_attrs
                ]
                async with self.session() as session:
                    session.add_all(to_upload)

                logger.info(f"Pushed {len(to_upload)} attributes")

        try:
            await extract_attributes(datapoints, attribute, attribute_callback=_save_and_callback)
        except anyio.get_cancelled_exc_class():
            logger.info("Attribute computation cancelled")
        finally:
            # Upload what we have, even given cancellation
            await _upload()

    async def _get_agent_runs_without_judgments(
        self, fg_id: str, filter_id: str, base_filter: FrameFilter | None = None
    ) -> list[AgentRun]:
        # Does this datapoint have a judgment for the given filter?
        subquery = (
            select(SQLAJudgment.id)
            .where(SQLAJudgment.agent_run_id == SQLAAgentRun.id)
            .where(SQLAJudgment.filter_id == filter_id)
            .where(SQLAJudgment.fg_id == fg_id)
            .correlate(SQLAAgentRun)  # Explicitly correlate with the outer SQLAAgentRun table
            .exists()
        )
        where_clause = ~subquery

        # If base_filter is provided, filter to those
        base_where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None
        if base_where_clause is not None:
            where_clause = where_clause & base_where_clause

        return await self.get_agent_runs(fg_id, where_clause=where_clause)

    ######################
    # Filter computation #
    ######################

    async def compute_filter(
        self,
        fg_id: str,
        filter_id: str,
        base_data_only: bool = True,
    ):
        base_filter = await self.get_base_filter(fg_id) if base_data_only else None
        await self._compute_filter(fg_id, filter_id, base_filter=base_filter)

    async def _get_dim_filters_with_missing_judgments(
        self, fg_id: str, dim_id: str, base_filter: FrameFilter | None = None
    ) -> list[str]:
        """TODO(mengk): this function looks pretty slow on profiling; check runtime complexity
        and see if there are obvious issues.

        o3's attempt: https://chatgpt.com/share/680f2309-c3f0-800e-a8d7-7bb59b86cf7a

        Filters that support SQL are recomputed instantly when datapoints are added, deleted, or modified.
        They are assumed to never require recomputation.
        This is done because:
          - They are extremely cheap to recompute.
          - It is overwhelming to store False judgments for datapoints that
            don't match, since MetadataFilters often match only a few points.
        This is *not* done for more expensive filters (e.g., FramePredicates) because those
        are extremely slow.
        TODO(mengk): we should think of a way to efficiently check...
        """
        async with self.session() as session:
            # Build subquery that determines which datapoints match the base filter
            agent_runs_subquery = select(SQLAAgentRun.id).where(SQLAAgentRun.fg_id == fg_id)
            # If base_filter is provided, only consider datapoints that match it
            where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None
            if where_clause is not None:
                agent_runs_subquery = agent_runs_subquery.where(where_clause)

            # Main query to find filters with missing judgments
            query = (
                select(SQLAFilter.id)
                .where(
                    SQLAFilter.fg_id == fg_id,
                    SQLAFilter.dimension_id == dim_id,
                )
                .where(
                    exists(
                        select(SQLAAgentRun)
                        .where(SQLAAgentRun.id.in_(agent_runs_subquery))
                        .where(
                            ~exists(
                                select(1)
                                .select_from(SQLAJudgment)
                                .where(
                                    SQLAJudgment.agent_run_id == SQLAAgentRun.id,
                                    SQLAJudgment.filter_id == SQLAFilter.id,
                                )
                                .correlate_except(SQLAJudgment)
                            )
                        )
                    )
                )
            )

            result = await session.execute(query)
            return cast(list[str], result.scalars().all())

    async def _compute_filter(
        self,
        fg_id: str,
        filter_id: str,
        base_filter: FrameFilter | None = None,
    ):
        """
        FIXME(mengk): known concurrency issue: if the same filter is computed multiple times at once,
            you'll likely get a unique key violation error.
        """

        filter = await self.get_filter(fg_id, filter_id)
        if filter is None:
            raise ValueError(f"Filter ID {filter_id} not found")

        logger.info(f"Computing filter: {filter.name or filter.id}")

        if filter.supports_sql:
            # Get the SQLA where clause for the filter
            where_clause = filter.to_sqla_where_clause(SQLAAgentRun)
            assert (
                where_clause is not None
            ), f"Filter {filter.name} does not support SQL, even though it claims to"
            logger.info(f"Applying SQL WHERE clause: {where_clause}")

            # Delete existing judgments for this filter
            async with self.session() as session:
                await session.execute(
                    delete(SQLAJudgment).where(
                        SQLAJudgment.filter_id == filter_id,
                        SQLAJudgment.fg_id == fg_id,
                    )
                )

            # Get datapoints that match the WHERE clause and the base filter
            async with self.session() as session:
                query = select(SQLAAgentRun.id).where(
                    SQLAAgentRun.fg_id == fg_id,
                    where_clause,
                )
                # If base_filter is provided, we need to join with the base filter judgments
                base_where_clause = (
                    base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None
                )
                if base_where_clause is not None:
                    query = query.where(base_where_clause)

                # Execute
                result = await session.execute(query)
                datapoint_ids = result.scalars().all()

            # Convert into judgments
            judgments = [
                Judgment(agent_run_id=id, matches=True, filter_id=filter_id) for id in datapoint_ids
            ]
        else:
            # Which datapoints do not have judgments for this filter? Early exit if all fresh
            datapoints = await self._get_agent_runs_without_judgments(fg_id, filter_id, base_filter)
            if not datapoints:
                return

            logger.info(
                f"Found {len(datapoints)} datapoints without judgments for filter {filter.name}"
            )

            attributes = None  # Default to None, will be set if filter is a FramePredicate

            # If filter is a AttributePredicateFilter, it operates on attributes
            # Pull them down and insert them into the datapoints
            if filter.type == "attribute_predicate":
                datapoints_dict = {d.id: d for d in datapoints}
                attributes = await self._get_attributes(
                    fg_id, filter.attribute, base_filter=base_filter
                )
                datapoints = list(datapoints_dict.values())

            # Apply filter
            judgments = await filter.apply(datapoints, attributes, return_all=True)

        # Push matching judgments to the database
        async with self.session() as session:
            session.add_all([SQLAJudgment.from_judgment(j, fg_id) for j in judgments])
            logger.info(f"Pushed {len(judgments)} judgments")

    async def _refresh_metadata_dims(self, fg_id: str):
        dims = await self.get_dims(fg_id)
        for dim in dims:
            if dim.metadata_key is not None:
                await self.cluster_metadata_dim(fg_id, dim.id)

    @time_this
    async def cluster_metadata_dim(self, fg_id: str, dim_id: str):
        # Get rid of existing filters on this dim
        filters = await self.get_dim_filters(fg_id, dim_id)
        await self._delete_filters(fg_id, [f.id for f in filters])

        # Get metadata filter key
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameDimension.metadata_key).where(SQLAFrameDimension.id == dim_id)
            )
            metadata_key = result.scalar_one_or_none()
            if metadata_key is None:
                raise ValueError(
                    f"Dimension {dim_id} either not found or does not have a metadata key"
                )

        # Download *all* metadata to maintain the invariant that metadata filters are always fresh.
        # If there is a currently-active base filter, and we only get the base metadata,
        #   then the remaining datapoints will be missing judgments.
        all_metadata_with_ids = await self.get_metadata_with_ids(fg_id, base_data_only=False)

        # Collect all datapoints with each unique metadata value
        value_to_datapoint_ids: dict[Any, set[str]] = {}
        for id, metadata in all_metadata_with_ids:
            if (value := metadata.get(metadata_key)) is not None:
                value_to_datapoint_ids.setdefault(value, set()).add(id)

        # Create a MetadataFilter for each unique value
        filters = {
            value: SQLAFilter.from_filter(
                PrimitiveFilter(
                    name=str(value),
                    key_path=("metadata", metadata_key),
                    value=value,
                ),
                fg_id=fg_id,
                dim_id=dim_id,
            )
            for value in value_to_datapoint_ids.keys()
        }
        async with self.session() as session:
            session.add_all(filters.values())
            logger.info(f"Pushed {len(filters)} filters")

        # Add judgments for each match
        sqla_judgments: list[SQLAJudgment] = []
        for value, datapoint_ids in value_to_datapoint_ids.items():
            matching_judgments = [
                SQLAJudgment.from_judgment(
                    Judgment(agent_run_id=id, matches=True, filter_id=filters[value].id),
                    fg_id=fg_id,
                )
                for id in datapoint_ids
            ]
            sqla_judgments.extend(matching_judgments)
        async with self.session() as session:
            session.add_all(sqla_judgments)
            logger.info(f"Pushed {len(sqla_judgments)} judgments")

    async def cluster_attributes(
        self,
        fg_id: str,
        dim_id: str,
        n_clusters: int = 1,
        attribute_callback: AttributeStreamingCallback | None = None,
        base_data_only: bool = True,
    ):
        dim = await self.get_dim(fg_id, dim_id)
        if dim is None:
            raise ValueError(f"Dimension {dim_id} not found")
        if dim.attribute is None:
            raise ValueError(f"Dimension {dim_id} does not have an attribute")

        # Get attributes to cluster
        base_filter = await self.get_base_filter(fg_id) if base_data_only else None
        attributes = await self._get_attributes(
            fg_id,
            dim.attribute,
            attribute_callback=attribute_callback,
            base_filter=base_filter,
        )
        to_cluster = [a.value for a in attributes if a.value is not None]

        # Propose clusters with guidance on what attribute to focus on
        guidance = (
            f"Specifically focus on the following attribute: {dim.attribute}"
            if dim.attribute
            else None
        )
        proposals = await propose_clusters(
            to_cluster,
            n_clusters_list=[None],
            extra_instructions_list=[guidance],
            feedback_list=[],
            k=n_clusters,
        )
        predicates = proposals[0]

        # Delete existing filters
        await self._delete_filters(fg_id, [f.id for f in await self.get_dim_filters(fg_id, dim_id)])

        # Push filters
        sqla_filters = [
            SQLAFilter.from_filter(
                AttributePredicateFilter(
                    name=predicate,
                    predicate=predicate,
                    attribute=dim.attribute,
                    backend=dim.backend,
                    # llm_api_keys=llm_api_keys,
                ),
                fg_id,
                dim_id,
            )
            for predicate in predicates
        ]
        async with self.session() as session:
            session.add_all(sqla_filters)
            logger.info(f"Pushed {len(sqla_filters)} filters")

    ###################
    # Marginalization #
    ###################

    async def get_dim_filters(self, fg_id: str, dim_id: str):
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFilter).where(
                    SQLAFilter.dimension_id == dim_id, SQLAFilter.fg_id == fg_id
                )
            )
            return [r.to_filter() for r in result.scalars().all()]

    async def get_matching_judgments(self, fg_id: str, filter_id: str):
        async with self.session() as session:
            result = await session.execute(
                select(SQLAJudgment).where(
                    SQLAJudgment.filter_id == filter_id,
                    SQLAJudgment.fg_id == fg_id,
                    SQLAJudgment.matches,
                )
            )
            return [j.to_judgment() for j in result.scalars().all()]

    async def _get_dim_marginals(
        self,
        fg_id: str,
        dim: FrameDimension,
        base_filter: FrameFilter | None = None,
        ensure_fresh: bool = True,
        publish_dim_callback: Callable[[str], Awaitable[None]] | None = None,  # Arg: filter_id
    ):
        # Dimension is always fresh if it's a MECE metadata dim
        always_fresh = dim.metadata_key is not None and dim.maintain_mece

        if ensure_fresh and not always_fresh:
            # Which filters in this dim have missing judgments? Compute those.
            missing_judgment_filter_ids = await self._get_dim_filters_with_missing_judgments(
                fg_id, dim.id, base_filter
            )
            if missing_judgment_filter_ids:
                logger.info(
                    f"Found {len(missing_judgment_filter_ids)} filters with missing judgments in dim_id={dim.id}"
                )

                # Compute filters in parallel
                async with anyio.create_task_group() as tg:
                    if publish_dim_callback:

                        async def _mark_loading():
                            await self.set_dim_loading_state(fg_id, dim.id, loading_marginals=True)
                            await publish_dim_callback(dim.id)

                        tg.start_soon(_mark_loading)

                    for filter_id in missing_judgment_filter_ids:
                        tg.start_soon(self._compute_filter, fg_id, filter_id, base_filter)

                # Mark done loading after previous task group completes
                if publish_dim_callback:
                    await self.set_dim_loading_state(fg_id, dim.id, loading_marginals=False)
                    await publish_dim_callback(dim.id)

        # Get all (filter, datapoint) pairs for the current dim_id
        async with self.session() as session:
            query = (
                select(SQLAJudgment)
                .join(SQLAFilter, SQLAFilter.id == SQLAJudgment.filter_id)
                .where(SQLAFilter.dimension_id == dim.id, SQLAJudgment.matches)
            )

            # Ensure we only get judgments for datapoints that match the base filter
            where_clause = base_filter.to_sqla_where_clause(SQLAAgentRun) if base_filter else None
            if where_clause is not None:
                query = query.join(
                    SQLAAgentRun, SQLAAgentRun.id == SQLAJudgment.agent_run_id
                ).where(where_clause)

            result = await session.execute(query)
            raw = result.scalars().all()
            judgments = [(j.to_judgment(), j.filter_id) for j in raw]

        # Create bin_id -> datapoint_ids map
        marginal_map: dict[str, list[Judgment]] = {}
        for j, filter_id in judgments:
            marginal_map.setdefault(filter_id, []).append(j)

        return marginal_map

    async def get_marginals(
        self,
        fg_id: str,
        keep_dim_ids: list[str] | None = None,
        base_data_only: bool = True,
        ensure_fresh: bool = True,
        publish_dim_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, dict[str, list[Judgment]]]:
        base_filter = await self.get_base_filter(fg_id) if base_data_only else None
        dims_dict = {d.id: d for d in await self.get_dims(fg_id)}
        dim_ids = keep_dim_ids or list(dims_dict.keys())
        return dict(
            zip(
                dim_ids,
                await asyncio.gather(
                    *[
                        self._get_dim_marginals(
                            fg_id,
                            dims_dict[dim_id],
                            base_filter=base_filter,
                            ensure_fresh=ensure_fresh,
                            publish_dim_callback=publish_dim_callback,
                        )
                        for dim_id in dim_ids
                    ]
                ),
            )
        )

    async def marginalize(
        self,
        fg_id: str,
        keep_dim_ids: list[str],
        base_data_only: bool = True,
        return_dims_and_filters: bool = False,
        _marginals: dict[str, dict[str, list[Judgment]]] | None = None,
    ) -> MarginalizationResult:
        # Retrieve marginals for each dimension, or use the cached marginals if provided
        marginals = _marginals or await self.get_marginals(fg_id, keep_dim_ids, base_data_only)
        if not all(dim_id in marginals for dim_id in keep_dim_ids):
            raise ValueError(
                f"Requested marginals for dims {keep_dim_ids} but only found {marginals.keys()} in marginals"
            )

        # Convert marginals to sets
        marginals = {
            dim_id: {
                filter_id: set([j.agent_run_id for j in js])
                for filter_id, js in dim_marginals.items()
            }
            for dim_id, dim_marginals in marginals.items()
        }

        # Result variables
        result: dict[tuple[tuple[str, str], ...], Any] = {}
        dim_ids_to_filter_ids: dict[str, list[str]] = {}

        # Get the (dim_id, filter_id) pairs for each dimension
        filters_per_dim: list[list[tuple[str, str]]] = []
        for dim_id in keep_dim_ids:
            dim_filters = await self.get_dim_filters(fg_id, dim_id)
            filters_per_dim.append([(dim_id, filter.id) for filter in dim_filters])
            dim_ids_to_filter_ids[dim_id] = [filter.id for filter in dim_filters]

        # Iterate over the Cartesian product of the bins
        for bin_combination in product(*filters_per_dim):
            matching_ids: set[str] | None = None
            for dim_id, bin_id in bin_combination:
                # ANDing an empty set will still be empty
                if matching_ids is not None and len(matching_ids) == 0:
                    break

                cur_marginal = marginals.get(dim_id, {}).get(bin_id, None)

                # Some filters may not be in the marginals dict.
                # This is because the base filter may rule out all datapoints matching a filter.
                # The SQL query does not return filters with no matching datapoints, so cur_marginal is None.
                # In this case, we should skip the entire combination.
                if cur_marginal is None:
                    matching_ids = None
                    break

                # Collect the datapoint IDs that match the current filter
                if matching_ids is None:
                    matching_ids = cur_marginal.copy()
                else:
                    matching_ids &= cur_marginal

            if matching_ids is not None and len(matching_ids) > 0:
                result[bin_combination] = [
                    Judgment(agent_run_id=id, matches=True, filter_id="DOESN'T MATTER")
                    for id in matching_ids
                ]

        # Collect the actual dim and filter objects
        if return_dims_and_filters:
            dims_dict = {dim.id: dim for dim in await self._get_dims(fg_id, keep_dim_ids)}
            filters_dict = {
                f.id: f
                # Get all filters for all dimensions
                for f in await self._get_filters(
                    fg_id,
                    [
                        filter_id
                        for filter_ids in dim_ids_to_filter_ids.values()
                        for filter_id in filter_ids
                    ],
                )
            }
        else:
            dims_dict = None
            filters_dict = None

        return MarginalizationResult(
            marginals=result,
            dim_ids_to_filter_ids=dim_ids_to_filter_ids,
            dims_dict=dims_dict,
            filters_dict=filters_dict,
        )

    ########
    # Jobs #
    ########

    async def add_job(self, job_json: dict[str, Any], job_id: str | None = None) -> str:
        """
        Save a job specification to the database.

        Args:
            job_json: The job specification to save.
            job_id: Optional job ID. If None, a new UUID will be generated.

        Returns:
            The job ID.
        """
        job_id = job_id or str(uuid4())
        async with self.session() as session:
            session.add(SQLAJob(id=job_id, job_json=job_json))
            logger.info(f"Added job with ID: {job_id}")
        return job_id

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """
        Retrieve a job specification from the database.

        Args:
            job_id: The ID of the job to retrieve.

        Returns:
            The job specification as a dictionary, or None if not found.
        """
        async with self.session() as session:
            result = await session.execute(select(SQLAJob).where(SQLAJob.id == job_id))
            job = result.scalar_one_or_none()
            return job.job_json if job else None

    @asynccontextmanager
    async def advisory_lock(self, fg_id: str, action_id: str) -> AsyncIterator[None]:
        """Acquires a PostgreSQL advisory lock for the given FrameGrid ID and action ID.

        This provides a concurrency safety mechanism that can prevent race conditions
        when multiple processes or tasks attempt to modify the same FrameGrid data.

        Args:
            fg_id: The FrameGrid ID to lock
            action_id: An identifier for the action being performed

        Example:
            ```python
            async with db_service.advisory_lock(fg_id, "compute_filter"):
                # This code is protected by the lock
                await db_service.compute_filter(fg_id, filter_id)
            ```
        """
        # Create integer keys from the string IDs using hash functions
        # We use two separate hashing algorithms to minimize collision risk
        fg_hash = int(hashlib.md5(fg_id.encode()).hexdigest(), 16) % (2**31 - 1)
        action_hash = int(hashlib.sha1(action_id.encode()).hexdigest(), 16) % (2**31 - 1)

        async with self.session() as session:
            try:
                # Acquire the advisory lock
                await session.execute(
                    text("SELECT pg_advisory_lock(:key1, :key2)"),
                    {"key1": fg_hash, "key2": action_hash},
                )
                logger.info(f"Acquired advisory lock for {fg_id}/{action_id}")

                # Yield control back to the caller
                yield
            finally:
                # Always release the lock, even if an exception occurs
                await session.execute(
                    text("SELECT pg_advisory_unlock(:key1, :key2)"),
                    {"key1": fg_hash, "key2": action_hash},
                )
                logger.info(f"Released advisory lock for {fg_id}/{action_id}")
