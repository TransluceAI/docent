from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import anyio
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import docent_core._db_service.schemas._all_tables as tables  # Import all tables to ensure SQLAlchemy checks their existence
from docent._log_util import get_logger
from docent_core._env_util import ENV

logger = get_logger(__name__)


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
        pool_size=75,
    )


class DocentDB:
    """PostgreSQL database service for Docent."""

    # Singleton instance and async lock for thread‑safe initialization
    _instance: "DocentDB | None" = None
    _lock: anyio.Lock = anyio.Lock()

    def __init__(
        self,
        engine: AsyncEngine,
        Session: async_sessionmaker[AsyncSession],
    ):
        self.engine = engine
        self._Session = Session

    @asynccontextmanager
    async def _session_scope(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> AsyncIterator[AsyncSession]:
        session = session_factory()
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            logger.error("Rolled back database transaction")
            raise
        finally:
            with anyio.CancelScope(shield=True):
                await session.close()

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

            engine_kwargs = dict(
                pool_size=25,
                max_overflow=25,
                pool_timeout=30,
                pool_recycle=1800,  # Recycle connections after 30 minutes
                pool_pre_ping=True,  # Check connection validity before use
            )

            # Initialize engine with connection pooling
            engine = create_async_engine(connection_url, **engine_kwargs)

            # Create session factory
            Session = async_sessionmaker(
                bind=engine,
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

    async def _get_test_session(self) -> AsyncSession:
        logger.warning("Using test session. This is not recommended for production.")
        return self._Session()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide a transactional scope around a series of operations."""
        # I think we don't need automatic recovery of failed sessions, since the codepath
        # has already errored out at that point.

        async with self._session_scope(self._Session) as session:
            try:
                yield session
                # If already in the middle of a commit, see it through
                with anyio.CancelScope(shield=True):
                    await session.commit()
            finally:
                with anyio.CancelScope(shield=True):
                    await session.close()

    @asynccontextmanager
    async def dql_session(self, collection_id: str) -> AsyncIterator[AsyncSession]:
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
