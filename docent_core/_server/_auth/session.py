"""
Session management utilities for user authentication.

This module contains functions for creating, managing, and validating user sessions.
"""

from typing import Literal

from fastapi import Response

from docent._log_util.logger import get_logger
from docent_core._env_util import ENV, get_deployment_id
from docent_core.docent.services.monoservice import MonoService

COOKIE_KEY = "docent_session"

logger = get_logger(__name__)

if deployment_id := get_deployment_id():
    # Deployed
    cookie_secure = True
    cookie_samesite: Literal["lax", "strict", "none"] = "none"
    if not (cookie_domain := ENV.get("COOKIE_DOMAIN")):
        cookie_domain = None
else:
    # Local deployment
    cookie_secure = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain = None

logger.info(
    f"Cookie settings: secure={cookie_secure}, samesite={cookie_samesite}, domain={cookie_domain}"
)


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
        key=COOKIE_KEY,
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
        key=COOKIE_KEY,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        domain=cookie_domain,
    )
