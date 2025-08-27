"""Client fixtures for integration tests."""

from typing import AsyncGenerator

import httpx
import pytest_asyncio
from httpx import ASGITransport

from docent_core._server.api import asgi_app
from docent_core.docent.db.schemas.auth_models import User


@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def authed_client(test_user: User) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/rest/login",
            json={"email": "pytest_integration@example.com", "password": "test_password_123"},
        )
        assert resp.status_code == 200
        yield client
