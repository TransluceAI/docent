from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, TypeVar, overload

import anyio
from sqlalchemy import URL, CursorResult, Executable, Result, UpdateBase, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql.selectable import TypedReturnsRows

import docent_core._db_service.schemas._all_tables as tables  # Import all tables to ensure SQLAlchemy checks their existence
from docent._log_util import get_logger
from docent_core._env_util import ENV

logger = get_logger(__name__)

DEFAULT_POOL_SIZE = 200
DEFAULT_MAX_OVERFLOW = 50


@dataclass
class PGParams:
    host: str
    port: str
    user: str
    password: str
    database: str


def get_pg_params() -> PGParams:
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
        raise ValueError("Database password missing. Please ensure DOCENT_PG_PASSWORD is set.")
    if not pg_database:
        pg_database = "docent"
        logger.info("No database name provided; using `docent` as default")

    return PGParams(
        host=pg_host, port=pg_port, user=pg_user, password=pg_password, database=pg_database
    )


def get_sync_engine():
    """Only used for database migrations, since alembic doesn't have great async support"""
    p = get_pg_params()

    return create_engine(
        URL.create(
            drivername="postgresql",
            username=p.user,
            password=p.password,
            host=p.host,
            port=int(p.port),
            database=p.database,
        ),
        pool_size=int(ENV.get("DOCENT_PG_POOL_SIZE", DEFAULT_POOL_SIZE)),
        max_overflow=int(ENV.get("DOCENT_PG_MAX_OVERFLOW", DEFAULT_MAX_OVERFLOW)),
    )


_T = TypeVar("_T", bound=Any)


