from fastapi import Depends, HTTPException, Request

from docent._db_service.schemas.auth_models import User
from docent._db_service.service import DBService
from docent._server._dependencies.database import get_db


async def _get_user_from_request(request: Request, db: DBService):
    # Method 1: Check for session-based authentication (from middleware)
    if hasattr(request.state, "user") and request.state.user is not None:
        return request.state.user

    # Method 2: Check for API key authentication
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header[7:]  # Remove "Bearer " prefix
        user = await db.get_user_by_email(api_key)
        if user:
            return user

    return None


async def get_authenticated_user(request: Request, db: DBService = Depends(get_db)) -> User:
    """Get the authenticated user from the request.
    Requires that the user is NOT anonymous."""

    user = await _get_user_from_request(request, db)
    if user is None or user.is_anonymous:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return user


async def get_user_anonymous_ok(request: Request, db: DBService = Depends(get_db)) -> User:
    """Get the user from the request.
    It's fine if the user is anonymous.
    """

    user = await _get_user_from_request(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return user


async def get_default_view_ctx(
    fg_id: str, db: DBService = Depends(get_db), user: User = Depends(get_user_anonymous_ok)
):
    return await db.get_default_view_ctx(fg_id, user)
