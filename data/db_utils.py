"""
Database utilities for the data registry.

Provides shared database connection and query functionality.
"""

import os
from contextlib import asynccontextmanager
from typing import Any, Dict

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from data.ingest import TEST_USER_EMAIL

# Load environment variables
load_dotenv()


def get_db_connection_params() -> Dict[str, Any]:
    """Get database connection parameters from environment."""
    return {
        "host": os.getenv("DOCENT_PG_HOST"),
        "port": int(os.getenv("DOCENT_PG_PORT", "5432")),
        "database": os.getenv("DOCENT_PG_DATABASE"),
        "user": os.getenv("DOCENT_PG_USER"),
        "password": os.getenv("DOCENT_PG_PASSWORD"),
    }


def create_database_url(params: Dict[str, Any] | None = None) -> str:
    """Create database URL from connection parameters."""
    if params is None:
        params = get_db_connection_params()

    return f"postgresql+asyncpg://{params['user']}:{params['password']}@{params['host']}:{params['port']}/{params['database']}"


def create_database_engine(params: Dict[str, Any] | None = None) -> AsyncEngine:
    """Create async database engine."""
    database_url = create_database_url(params)
    return create_async_engine(database_url)


@asynccontextmanager
async def get_db_connection():
    """Context manager for database connections."""
    engine = create_database_engine()
    try:
        async with engine.begin() as conn:
            yield conn
    finally:
        await engine.dispose()


async def get_current_alembic_revision() -> str:
    """Get the current Alembic revision from the database."""
    async with get_db_connection() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.fetchone()
        if row:
            return row[0]
        else:
            raise ValueError("No Alembic version found in database")


async def get_collection_info(collection_id: str) -> Dict[str, Any]:
    """Get collection information from the database."""
    async with get_db_connection() as conn:
        # Get collection info
        result = await conn.execute(
            text("SELECT id, name, created_by FROM collections WHERE id = :collection_id"),
            {"collection_id": collection_id},
        )
        collection_row = result.fetchone()

        if not collection_row:
            raise ValueError(f"Collection {collection_id} not found")

        # Count related records
        agent_runs_result = await conn.execute(
            text("SELECT COUNT(*) FROM agent_runs WHERE collection_id = :collection_id"),
            {"collection_id": collection_id},
        )
        agent_runs_count = agent_runs_result.scalar()

        return {
            "id": collection_row[0],
            "name": collection_row[1],
            "created_by": collection_row[2],
            "agent_runs_count": agent_runs_count,
        }


async def get_default_user_id() -> str:
    """Get or create the default test user and return their ID."""
    async with get_db_connection() as conn:
        # Try to find existing user
        result = await conn.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": TEST_USER_EMAIL}
        )
        user_row = result.fetchone()

        if user_row:
            return user_row[0]

    raise ValueError(f"User {TEST_USER_EMAIL} not found")
