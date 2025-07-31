"""
Session management utilities for user authentication.

This module contains functions for creating, managing, and validating user sessions.
"""

from typing import Literal

from fastapi import Response

from docent_core._db_service.service import MonoService
from docent_core._env_util import get_deployment_id

if get_deployment_id():
    # Staging or production
    cookie_secure = True
    cookie_domain = None  # Auto-detect from request hostname
    cookie_samesite: Literal["lax", "strict", "none"] = "none"
else:
    # Local deployment
    cookie_secure = False
    cookie_domain = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"


async def create_user_session(user_id: str, response: Response, mono_svc: MonoService) -> str:
    """
    Create a new session for a user and set the session cookie.

    This is a shared helper function used by both signup and login endpoints
    to ensure consistent session creation and cookie handling.

    Args:
        user_id: The user ID to create a session for
        response: FastAPI Response object to set cookies
        mono_svc: MonoService instance for database operations

    Returns:
        The created session ID
    """
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


async def invalidate_user_session(
    session_id: str, response: Response, mono_svc: MonoService
) -> None:
    """
    Invalidate a user session and clear the session cookie.

    Args:
        session_id: The session ID to invalidate
        response: FastAPI Response object to clear cookies
        mono_svc: MonoService instance for database operations
    """
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
