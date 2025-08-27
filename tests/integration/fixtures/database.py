"""Database fixtures for integration tests."""

from typing import AsyncGenerator

import pytest_asyncio
import redis.asyncio as redis
from arq import ArqRedis
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.asyncio.engine import AsyncConnection

from docent_core._db_service.db import DocentDB
from docent_core._server.api import asgi_app
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import SQLABase
from docent_core.docent.server.dependencies.database import get_db, get_mono_svc
from docent_core.docent.services.charts import ChartsService
from docent_core.docent.services.monoservice import MonoService

TEST_DATABASE_URL = URL.create(
    drivername="postgresql+asyncpg",
    username="docent_user",
    password="docent_password",
    host="localhost",
    port=5432,
    database="_pytest_docent_test",
)

TEST_REDIS_URL = "redis://localhost:6379/1"  # Use database 1 for tests


# Function scope for this fixture may slow down tests, but avoids tricky asyncio problems
@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        TEST_DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True, echo=False
    )
    try:
        async with engine.begin() as conn:
            # Clean slate: drop all tables first, then create them
            # This ensures tests start clean even if previous run was interrupted
            await conn.run_sync(SQLABase.metadata.drop_all)
            await conn.run_sync(SQLABase.metadata.create_all)
        yield engine
    finally:
        try:
            await engine.dispose()
        except Exception:
            pass


@pytest_asyncio.fixture(scope="function")
async def db_connection(db_engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    async with db_engine.connect() as connection:
        yield connection


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def db_service(db_engine: AsyncEngine) -> AsyncGenerator[DocentDB, None]:
    session_maker = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    yield DocentDB(db_engine, session_maker)


@pytest_asyncio.fixture(scope="function")
async def mono_service(db_service: DocentDB) -> AsyncGenerator[MonoService, None]:
    """
    Test-scoped fixture that provides MonoService with real database.
    """
    service = MonoService(db_service)
    yield service


@pytest_asyncio.fixture(scope="function")
async def charts_service(db_session: AsyncSession) -> AsyncGenerator[ChartsService, None]:
    """
    Fixture that creates a test charts service and returns it.
    """
    service = ChartsService(db_session)
    yield service


@pytest_asyncio.fixture(scope="function")
async def test_collection_id(
    mono_service: MonoService, test_user: User
) -> AsyncGenerator[str, None]:
    """
    Fixture that creates a test collection and returns its ID.
    Cleans up the collection after the test.
    """
    collection_id = await mono_service.create_collection(
        name="pytest_integration_collection",
        description="Test collection for integration tests",
        user=test_user,
    )
    yield collection_id


@pytest_asyncio.fixture(scope="function")
async def test_user(mono_service: MonoService) -> AsyncGenerator[User, None]:
    """
    Fixture that creates a test user and returns the user ID.
    """
    user = await mono_service.create_user(
        email="pytest_integration@example.com", password="test_password_123"
    )
    yield user


@pytest_asyncio.fixture(scope="function")
async def redis_client() -> AsyncGenerator[ArqRedis, None]:
    """
    Test-scoped fixture that provides Redis client with test database.
    """
    client = ArqRedis(
        connection_pool=redis.ConnectionPool.from_url(TEST_REDIS_URL, decode_responses=True)  # type: ignore
    )
    try:
        # Clear test database before test
        await client.flushdb()  # type: ignore
        yield client
    finally:
        try:
            # Clear test database after test
            await client.flushdb()  # type: ignore
            await client.aclose()
        except Exception:
            pass


@pytest_asyncio.fixture(scope="function", autouse=True)
async def override_db(
    db_service: DocentDB, mono_service: MonoService, redis_client: ArqRedis
) -> AsyncGenerator[None, None]:
    original_overrides = asgi_app.dependency_overrides.copy()

    # Import here to avoid circular imports
    from docent_core._server._broker import redis_client as redis_client_module

    # Capture the original client without triggering connection creation
    original_redis = getattr(redis_client_module, "_redis_client", None)

    try:

        async def get_db_override():
            return db_service

        async def get_mono_svc_override():
            return mono_service

        asgi_app.dependency_overrides[get_db] = get_db_override
        asgi_app.dependency_overrides[get_mono_svc] = get_mono_svc_override

        # Override the global Redis client
        redis_client_module._redis_client = redis_client  # type: ignore

        yield
    finally:
        asgi_app.dependency_overrides.clear()
        asgi_app.dependency_overrides.update(original_overrides)

        # Restore original Redis client
        redis_client_module._redis_client = original_redis  # type: ignore
