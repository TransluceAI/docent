from __future__ import annotations

import asyncio
import functools
import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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
from sqlalchemy import URL, ColumnElement, delete, distinct, exists, func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from docent._ai_tools.clustering.cluster_diffs import cluster_diff_claims, search_over_diffs
from docent._ai_tools.clustering.cluster_generator import propose_clusters
from docent._ai_tools.diffs.llm_diff_summaries import compute_transcript_diff
from docent._ai_tools.diffs.models import Claim, SQLADiffsReport, TranscriptDiff
from docent._ai_tools.search import SearchResult, SearchResultStreamingCallback, execute_search
from docent._db_service.contexts import ViewContext
from docent._db_service.schemas.auth_models import (
    PERMISSION_LEVELS,
    Permission,
    ResourceType,
    SubjectType,
    User,
)
from docent._db_service.schemas.base import SQLABase
from docent._db_service.schemas.tables import (
    JobStatus,
    SQLAAccessControlEntry,
    SQLAAgentRun,
    SQLADiffAttribute,
    SQLAFilter,
    SQLAFrameDimension,
    SQLAFrameGrid,
    SQLAJob,
    SQLAJudgment,
    SQLASearchQuery,
    SQLASearchResult,
    SQLASession,
    SQLATranscript,
    SQLAUser,
    SQLAUserOrganization,
    SQLAView,
)
from docent._env_util import ENV
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun, BaseAgentRunMetadata
from docent.data_models.filters import (
    ComplexFilter,
    FrameDimension,
    FrameFilter,
    Judgment,
    PrimitiveFilter,
    SearchResultPredicateFilter,
)
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

    async def create_fg(
        self,
        user: User,
        fg_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ):
        # Create FG
        fg_id = fg_id or str(uuid4())
        async with self.session() as session:
            session.add(
                SQLAFrameGrid(id=fg_id, name=name, description=description, created_by=user.id)
            )

        # Create ACL entry for the user
        await self.set_acl_permission(
            SubjectType.USER,
            subject_id=user.id,
            resource_type=ResourceType.FRAME_GRID,
            resource_id=fg_id,
            permission=Permission.ADMIN,
        )

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

    async def delete_fg(self, fg_id: str) -> None:
        # Remove all references from views to other dimensions and filters
        async with self.session() as session:
            await session.execute(
                update(SQLAView)
                .where(SQLAView.fg_id == fg_id)
                .values(outer_dim_id=None, inner_dim_id=None, base_filter_id=None)
            )

        # First delete all filters associated with this framegrid
        async with self.session() as session:
            query = select(SQLAFilter.id).where(SQLAFilter.fg_id == fg_id)
            result = await session.execute(query)
            filter_ids = cast(list[str], result.scalars().all())
        await self._delete_filters(filter_ids)

        # Then delete all dimensions
        async with self.session() as session:
            query = select(SQLAFrameDimension.id).where(SQLAFrameDimension.fg_id == fg_id)
            result = await session.execute(query)
            dim_ids = cast(list[str], result.scalars().all())
        await self._delete_dimensions(dim_ids)

        # Delete all attributes
        async with self.session() as session:
            await session.execute(delete(SQLASearchResult).where(SQLASearchResult.fg_id == fg_id))

        # Delete all transcripts
        async with self.session() as session:
            await session.execute(delete(SQLATranscript).where(SQLATranscript.fg_id == fg_id))

        # Delete all agent runs
        async with self.session() as session:
            await session.execute(delete(SQLAAgentRun).where(SQLAAgentRun.fg_id == fg_id))

        # Delete views
        async with self.session() as session:
            await session.execute(delete(SQLAView).where(SQLAView.fg_id == fg_id))

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

        # Get all MECE metadata dimensions associated with this FG, regardless of view
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameDimension.id, SQLAFrameDimension.view_id).where(
                    SQLAFrameDimension.fg_id == fg_id,
                    SQLAFrameDimension.metadata_key.isnot(None),
                    SQLAFrameDimension.maintain_mece,
                )
            )
            mece_dim_ids_and_view_ids = result.all()

        # Re-cluster all MECE metadata dimensions
        async with anyio.create_task_group() as tg:
            for dim_id, view_id in mece_dim_ids_and_view_ids:
                cur_ctx = await self.get_view_ctx(view_id)
                tg.start_soon(self.cluster_metadata_dim, cur_ctx, dim_id)

    async def get_agent_runs(
        self,
        ctx: ViewContext,
        agent_run_ids: list[str] | None = None,
        _where_clause: ColumnElement[bool] | None = None,
        _limit: int | None = None,
    ) -> list[AgentRun]:
        """
        Get all agent runs for a given FrameGrid ID.
        """
        async with self.session() as session:
            # Get runs
            query = select(SQLAAgentRun).where(ctx.get_base_where_clause(SQLAAgentRun))
            if agent_run_ids is not None:
                query = query.where(SQLAAgentRun.id.in_(agent_run_ids))
            if _where_clause is not None:
                query = query.where(_where_clause)
            if _limit is not None:
                query = query.limit(_limit)
            result = await session.execute(query)
            agent_runs_raw = result.scalars().all()

            # Get transcripts for those runs
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

    async def get_agent_run(self, ctx: ViewContext, agent_run_id: str) -> AgentRun | None:
        """
        Get an AgentRun from the database by its ID.
        """
        agent_runs = await self.get_agent_runs(
            ctx, _where_clause=SQLAAgentRun.id.in_([agent_run_id])
        )
        assert len(agent_runs) <= 1, f"Found {len(agent_runs)} AgentRuns with ID {agent_run_id}"
        return agent_runs[0] if agent_runs else None

    async def get_any_agent_run(self, ctx: ViewContext) -> AgentRun | None:
        """
        Get an arbitrary AgentRun from the database for a given FrameGrid ID.
        """
        agent_runs = await self.get_agent_runs(ctx, _limit=1)
        return agent_runs[0] if agent_runs else None

    async def count_base_agent_runs(self, ctx: ViewContext) -> int:
        async with self.session() as session:
            query = (
                select(func.count())
                .select_from(SQLAAgentRun)
                .where(ctx.get_base_where_clause(SQLAAgentRun))
            )
            result = await session.execute(query)
            return result.scalar_one()

    async def get_metadata_with_ids(self, ctx: ViewContext):
        async with self.session() as session:
            query = select(SQLAAgentRun.id, SQLAAgentRun.metadata_json).where(
                ctx.get_base_where_clause(SQLAAgentRun)
            )

            result = await session.execute(query)
            raw = result.all()
            return [(m[0], BaseAgentRunMetadata.model_validate(m[1])) for m in raw]

    #########
    # Views #
    #########

    async def get_all_view_ctxs(self, fg_id: str) -> list[ViewContext]:
        async with self.session() as session:
            result = await session.execute(select(SQLAView.id).where(SQLAView.fg_id == fg_id))
            view_ids = result.scalars().all()
            return [await self.get_view_ctx(view_id) for view_id in view_ids]

    async def get_view_ctx(self, view_id: str) -> ViewContext:
        async with self.session() as session:
            # Get the view
            result = await session.execute(select(SQLAView).where(SQLAView.id == view_id))
            view = result.scalar_one_or_none()
            if view is None:
                raise ValueError(f"View with ID {view_id} not found")

            # Get the base filter for this view
            base_filter = (
                await self.get_filter(view.base_filter_id)
                if view.base_filter_id is not None
                else None
            )
            # Check that the base filter is a ComplexFilter
            if base_filter is not None:
                assert isinstance(base_filter, ComplexFilter), "Base filter must be a ComplexFilter"

            return ViewContext(fg_id=view.fg_id, view_id=view.id, base_filter=base_filter)

    async def get_default_view_ctx(self, fg_id: str) -> ViewContext:
        # Check if a default view exists for this fg
        async with self.session() as session:
            result = await session.execute(
                select(SQLAView).where(SQLAView.fg_id == fg_id, SQLAView.is_default)
            )
            view = result.scalar_one_or_none()

        # If not, create a new view whose admin is the user who created the FG
        if view is None:
            async with self.session() as session:
                view = SQLAView(
                    id=str(uuid4()),
                    fg_id=fg_id,
                    is_default=True,
                )
                session.add(view)

            # Who created the FG?
            async with self.session() as session:
                result = await session.execute(
                    select(SQLAFrameGrid.created_by).where(SQLAFrameGrid.id == fg_id)
                )
                user_id = result.scalar_one()

            # Create ACL entry for the user
            await self.set_acl_permission(
                SubjectType.USER,
                subject_id=user_id,
                resource_type=ResourceType.VIEW,
                resource_id=view.id,
                permission=Permission.ADMIN,
            )

        # Get the base filter for this view
        base_filter = (
            await self.get_filter(view.base_filter_id) if view.base_filter_id is not None else None
        )
        # Check that the base filter is a ComplexFilter
        if base_filter is not None:
            assert isinstance(base_filter, ComplexFilter), "Base filter must be a ComplexFilter"

        return ViewContext(fg_id=fg_id, view_id=view.id, base_filter=base_filter)

    async def set_view_base_filter(self, ctx: ViewContext, filter: ComplexFilter):
        # Clear the old base filter
        await self.clear_view_base_filter(ctx)

        # Add the new filter
        async with self.session() as session:
            sqla_filter = SQLAFilter.from_filter(filter, ctx)
            session.add(sqla_filter)
            logger.info(f"Added filter {filter.id} to view {ctx.view_id}")

        # Set the base filter
        async with self.session() as session:
            await session.execute(
                update(SQLAView)
                .where(SQLAView.id == ctx.view_id)
                .values(base_filter_id=sqla_filter.id)
            )

        new_ctx = ViewContext(fg_id=ctx.fg_id, view_id=ctx.view_id, base_filter=filter)

        # Base filter might trigger a new clustering of metadata dimensions
        await self._refresh_metadata_dims(new_ctx)

        return new_ctx

    async def clear_view_base_filter(self, ctx: ViewContext):
        if ctx.base_filter is not None:
            # Unset the base filter
            async with self.session() as session:
                await session.execute(
                    update(SQLAView).where(SQLAView.id == ctx.view_id).values(base_filter_id=None)
                )

            # Delete the filter
            await self.delete_filter(ctx.base_filter.id)

        new_ctx = ViewContext(fg_id=ctx.fg_id, view_id=ctx.view_id, base_filter=None)

        # Base filter might trigger a new clustering of metadata dimensions
        await self._refresh_metadata_dims(new_ctx)

        return new_ctx

    async def set_io_dim_with_metadata_key(
        self, ctx: ViewContext, metadata_key: str, type: Literal["inner", "outer"]
    ):
        # Check if there's a MECE dimension already with this metadata key
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameDimension).where(
                    SQLAFrameDimension.fg_id == ctx.fg_id,
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
            await self.upsert_dim(ctx, new_dim, upsert_filters=False)
            io_dim_id = new_dim.id

        # Update the view
        async with self.session() as session:
            await session.execute(
                update(SQLAView)
                .where(SQLAView.id == ctx.view_id)
                .values(**{f"{type}_dim_id": io_dim_id})
            )

        # After setting, make sure they're re-clustered
        await self.cluster_metadata_dim(ctx, io_dim_id)

        # Delete unused metadata dimensions
        await self._delete_unused_metadata_dims(ctx.fg_id)

    async def _delete_unused_metadata_dims(self, fg_id: str):
        # Get inner/outer_dim_ids from ALL views in this framegrid, not just one view
        async with self.session() as session:
            result = await session.execute(
                select(SQLAView.inner_dim_id, SQLAView.outer_dim_id).where(SQLAView.fg_id == fg_id)
            )
            all_view_dims = result.all()

        # Collect all dimension IDs used by ANY view in this framegrid
        dims_ids_to_keep: set[str] = set()
        for inner_dim_id, outer_dim_id in all_view_dims:
            if inner_dim_id:
                dims_ids_to_keep.add(inner_dim_id)
            if outer_dim_id:
                dims_ids_to_keep.add(outer_dim_id)

        # Delete any metadata dimension that isn't used by any view
        dims = await self._get_fg_dims(fg_id)
        for dim in dims:
            if dim.metadata_key is not None and dim.id not in dims_ids_to_keep:
                logger.info(f"Deleting unused metadata dimension {dim.id}")
                await self.delete_dimension(dim.id)

    async def set_io_dims(
        self, ctx: ViewContext, inner_dim_id: str | None, outer_dim_id: str | None
    ):
        async with self.session() as session:
            await session.execute(
                update(SQLAView)
                .where(SQLAView.id == ctx.view_id)
                .values(inner_dim_id=inner_dim_id, outer_dim_id=outer_dim_id)
            )

        # After setting, make sure they're re-clustered
        async with anyio.create_task_group() as tg:
            for dim_id in [outer_dim_id, inner_dim_id]:
                if dim_id is not None:
                    tg.start_soon(self.cluster_metadata_dim, ctx, dim_id)

        # Delete unused metadata dimensions
        await self._delete_unused_metadata_dims(ctx.fg_id)

    async def get_io_dims(self, ctx: ViewContext) -> tuple[str | None, str | None] | None:
        async with self.session() as session:
            result = await session.execute(
                select(SQLAView.inner_dim_id, SQLAView.outer_dim_id).where(
                    SQLAView.id == ctx.view_id
                )
            )
            row = result.one_or_none()
            return tuple(row) if row is not None else None

    ##########################
    # Dimensions and filters #
    ##########################

    async def _delete_filters(self, filter_ids: list[str]):
        async with self.session() as session:
            # Delete judgments for filters
            judgment_result = await session.execute(
                delete(SQLAJudgment).where(SQLAJudgment.filter_id.in_(filter_ids))
            )
            if (count := judgment_result.rowcount) > 0:
                logger.info(f"Deleted {count} judgments across {len(filter_ids)} filters")

            # Delete the filters themselves
            filter_result = await session.execute(
                delete(SQLAFilter).where(SQLAFilter.id.in_(filter_ids))
            )
            if (count := filter_result.rowcount) > 0:
                logger.info(f"Deleted {count} filters")

    async def set_dim_loading_state(
        self,
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

    async def upsert_dim(self, ctx: ViewContext, dim: FrameDimension, upsert_filters: bool = True):
        """
        Generalized dimension upsert method that handles creating or updating dimensions and their filters.

        Args:
            fg_id: Frame grid ID
            dim: The dimension to upsert
            upsert_filters: Whether to update filters as well. If True, will delete and recreate filters that have changed.
        """
        existing_dim = await self.get_dim(dim.id, include_bins=upsert_filters)

        # Create SQLAlchemy objects for the dimension and its filters
        sqla_dim, sqla_filters = SQLAFrameDimension.from_frame_dimension(dim, ctx)

        # Update or create the dimension
        async with self.session() as session:
            if existing_dim:
                sqla_dim, _ = SQLAFrameDimension.from_frame_dimension(dim, ctx)
                values = {k: v for k, v in sqla_dim.__dict__.items() if not k.startswith("_sa_")}
                await session.execute(
                    update(SQLAFrameDimension).where(SQLAFrameDimension.id == dim.id).values(values)
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
                await self._delete_filters(list(filter_ids_to_remove))

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
            await self.cluster_metadata_dim(ctx, dim.id)

        return dim.id

    async def get_dim(self, dim_id: str, include_bins: bool = True):
        result = await self._get_specific_dims([dim_id], include_bins)
        assert len(result) <= 1, f"Expected at most 1 dimension, got {len(result)}"
        return result[0] if result else None

    async def get_dims(self, dim_ids: list[str], include_bins: bool = True) -> list[FrameDimension]:
        return await self._get_specific_dims(dim_ids, include_bins)

    async def _populate_dims_with_filters(
        self, sqla_dims: Sequence[SQLAFrameDimension], include_bins: bool = True
    ) -> list[FrameDimension]:
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

    async def _get_fg_dims(self, fg_id: str, include_bins: bool = False) -> list[FrameDimension]:
        async with self.session() as session:
            query = select(SQLAFrameDimension).where(SQLAFrameDimension.fg_id == fg_id)
            result = await session.execute(query)
            sqla_dims = result.scalars().all()

        return await self._populate_dims_with_filters(sqla_dims, include_bins)

    async def get_view_dims(
        self, ctx: ViewContext, include_bins: bool = True
    ) -> list[FrameDimension]:
        # Get dimensions matching the requested IDs
        async with self.session() as session:
            query = select(SQLAFrameDimension).where(SQLAFrameDimension.view_id == ctx.view_id)
            result = await session.execute(query)
            sqla_dims = result.scalars().all()

        return await self._populate_dims_with_filters(sqla_dims, include_bins)

    async def _get_specific_dims(
        self, dim_ids: list[str], include_bins: bool = True
    ) -> list[FrameDimension]:
        # Get dimensions matching the requested IDs
        async with self.session() as session:
            query = select(SQLAFrameDimension).where(SQLAFrameDimension.id.in_(dim_ids))
            result = await session.execute(query)
            sqla_dims = result.scalars().all()

        return await self._populate_dims_with_filters(sqla_dims, include_bins)

    async def _get_filter_ids(self, ctx: ViewContext) -> list[str]:
        async with self.session() as session:
            query = select(SQLAFilter.id).where(SQLAFilter.view_id == ctx.view_id)
            result = await session.execute(query)
            return cast(list[str], result.scalars().all())

    async def _get_view_filters(self, ctx: ViewContext) -> list[FrameFilter]:
        async with self.session() as session:
            query = select(SQLAFilter).where(SQLAFilter.view_id == ctx.view_id)
            result = await session.execute(query)
            sqla_filters = result.scalars().all()
            return [sqla_filter.to_filter() for sqla_filter in sqla_filters]

    async def _get_specific_filters(self, filter_ids: list[str]) -> list[FrameFilter]:
        async with self.session() as session:
            query = select(SQLAFilter).where(SQLAFilter.id.in_(filter_ids))
            result = await session.execute(query)
            sqla_filters = result.scalars().all()
            return [sqla_filter.to_filter() for sqla_filter in sqla_filters]

    async def get_filter(self, filter_id: str) -> FrameFilter | None:
        filters = await self._get_specific_filters([filter_id])
        assert len(filters) <= 1, f"Expected at most 1 filter, got {len(filters)}"
        return filters[0] if filters else None

    async def set_filter(self, filter_id: str, filter: FrameFilter):
        if filter_id != filter.id:
            raise ValueError(f"Filter ID mismatch: {filter_id} != {filter.id}")

        async with self.session() as session:
            await session.execute(
                update(SQLAFilter)
                .where(SQLAFilter.id == filter_id)
                .values(filter_json=filter.model_dump())
            )
            logger.info(f"Updated filter {filter_id}")

            # Also need to invalidate all the judgments involving this filter
            judgment_result = await session.execute(
                delete(SQLAJudgment).where(SQLAJudgment.filter_id == filter_id)
            )
            logger.info(
                f"Deleted {judgment_result.rowcount} judgments associated with updated filter {filter_id}"
            )

    async def delete_filter(self, filter_id: str):
        await self._delete_filters([filter_id])

    async def delete_dimension(self, dim_id: str):
        await self._delete_dimensions([dim_id])

    async def _delete_dimensions(self, dim_ids: list[str]):
        # Get all filters on these dimensions and delete them
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFilter.id)
                .join(SQLAFrameDimension, SQLAFrameDimension.id == SQLAFilter.dimension_id)
                .where(SQLAFrameDimension.id.in_(dim_ids))
            )
            filter_ids = cast(list[str], result.scalars().all())
        await self._delete_filters(filter_ids)

        # Then delete the dimensions
        async with self.session() as session:
            result = await session.execute(
                delete(SQLAFrameDimension).where(SQLAFrameDimension.id.in_(dim_ids))
            )
            logger.info(f"Deleted {result.rowcount} dimensions")

    ############
    # Searches #
    ############

    async def add_search_query(self, ctx: ViewContext, search_query: str) -> str:
        """
        Add a search query to the SQLASearchQuery table if it does not already exist.
        Returns the id of the search query.
        """
        async with self.session() as session:
            # Check if the search query already exists for this frame grid
            result = await session.execute(
                select(SQLASearchQuery).where(
                    SQLASearchQuery.fg_id == ctx.fg_id,
                    SQLASearchQuery.search_query == search_query,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                return existing.id

        # Otherwise, create a new search query
        async with self.session() as session:
            new_id = str(uuid4())
            sq = SQLASearchQuery(
                id=new_id,
                fg_id=ctx.fg_id,
                search_query=search_query,
            )
            session.add(sq)

        logger.info(f"Added new search query {search_query} with id {new_id} to fg_id {ctx.fg_id}")
        return new_id

    async def get_search_query(self, query_id: str) -> SQLASearchQuery:
        async with self.session() as session:
            # Check if the search query already exists for this frame grid
            result = await session.execute(
                select(SQLASearchQuery).where(SQLASearchQuery.id == query_id)
            )
            return result.scalar_one()

    async def delete_search_query(self, fg_id: str, search_query_id: str):
        """
        Delete a search query from the database.

        Args:
            search_query_id: The ID of the search query to delete

        Returns:
            True if the search query was found and deleted, False otherwise
        """
        # Delete search results
        async with self.session() as session:
            await session.execute(
                delete(SQLASearchQuery).where(SQLASearchQuery.id == search_query_id)
            )

        # Get all search queries
        async with self.session() as session:
            result = await session.execute(
                select(SQLASearchQuery.search_query).where(SQLASearchQuery.fg_id == fg_id)
            )
            search_queries = list(set(result.scalars().all()))

        # Get dimensions with queries that no searches require
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFrameDimension.id).where(
                    SQLAFrameDimension.fg_id == fg_id,
                    SQLAFrameDimension.search_query.isnot(None),
                    ~SQLAFrameDimension.search_query.in_(search_queries),
                )
            )
            dim_ids = cast(list[str], result.scalars().all())

        # Delete them
        await self._delete_dimensions(dim_ids)

    async def get_searches_with_result_counts(self, ctx: ViewContext) -> list[dict[str, Any]]:
        # Get search result queries
        async with self.session() as session:
            query = select(SQLASearchQuery.id, SQLASearchQuery.search_query).where(
                SQLASearchQuery.fg_id == ctx.fg_id
            )
            result = await session.execute(query)
            search_ids_and_queries = result.all()

        # Consolidate set of search queries
        for _, query in search_ids_and_queries:
            assert query is not None, "We filtered out null search queries, this should not happen"
        search_queries = list(set(cast(str, query) for _, query in search_ids_and_queries))

        # Get counts of agent runs that these search queries have been run against
        async with self.session() as session:
            query = (
                select(
                    SQLASearchResult.search_query,
                    func.count(distinct(SQLASearchResult.agent_run_id)),
                )
                .where(SQLASearchResult.search_query.in_(search_queries))
                .join(SQLAAgentRun, SQLASearchResult.agent_run_id == SQLAAgentRun.id)
                .where(
                    ctx.get_base_where_clause(SQLAAgentRun),
                )
                .group_by(SQLASearchResult.search_query)
            )
            result = await session.execute(query)

        latest_jobs = {query.id: job for job, query in await self.list_search_jobs_and_queries()}

        # Return search queries with judgment counts
        counts = {query: count for query, count in result.all()}
        num_total = await self.count_base_agent_runs(ctx)
        return [
            {
                "search_id": search_id,
                "search_query": search_query,
                "num_judgments_computed": counts.get(search_query, 0),
                "num_total": num_total,
                "job": latest_jobs[search_id],
            }
            for search_id, search_query in search_ids_and_queries
        ]

    async def _get_agent_runs_without_search_results(
        self, ctx: ViewContext, search_query: str
    ) -> list[AgentRun]:
        where_clause = ~exists().where(
            SQLASearchResult.agent_run_id == SQLAAgentRun.id,
            SQLASearchResult.search_query == search_query,
        )
        return await self.get_agent_runs(ctx, _where_clause=where_clause)

    async def get_search_results(
        self,
        ctx: ViewContext,
        search_query: str,
    ) -> list[SearchResult]:
        return await self._get_search_results(ctx, search_query)

    async def _get_search_results(
        self,
        ctx: ViewContext,
        search_query: str,
        search_result_callback: SearchResultStreamingCallback | None = None,
        ensure_fresh: bool = True,
    ) -> list[SearchResult]:
        # Ensure we have fresh search results
        if ensure_fresh:
            await self.compute_search(
                ctx,
                search_query,
                search_result_callback=search_result_callback,
            )

        async with self.session() as session:
            query = (
                select(SQLASearchResult)
                .where(SQLASearchResult.search_query == search_query)
                .join(SQLAAgentRun, SQLASearchResult.agent_run_id == SQLAAgentRun.id)
                .where(ctx.get_base_where_clause(SQLAAgentRun))
            )

            result = await session.execute(query)
            return [a.to_search_result() for a in result.scalars().all()]

    async def get_diffs_report(self, diffs_report_id: str) -> SQLADiffsReport:
        async with self.session() as session:
            result = await session.execute(
                select(SQLADiffsReport).where(SQLADiffsReport.id == diffs_report_id)
            )
        return result.scalar_one()

    async def compute_diffs(
        self,
        ctx: ViewContext,
        diffs_report_id: str,
        diff_callback: Callable[[TranscriptDiff | None], Coroutine[Any, Any, None]] | None = None,
        should_include_existing_diffs: bool = False,
        should_persist: bool = True,
    ):
        # TODO(vincent): intersect with a filter, maybe allow user to pass in attribute as well
        # get pairs of datapoints from fg_id where (sample_id, task_id, epoch_id) match
        # and the datapoints have the corresponding experiment_id's

        # TODO(vincent): flexible binning and comparisons

        datapoints = await self.get_agent_runs(ctx)
        from docent._ai_tools.diffs.models import SQLADiffsReport

        dbs = self.Session()
        result = await dbs.execute(
            select(SQLADiffsReport).where(SQLADiffsReport.id == diffs_report_id)
        )
        diffs_report = result.scalar_one()
        experiment_id_1 = diffs_report.experiment_id_1
        experiment_id_2 = diffs_report.experiment_id_2

        print(f"have {len(datapoints)} datapoints", experiment_id_1, experiment_id_2)

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

        existing_diff_pairs = {}
        from docent._ai_tools.diffs.models import SQLATranscriptDiff

        if should_include_existing_diffs:
            # Get existing diff results from database
            async with self.session() as session:

                result = await session.execute(
                    select(SQLATranscriptDiff).where(
                        SQLATranscriptDiff.frame_grid_id == ctx.fg_id,
                    )
                )
                existing_diffs = result.scalars().all()
                # TODO(vincent): we didn't actually check for exp_ids...

            # Stream existing diffs
            if diff_callback is not None:
                for diff in existing_diffs:
                    print(diff)
                    await diff_callback(diff.to_pydantic())

        tasks: list[Coroutine[Any, Any, TranscriptDiff]] = []
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
                    tasks.append(compute_transcript_diff(first_dp, second_dp, diffs_report_id))
                    pairs_to_compute.append((first_dp.id, second_dp.id))

        logger.info(f"Computing diffs for {len(tasks)} new pairs")

        # Compute diffs for pairs that don't have results yet
        results = await asyncio.gather(*tasks)

        # Store results in database if should_persist is True

        from docent._ai_tools.diffs.models import SQLATranscriptDiff

        transcript_diffs_models: list[SQLATranscriptDiff] = []
        for transcript_diff in results:
            transcript_diffs_models.append(SQLATranscriptDiff.from_pydantic(transcript_diff, ctx))
            if diff_callback is not None:
                await diff_callback(transcript_diff)

        print("tdms", transcript_diffs_models)
        if transcript_diffs_models and should_persist:
            for transcript_diff in transcript_diffs_models:
                transcript_diff.diffs_report_id = diffs_report.id
            dbs.add_all(transcript_diffs_models)
            dbs.add(diffs_report)
            await dbs.commit()
            logger.info(
                f"Pushed {len(transcript_diffs_models)} diff attributes and updated Report{diffs_report.id}"
            )
        return transcript_diffs_models

    async def compute_search(
        self,
        ctx: ViewContext,
        search_query: str,
        search_result_callback: SearchResultStreamingCallback | None = None,
    ):
        # If the callback is set, the caller is expecting all results to be streamed back
        # So, retrieve them and send them
        if search_result_callback is not None:
            existing_search_results = await self._get_search_results(
                ctx, search_query, ensure_fresh=False
            )
            if existing_search_results:
                await search_result_callback(existing_search_results)

        # Figure out which datapoints don't have search results computed
        agent_runs = await self._get_agent_runs_without_search_results(ctx, search_query)
        if not agent_runs:
            logger.info(f"All datapoints already have results for {search_query}")
            return
        else:
            logger.info(f"Computing results for {len(agent_runs)} datapoints")

        async def _results_callback(search_results: list[SearchResult] | None):
            if search_result_callback:
                await search_result_callback(search_results)

            with anyio.CancelScope(shield=True):
                if search_results is None:
                    return
                to_upload: list[SQLASearchResult] = [
                    SQLASearchResult.from_search_result(
                        search_result=attr,
                        fg_id=ctx.fg_id,
                    )
                    for attr in search_results
                ]
                async with self.session() as session:
                    session.add_all(to_upload)

                logger.info(f"Pushed {len(to_upload)} attributes")

        try:
            await execute_search(agent_runs, search_query, search_result_callback=_results_callback)
        except anyio.get_cancelled_exc_class():
            logger.info("Attribute computation cancelled")

    async def _get_agent_runs_without_judgments(
        self, ctx: ViewContext, filter_id: str
    ) -> list[AgentRun]:
        # Does this datapoint have a judgment for the given filter?
        subquery = (
            select(SQLAJudgment.id)
            .where(SQLAJudgment.agent_run_id == SQLAAgentRun.id)
            .where(SQLAJudgment.filter_id == filter_id)
            .correlate(SQLAAgentRun)  # Explicitly correlate with the outer SQLAAgentRun table
            .exists()
        )
        where_clause = ~subquery

        return await self.get_agent_runs(ctx, _where_clause=where_clause)

    #########################################
    # Computing filters and clustering dims #
    #########################################

    async def compute_filter(
        self,
        ctx: ViewContext,
        filter_id: str,
    ):
        await self._compute_filter(ctx, filter_id)

    async def _get_dim_filters_with_missing_judgments(
        self, ctx: ViewContext, dim_id: str
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
            # Subquery that determines which datapoints match the base filter
            agent_runs_subquery = select(SQLAAgentRun.id).where(
                ctx.get_base_where_clause(SQLAAgentRun)
            )

            # Main query to find filters with missing judgments
            query = (
                select(SQLAFilter.id)
                .where(SQLAFilter.dimension_id == dim_id)
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
        ctx: ViewContext,
        filter_id: str,
    ):
        """
        FIXME(mengk): known concurrency issue: if the same filter is computed multiple times at once,
            you'll likely get a unique key violation error.
        """

        filter = await self.get_filter(filter_id)
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
                    delete(SQLAJudgment).where(SQLAJudgment.filter_id == filter_id)
                )

            # Get datapoints that match the WHERE clause and the base filter
            async with self.session() as session:
                query = select(SQLAAgentRun.id).where(
                    ctx.get_base_where_clause(SQLAAgentRun),
                    where_clause,
                )
                result = await session.execute(query)
                datapoint_ids = result.scalars().all()

            # Convert into judgments
            judgments = [
                Judgment(agent_run_id=id, matches=True, filter_id=filter_id) for id in datapoint_ids
            ]
        else:
            # Which datapoints do not have judgments for this filter? Early exit if all fresh
            agent_runs = await self._get_agent_runs_without_judgments(ctx, filter_id)
            if not agent_runs:
                return

            logger.info(
                f"Found {len(agent_runs)} datapoints without judgments for filter {filter.name}"
            )

            search_results = None  # Default to None, will be set if filter is a FramePredicate

            # If filter is a SearchResultPredicateFilter, it operates on search results
            # Pull them down and insert them into the datapoints
            if filter.type == "search_result_predicate":
                datapoints_dict = {d.id: d for d in agent_runs}
                search_results = await self._get_search_results(ctx, filter.search_query)
                agent_runs = list(datapoints_dict.values())

            # Apply filter
            judgments = await filter.apply(agent_runs, search_results, return_all=True)

        # Push matching judgments to the database
        async with self.session() as session:
            session.add_all([SQLAJudgment.from_judgment(j, ctx.fg_id) for j in judgments])
            logger.info(f"Pushed {len(judgments)} judgments")

    async def _refresh_metadata_dims(self, ctx: ViewContext):
        dims = await self.get_view_dims(ctx)
        for dim in dims:
            if dim.metadata_key is not None:
                print(f"Refreshing metadata dim {dim.id}")
                await self.cluster_metadata_dim(ctx, dim.id)

    async def cluster_metadata_dim(self, ctx: ViewContext, dim_id: str):
        # Get rid of existing filters on this dim
        filters = await self._get_dim_filters(dim_id)
        await self._delete_filters([f.id for f in filters])

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

        all_metadata_with_ids = await self.get_metadata_with_ids(ctx)

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
                ctx=ctx,
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
                    fg_id=ctx.fg_id,
                )
                for id in datapoint_ids
            ]
            sqla_judgments.extend(matching_judgments)
        async with self.session() as session:
            session.add_all(sqla_judgments)
            logger.info(f"Pushed {len(sqla_judgments)} judgments")

    async def cluster_search_results(
        self,
        ctx: ViewContext,
        dim_id: str,
        n_proposals: int = 1,
        search_result_callback: SearchResultStreamingCallback | None = None,
    ):
        dim = await self.get_dim(dim_id)
        if dim is None:
            raise ValueError(f"Dimension {dim_id} not found")
        if dim.search_query is None:
            raise ValueError(f"Dimension {dim_id} does not have an attribute")

        # Get attributes to cluster
        search_results = await self._get_search_results(
            ctx,
            dim.search_query,
            search_result_callback=search_result_callback,
        )
        to_cluster = [a.value for a in search_results if a.value is not None]

        # Propose clusters with guidance on what attribute to focus on
        guidance = f"Specifically focus on the following attribute: {dim.search_query}"
        proposals = await propose_clusters(
            to_cluster,
            n_clusters_list=[None],
            extra_instructions_list=[guidance],
            feedback_list=[],
            k=n_proposals,
        )
        predicates = proposals[0]

        # Delete existing filters
        await self._delete_filters([f.id for f in await self._get_dim_filters(dim_id)])

        # Push filters
        sqla_filters = [
            SQLAFilter.from_filter(
                SearchResultPredicateFilter(
                    name=predicate,
                    predicate=predicate,
                    search_query=dim.search_query,
                ),
                ctx,
                dim_id,
            )
            for predicate in predicates
        ]
        async with self.session() as session:
            session.add_all(sqla_filters)
            logger.info(f"Pushed {len(sqla_filters)} filters")

    #########################
    # Clustering diffs
    #########################

    async def compute_diff_clusters(
        self,
        ctx: ViewContext,
        claims: list[Claim],
    ):
        # datapoints = await self.get_agent_runs(ctx)
        # expid_by_datapoint = {d.id: d.metadata.get("experiment_id") for d in datapoints}
        # async with self.session() as session:
        #     result = await session.execute(
        #         select(SQLADiffAttribute)
        #         .where(
        #             SQLADiffAttribute.frame_grid_id == ctx.fg_id,
        #         )
        #         .order_by(SQLADiffAttribute.id)
        #     )
        #     existing_diffs = result.scalars().all()
        # valid_existing_diffs = [
        #     d.to_diff_attribute()
        #     for d in existing_diffs
        #     if expid_by_datapoint.get(d.data_id_1) == experiment_id_1
        #     and expid_by_datapoint.get(d.data_id_2) == experiment_id_2
        # ]
        # print(f"have {len(valid_existing_diffs)} valid existing diffs")
        print("-------------------------------- Claims --------------------------------")
        print(claims)

        clusters = await cluster_diff_claims(claims)
        return clusters

    async def compute_diff_search(
        self,
        ctx: ViewContext,
        experiment_id_1: str,
        experiment_id_2: str,
        search_query: str,
        search_result_callback: (
            Callable[[tuple[str, int]], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> list[tuple[str, int]]:
        datapoints = await self.get_agent_runs(ctx)
        expid_by_datapoint = {d.id: d.metadata.get("experiment_id") for d in datapoints}
        async with self.session() as session:
            result = await session.execute(
                select(SQLADiffAttribute)
                .where(
                    SQLADiffAttribute.frame_grid_id == ctx.fg_id,
                )
                .order_by(SQLADiffAttribute.id)
            )
            existing_diffs = result.scalars().all()
        valid_existing_diffs = [
            d.to_diff_attribute()
            for d in existing_diffs
            if expid_by_datapoint.get(d.data_id_1) == experiment_id_1
            and expid_by_datapoint.get(d.data_id_2) == experiment_id_2
        ]

        results = await search_over_diffs(
            search_query,
            [d.claim or "" for d in valid_existing_diffs],
            search_result_callback=search_result_callback,
        )

        # TODO(vincent): stream the results
        return results

    ###################
    # Marginalization #
    ###################

    async def _get_dim_filters(self, dim_id: str):
        async with self.session() as session:
            result = await session.execute(
                select(SQLAFilter).where(SQLAFilter.dimension_id == dim_id)
            )
            return [r.to_filter() for r in result.scalars().all()]

    async def get_matching_judgments(self, filter_id: str):
        async with self.session() as session:
            result = await session.execute(
                select(SQLAJudgment).where(
                    SQLAJudgment.filter_id == filter_id,
                    SQLAJudgment.matches,
                )
            )
            return [j.to_judgment() for j in result.scalars().all()]

    async def _get_dim_marginals(
        self,
        ctx: ViewContext,
        dim: FrameDimension,
        ensure_fresh: bool = True,
        publish_dim_callback: Callable[[str], Awaitable[None]] | None = None,  # Arg: filter_id
    ):
        # Dimension is always fresh if it's a MECE metadata dim
        always_fresh = dim.metadata_key is not None and dim.maintain_mece

        if ensure_fresh and not always_fresh:
            # Which filters in this dim have missing judgments? Compute those.
            missing_judgment_filter_ids = await self._get_dim_filters_with_missing_judgments(
                ctx, dim.id
            )
            if missing_judgment_filter_ids:
                logger.info(
                    f"Found {len(missing_judgment_filter_ids)} filters with missing judgments in dim_id={dim.id}"
                )

                # Compute filters in parallel
                async with anyio.create_task_group() as tg:
                    if publish_dim_callback:

                        async def _mark_loading():
                            await self.set_dim_loading_state(dim.id, loading_marginals=True)
                            await publish_dim_callback(dim.id)

                        tg.start_soon(_mark_loading)

                    for filter_id in missing_judgment_filter_ids:
                        tg.start_soon(self._compute_filter, ctx, filter_id)

                # Mark done loading after previous task group completes
                if publish_dim_callback:
                    await self.set_dim_loading_state(dim.id, loading_marginals=False)
                    await publish_dim_callback(dim.id)

        # Get all (filter, datapoint) pairs for the current dim_id
        async with self.session() as session:
            query = (
                select(SQLAJudgment)
                .join(SQLAFilter, SQLAFilter.id == SQLAJudgment.filter_id)
                .where(SQLAFilter.dimension_id == dim.id, SQLAJudgment.matches)
            )

            # Ensure we only get judgments for datapoints that match the base filter
            query = query.join(SQLAAgentRun, SQLAAgentRun.id == SQLAJudgment.agent_run_id).where(
                ctx.get_base_where_clause(SQLAAgentRun)
            )

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
        ctx: ViewContext,
        keep_dim_ids: list[str] | None = None,
        ensure_fresh: bool = True,
        publish_dim_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, dict[str, list[Judgment]]]:
        dims_dict = {d.id: d for d in await self.get_view_dims(ctx)}
        dim_ids = keep_dim_ids or list(dims_dict.keys())
        return dict(
            zip(
                dim_ids,
                await asyncio.gather(
                    *[
                        self._get_dim_marginals(
                            ctx,
                            dims_dict[dim_id],
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
        ctx: ViewContext,
        keep_dim_ids: list[str],
        return_dims_and_filters: bool = False,
        _marginals: dict[str, dict[str, list[Judgment]]] | None = None,
    ) -> MarginalizationResult:
        # Retrieve marginals for each dimension, or use the cached marginals if provided
        marginals = _marginals or await self.get_marginals(ctx, keep_dim_ids)
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
            dim_filters = await self._get_dim_filters(dim_id)
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
            dims_dict = {dim.id: dim for dim in await self._get_specific_dims(keep_dim_ids)}
            filters_dict = {
                f.id: f
                # Get all filters for all dimensions
                for f in await self._get_specific_filters(
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

    async def add_job(self, type: str, job_json: dict[str, Any], job_id: str | None = None) -> str:
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
            session.add(SQLAJob(id=job_id, type=type, created_at=datetime.now(), job_json=job_json))
            logger.info(f"Added job with ID: {job_id}")
        return job_id

    async def add_search_job(self, query_id: str) -> tuple[bool, str]:
        """
        Adds or finds a search job for the given query. The first return value is whether this
        call added a new job.
        """
        async with self.session() as session:
            # Check if an equivalent job already exists
            result = await session.execute(
                select(SQLAJob)
                .filter(SQLAJob.type == "compute_search")
                .filter(SQLAJob.job_json["query_id"].astext == query_id)
                .order_by(SQLAJob.created_at.desc())
                .limit(1)
            )
            existing: SQLAJob | None = result.scalar_one_or_none()
            if existing is not None and existing.status in [JobStatus.PENDING, JobStatus.RUNNING]:
                return False, existing.id

            # Otherwise, create a new job
            job_id = str(uuid4())
            session.add(SQLAJob(id=job_id, type="compute_search", job_json={"query_id": query_id}))
            logger.info(f"Added job with ID: {job_id}")

            return True, job_id

    async def get_job(self, job_id: str) -> SQLAJob | None:
        """
        Retrieve a job specification from the database.

        Args:
            job_id: The ID of the job to retrieve.

        Returns:
            The job specification as a dictionary, or None if not found.
        """
        async with self.session() as session:
            result = await session.execute(select(SQLAJob).where(SQLAJob.id == job_id))
            return result.scalar_one_or_none()

    async def list_search_jobs_and_queries(self) -> list[tuple[SQLAJob, SQLASearchQuery]]:
        async with self.session() as session:
            # Find the latest job creation time corresponding to each query ID.
            sub_q = (
                select(
                    SQLAJob.job_json["query_id"].astext.label("query_id"),
                    func.max(SQLAJob.created_at).label("created_at"),
                )
                .group_by("query_id")
                .filter(SQLAJob.type == "compute_search")
            ).subquery()
            # Find all search queries, along with the latest job corresponding to each one.
            q = (
                select(SQLAJob, SQLASearchQuery)
                .select_from(sub_q)
                .filter(SQLAJob.type == "compute_search")
                .filter(SQLASearchQuery.id == sub_q.c.query_id)
                .filter(SQLAJob.created_at == sub_q.c.created_at)
                .order_by(SQLASearchQuery.created_at.desc())
            )
            result = await session.execute(q)

        return result.all()

    async def set_job_status(self, job_id: str, status: JobStatus):
        async with self.session() as session:
            await session.execute(
                update(SQLAJob).filter(SQLAJob.id == job_id).values(status=status)
            )

    async def get_search_job_and_query(
        self, job_id: str
    ) -> tuple[dict[Any, Any], SQLASearchQuery] | None:
        async with self.session() as session:
            result = await session.execute(
                select(SQLAJob, SQLASearchQuery)
                .filter(SQLAJob.id == job_id)
                .filter(SQLAJob.type == "compute_search")
                .filter(SQLAJob.job_json["query_id"].astext == SQLASearchQuery.id)
            )

        row = result.one_or_none()
        if row is None:
            return None
        job, query = row
        return job.job_json, query

    #########
    # Users #
    #########

    async def get_users(self) -> list[User]:
        async with self.session() as session:
            # Get all users
            users_result = await session.execute(select(SQLAUser))
            sqla_users = users_result.scalars().all()

            # Get all user-organization relationships
            user_orgs_result = await session.execute(select(SQLAUserOrganization))
            user_orgs = user_orgs_result.scalars().all()

            # Group organizations by user_id
            user_org_map: dict[str, list[str]] = {}
            for user_org in user_orgs:
                user_org_map.setdefault(user_org.user_id, []).append(user_org.organization_id)

            # Convert to User objects with organization_ids
            return [
                user.to_user(organization_ids=user_org_map.get(user.id, [])) for user in sqla_users
            ]

    async def create_user(self, email: str) -> User:
        """
        Create a new user. Raises an error if a user with the given email already exists.

        Args:
            email: The email address of the user

        Returns:
            The User object
        """
        # Check if user already exists
        existing_user = await self.get_user_by_email(email)
        if existing_user:
            raise ValueError("User already exists for {email}")

        user_id = str(uuid4())
        sqla_user = SQLAUser(id=user_id, email=email)

        async with self.session() as session:
            session.add(sqla_user)

        logger.info(f"Created new user with ID: {sqla_user.id} and email: {sqla_user.email}")
        return sqla_user.to_user(organization_ids=[])

    async def create_anonymous_user(self) -> User:
        """
        Create an anonymous user that is persisted to the database.

        Returns:
            A User object with anonymous properties
        """
        user_id = str(uuid4())
        email = f"anonymous_{user_id}"

        # Persist anonymous user to database
        async with self.session() as session:
            sqla_user = SQLAUser(id=user_id, email=email, is_anonymous=True)
            session.add(sqla_user)

        logger.info(f"Created anonymous user with ID: {user_id}")
        return sqla_user.to_user(organization_ids=[])

    async def get_user_by_email(self, email: str) -> User | None:
        """
        Retrieve a user by email address.

        Args:
            email: The email address to search for

        Returns:
            The User object if found, None otherwise
        """
        async with self.session() as session:
            # Get the user
            result = await session.execute(select(SQLAUser).where(SQLAUser.email == email))
            sqla_user = result.scalar_one_or_none()
            if not sqla_user:
                return None

            # Get the user's organization IDs
            org_result = await session.execute(
                select(SQLAUserOrganization.organization_id).where(
                    SQLAUserOrganization.user_id == sqla_user.id
                )
            )
            organization_ids = org_result.scalars().all()

            return sqla_user.to_user(organization_ids=list(organization_ids))

    async def create_session(self, user_id: str, expires_in_days: int = 30) -> str:
        """
        Create a new session for a user.

        Args:
            user_id: The user ID to create a session for
            expires_in_days: Number of days until the session expires

        Returns:
            The session ID
        """

        session_id = str(uuid4())
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=expires_in_days)

        async with self.session() as session:
            session.add(
                SQLASession(
                    id=session_id,
                    user_id=user_id,
                    expires_at=expires_at,
                    is_active=True,
                )
            )
        logger.info(f"Created session {session_id} for user {user_id}")
        return session_id

    async def get_user_by_session_id(self, session_id: str) -> User | None:
        """
        Retrieve a user by their session ID.

        Args:
            session_id: The session ID to look up

        Returns:
            The User object if the session is valid and active, None otherwise
        """
        async with self.session() as session:
            # Join session and user tables, check if session is active and not expired
            result = await session.execute(
                select(SQLAUser)
                .join(SQLASession, SQLAUser.id == SQLASession.user_id)
                .where(
                    SQLASession.id == session_id,
                    SQLASession.is_active,
                    SQLASession.expires_at > datetime.now(UTC).replace(tzinfo=None),
                )
            )
            sqla_user = result.scalar_one_or_none()
            if not sqla_user:
                return None

            # Get the user's organization IDs
            org_result = await session.execute(
                select(SQLAUserOrganization.organization_id).where(
                    SQLAUserOrganization.user_id == sqla_user.id
                )
            )
            organization_ids = org_result.scalars().all()

            return sqla_user.to_user(organization_ids=list(organization_ids))

    async def invalidate_session(self, session_id: str) -> bool:
        """
        Invalidate a session by marking it as inactive.

        Args:
            session_id: The session ID to invalidate

        Returns:
            True if the session was found and invalidated, False otherwise
        """
        async with self.session() as session:
            result = await session.execute(
                update(SQLASession).where(SQLASession.id == session_id).values(is_active=False)
            )
            return result.rowcount > 0

    ###############
    # Permissions #
    ###############

    async def has_permission(
        self,
        user: User,
        resource_type: ResourceType,
        resource_id: str,
        permission: Permission,
    ) -> bool:
        user_permission_level = await self.get_permission_level(user, resource_type, resource_id)
        if user_permission_level is None:
            return False
        return user_permission_level.includes(permission)

    async def get_permission_level(
        self,
        user: User,
        resource_type: ResourceType,
        resource_id: str,
    ) -> Permission | None:
        """Get the highest permission level a user has for a resource."""

        # Build the resource filter based on ResourceType
        if resource_type == ResourceType.FRAME_GRID:
            resource_filter = SQLAAccessControlEntry.fg_id == resource_id
        elif resource_type == ResourceType.VIEW:
            resource_filter = SQLAAccessControlEntry.view_id == resource_id
        else:
            raise ValueError(f"Unsupported resource type: {resource_type}")

        all_perm_strs: list[str] = []

        async with self.session() as session:
            # Check public permissions
            public_permission_result = await session.execute(
                select(SQLAAccessControlEntry.permission).where(
                    SQLAAccessControlEntry.is_public,
                    resource_filter,
                )
            )
            all_perm_strs.extend(public_permission_result.scalars().all())

            # Check direct user permissions
            direct_permission_result = await session.execute(
                select(SQLAAccessControlEntry.permission).where(
                    SQLAAccessControlEntry.user_id == user.id,
                    resource_filter,
                )
            )
            all_perm_strs.extend(direct_permission_result.scalars().all())

            # Check organization permissions for all user's organizations
            if user.organization_ids:
                org_permission_result = await session.execute(
                    select(SQLAAccessControlEntry.permission).where(
                        SQLAAccessControlEntry.organization_id.in_(user.organization_ids),
                        resource_filter,
                    )
                )
                all_perm_strs.extend(org_permission_result.scalars().all())

        # Return the highest permission level
        if not all_perm_strs:
            return None
        return Permission(max(all_perm_strs, key=lambda p: PERMISSION_LEVELS[p]))

    async def set_acl_permission(
        self,
        subject_type: SubjectType,
        subject_id: str,
        resource_type: ResourceType,
        resource_id: str,
        permission: Permission,
    ) -> None:
        # Build the resource filter based on ResourceType
        if resource_type == ResourceType.FRAME_GRID:
            resource_filter = SQLAAccessControlEntry.fg_id == resource_id
            resource_fields = {"fg_id": resource_id, "view_id": None}
        elif resource_type == ResourceType.VIEW:
            resource_filter = SQLAAccessControlEntry.view_id == resource_id
            resource_fields = {"fg_id": None, "view_id": resource_id}
        else:
            raise ValueError(f"Unsupported resource type: {resource_type}")

        # Build the subject filter and fields based on SubjectType
        if subject_type == SubjectType.USER:
            subject_filter = SQLAAccessControlEntry.user_id == subject_id
            subject_fields = {
                "user_id": subject_id,
                "organization_id": None,
                "is_public": False,
            }
        elif subject_type == SubjectType.ORGANIZATION:
            subject_filter = SQLAAccessControlEntry.organization_id == subject_id
            subject_fields = {
                "user_id": None,
                "organization_id": subject_id,
                "is_public": False,
            }
        elif subject_type == SubjectType.PUBLIC:
            subject_filter = SQLAAccessControlEntry.is_public
            subject_fields = {"user_id": None, "organization_id": None, "is_public": True}
        else:
            raise ValueError(f"Unsupported subject type: {subject_type}")

        # Check if any permission already exists for this subject/resource combination
        async with self.session() as session:
            existing = await session.execute(
                select(SQLAAccessControlEntry).where(
                    subject_filter,
                    resource_filter,
                )
            )
            existing_entry = existing.scalar_one_or_none()

        # Permission doesn't exist, create it
        if existing_entry is None:
            acl_entry = SQLAAccessControlEntry(
                id=str(uuid4()),
                permission=permission.value,
                **subject_fields,
                **resource_fields,
            )

            async with self.session() as session:
                session.add(acl_entry)

            logger.info(
                f"Granted {permission.value} permission on {resource_type.value}:{resource_id} "
                f"to {subject_type.value}:{subject_id}"
            )

        # Permission exists, update it
        else:
            async with self.session() as session:
                await session.execute(
                    update(SQLAAccessControlEntry)
                    .where(SQLAAccessControlEntry.id == existing_entry.id)
                    .values(
                        **subject_fields,
                        **resource_fields,
                        permission=permission.value,
                    )
                )

            logger.info(
                f"Updated permission on {resource_type.value}:{resource_id} "
                f"for {subject_type.value}:{subject_id} from {existing_entry.permission} to {permission.value}"
            )

    async def clear_acl_permission(
        self,
        subject_type: SubjectType,
        subject_id: str,
        resource_type: ResourceType,
        resource_id: str,
    ) -> int:
        async with self.session() as session:
            # Build the delete query with the provided filters
            query = delete(SQLAAccessControlEntry)

            # Handle subject filtering based on SubjectType
            if subject_type == SubjectType.USER:
                query = query.where(SQLAAccessControlEntry.user_id == subject_id)
            elif subject_type == SubjectType.ORGANIZATION:
                query = query.where(SQLAAccessControlEntry.organization_id == subject_id)
            elif subject_type == SubjectType.PUBLIC:
                query = query.where(SQLAAccessControlEntry.is_public)
            else:
                raise ValueError(f"Unsupported subject type: {subject_type}")

            # Handle resource filtering based on ResourceType
            if resource_type == ResourceType.FRAME_GRID:
                query = query.where(SQLAAccessControlEntry.fg_id == resource_id)
            elif resource_type == ResourceType.VIEW:
                query = query.where(SQLAAccessControlEntry.view_id == resource_id)
            else:
                raise ValueError(f"Unsupported resource type: {resource_type}")

            result = await session.execute(query)
            count = result.rowcount or 0

            if count > 0:
                logger.info(
                    f"Cleared {count} ACL permissions with filters: "
                    f"subject_type={subject_type}, subject_id={subject_id}, "
                    f"resource_type={resource_type}, resource_id={resource_id}"
                )
            else:
                logger.info("No ACL permissions matched the provided filters")

            return count

    ###########
    # Locking #
    ###########

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