class ShieldedAsyncSession(AsyncSession):
    """I believe there is an outstanding bug in SQLAlchemy / asyncpg,
    and this is a hack around it.

    I'm not confident that this solution covers all edge cases or codepaths.
    All I know is that if you don't shield these basic calls,
    you can get connection leaks when they're cancelled.

    The execute overrides are necessary to ensure correct type checking.
    They mirror the implementation in sqlalchemy.ext.asyncio.session.AsyncSession.

    Also, it's not ideal that cancelled calls will continue blocking
    until they complete.

    TODO(mengk): investigate further.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

    @overload
    async def execute(
        self, statement: TypedReturnsRows[_T], *args: Any, **kwargs: Any
    ) -> Result[_T]: ...

    @overload
    async def execute(
        self, statement: UpdateBase, *args: Any, **kwargs: Any
    ) -> CursorResult[Any]: ...

    @overload
    async def execute(self, statement: Executable, *args: Any, **kwargs: Any) -> Result[Any]: ...

    async def execute(self, statement: Executable, *args: Any, **kwargs: Any):
        with anyio.CancelScope(shield=True):
            return await super().execute(statement, *args, **kwargs)

    async def flush(self, *args: Any, **kwargs: Any):  # type: ignore
        with anyio.CancelScope(shield=True):
            return await super().flush(*args, **kwargs)

    async def commit(self, *args: Any, **kwargs: Any):  # type: ignore
        with anyio.CancelScope(shield=True):
            return await super().commit(*args, **kwargs)

    async def rollback(self, *args: Any, **kwargs: Any):  # type: ignore
        with anyio.CancelScope(shield=True):
            return await super().rollback(*args, **kwargs)

    async def close(self, *args: Any, **kwargs: Any):  # type: ignore
        with anyio.CancelScope(shield=True):
            return await super().close(*args, **kwargs)


class DocentDB:
    """PostgreSQL database service for Docent."""

    # Singleton instance and async lock for thread‑safe initialization
    _instance: "DocentDB | None" = None
    _lock: anyio.Lock = anyio.Lock()

    def __init__(
        self,
        engine: AsyncEngine,
        Session: async_sessionmaker[ShieldedAsyncSession],
    ):
        self.engine = engine
        self._Session = Session

    @asynccontextmanager
    async def _session_scope(
        self,
        session_factory: async_sessionmaker[ShieldedAsyncSession],
    ) -> AsyncIterator[ShieldedAsyncSession]:
        session = session_factory()
        try:
            yield session
            await session.commit()
        # These exceptions are processed _after_ code in the body.
        # Therefore, if an exception caused a connection to leak in the body,
        #   we may not be able to close or roll it back here. We need to avoid that.
        except Exception:
            try:
                await session.rollback()
                logger.info("Rolled back database transaction")
            except Exception as rb_err:
                logger.error("Failed to rollback database transaction: %r", rb_err)
            raise
        finally:
            try:
                await session.close()
            except Exception as cl_err:
                logger.error("Failed to close database session: %r", cl_err)

    @classmethod
    async def init(cls):
        """Get or create a singleton instance of ``DocentDB``.

        Uses an :py:class:`anyio.Lock` to guard the first‑time creation so that
        concurrent callers do not race to create multiple instances.
        """

        async with cls._lock:
            if cls._instance is not None:
                return cls._instance

            p = get_pg_params()

            # Check that the target database is not 'postgres'
            if (target_database := p.database) == "postgres":
                raise ValueError("Cannot use 'postgres' as a target database")

            # First create a connection to the default 'postgres' database
            url = URL.create(
                drivername="postgresql+asyncpg",
                username=p.user,
                password=p.password,
                host=p.host,
                port=int(p.port),
                database="postgres",  # Connect to default postgres database first
            )

            # Create the target database if it doesn't exist
            await cls._ensure_database_exists(url, target_database)

            # Now create the connection string for the target database
            connection_url = url.set(database=target_database)
            logger.info(f"Using database connection: {connection_url}")

            # Specify size of persistent (+ overflow) connection pools
            pool_size = int(ENV.get("DOCENT_PG_POOL_SIZE", DEFAULT_POOL_SIZE))
            max_overflow = int(ENV.get("DOCENT_PG_MAX_OVERFLOW", DEFAULT_MAX_OVERFLOW))

            engine_kwargs = dict(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=30,
                pool_recycle=1800,  # Recycle connections after 30 minutes
                pool_pre_ping=True,  # Check connection validity before use
            )

            # Initialize engine with connection pooling
            engine = create_async_engine(connection_url, **engine_kwargs)

            # Create session factory
            Session = async_sessionmaker(
                bind=engine,
                class_=ShieldedAsyncSession,
                autoflush=False,
                expire_on_commit=False,
            )

            # Initialize database tables if they don't exist
            # await cls._setup_target_database(engine)
            # TODO(mengk): please create tables manually.

            # Cache and return the singleton instance
            cls._instance = cls(
                engine,
                Session,
            )
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
    async def _setup_target_database(engine: AsyncEngine) -> None:
        """Create all tables if they don't exist."""
        async with engine.begin() as conn:
            # Enable pgvector extension
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # Create tables
            await conn.run_sync(tables.base.SQLABase.metadata.create_all)
        logger.info("pgvector and tables initialized successfully")

    async def drop_all_tables(self) -> None:
        """
        Drop all tables in the database.
        WARNING: This will permanently delete all data.
        """
        # Safety check to prevent dropping tables from the postgres system database
        if self.engine.url.database == "postgres":
            raise ValueError("Refusing to drop tables from the 'postgres' system database")

        async with self.engine.begin() as conn:
            await conn.run_sync(tables.base.SQLABase.metadata.drop_all)

    async def _get_test_session(self) -> ShieldedAsyncSession:
        logger.warning("Using test session. This is not recommended for production.")
        return self._Session()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ShieldedAsyncSession]:
        """Provide a transactional scope around a series of operations."""
        async with self._session_scope(self._Session) as session:
            yield session

    @asynccontextmanager
    async def dql_session(self, collection_id: str) -> AsyncIterator[ShieldedAsyncSession]:
        """Return a session with the read-only DQL role assumed and collection configured."""
        from docent_core.docent.db.dql import DQL_COLLECTION_SETTING_KEY

        async with self._session_scope(self._Session) as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            # SET LOCAL ROLE automatically resets when the transaction ends
            await session.execute(text("SET LOCAL ROLE docent_dql_reader"))
            await session.execute(
                text(f"SELECT set_config('{DQL_COLLECTION_SETTING_KEY}', :collection_id, true)"),
                {"collection_id": collection_id},
            )
            yield session
