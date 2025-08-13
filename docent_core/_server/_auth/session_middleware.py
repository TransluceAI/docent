"""
Session authentication middleware for validating user sessions.

This middleware validates the docent_session cookie on every request
and attaches user information to request.state for use in endpoints.
"""

from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from docent._log_util import get_logger
from docent_core._server._auth.session import COOKIE_KEY
from docent_core.docent.server.dependencies.database import get_mono_svc

logger = get_logger(__name__)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that validates user sessions and attaches user info to request state.

    For each request:
    1. Extracts the docent_session cookie
    2. Validates the session (active and not expired)
    3. Loads the associated user
    4. Attaches user and user_id to request.state

    If no valid session is found, request.state.user remains None.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]):
        # Initialize user state
        request.state.user = None
        request.state.user_id = None

        # Get the user from session_id
        if session_id := request.cookies.get(COOKIE_KEY):

            # For testing, we override get_mono_svc with a version that uses the test db
            mono_svc_factory = request.app.dependency_overrides.get(get_mono_svc, get_mono_svc)
            mono_svc = await mono_svc_factory()

            user = await mono_svc.get_user_by_session_id(session_id)

            if user:
                # Attach user information to request state
                request.state.user = user
                request.state.user_id = user.id
                logger.debug(
                    f"Authenticated user {user.id} ({user.email}) for {request.method} {request.url.path}"
                )
            else:
                logger.debug(
                    f"Invalid or expired session {session_id} for {request.method} {request.url.path}"
                )

        # Process request
        response = await call_next(request)
        return response
