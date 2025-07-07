"""
Session management utilities for user authentication.

This module contains functions for creating, managing, and validating user sessions.
"""

from typing import Literal

from fastapi import Response

from docent_core._db_service.service import MonoService
from docent_core._env_util import ENV

ENVIRONMENT = ENV.get("ENVIRONMENT")
if ENVIRONMENT is None or ENVIRONMENT == "":
    raise ValueError(
        "Must set ENVIRONMENT environment variable. Look at .env.template for an example."
    )

if ENVIRONMENT == "local":
    cookie_secure = False
    cookie_domain = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
elif ENVIRONMENT == "dev":
    cookie_secure = True
    cookie_domain = "dev.transluce.org"
    cookie_samesite: Literal["lax", "strict", "none"] = "none"
elif ENVIRONMENT == "prod":
    cookie_secure = True
    cookie_domain = "transluce.org"
    cookie_samesite: Literal["lax", "strict", "none"] = "none"
else:
    raise ValueError(f"Invalid environment: {ENVIRONMENT}")


async def create_user_session(user_id: str, response: Response) -> str:
    """
    Create a new session for a user and set the session cookie.

    This is a shared helper function used by both signup and login endpoints
    to ensure consistent session creation and cookie handling.

    Args:
        user_id: The user ID to create a session for
        response: FastAPI Response object to set cookies

    Returns:
        The created session ID
    """
    # Get database service instance
    mono_svc = await MonoService.init()

    # Create a new session in the database
    session_id = await mono_svc.create_session(user_id)

    # Set the session cookie with consistent settings
    response.set_cookie(
        key="docent_session_id",
        value=session_id,
        max_age=30 * 24 * 60 * 60,  # 30d
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        domain=cookie_domain,
    )

    return session_id


async def invalidate_user_session(session_id: str, response: Response) -> None:
    """
    Invalidate a user session and clear the session cookie.

    Args:
        session_id: The session ID to invalidate
        response: FastAPI Response object to clear cookies
    """
    # Get database service instance
    mono_svc = await MonoService.init()

    # Invalidate the session in the database
    await mono_svc.invalidate_session(session_id)

    # Clear the session cookie
    response.delete_cookie(
        key="docent_session_id",
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        domain=cookie_domain,
    )
