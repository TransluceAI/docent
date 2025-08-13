from fastapi import Depends, HTTPException, Request

from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.server.dependencies.database import get_mono_svc
from docent_core.docent.services.monoservice import MonoService


async def _get_user_from_request(request: Request, mono_svc: MonoService):
    # Method 1: Check for session-based authentication (from middleware)
    if hasattr(request.state, "user") and request.state.user is not None:
        return request.state.user

    # Method 2: Check for API key authentication
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header[7:]  # Remove "Bearer " prefix
        user = await mono_svc.get_user_by_api_key(api_key)
        if user:
            return user

    return None


async def get_authenticated_user(request: Request, db: MonoService = Depends(get_mono_svc)) -> User:
    """Get the authenticated user from the request.
    Requires that the user is NOT anonymous."""

    user = await _get_user_from_request(request, db)
    if user is None or user.is_anonymous:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return user


async def get_user_anonymous_ok(
    request: Request, mono_svc: MonoService = Depends(get_mono_svc)
) -> User:
    """Get the user from the request.
    It's fine if the user is anonymous.
    """

    user = await _get_user_from_request(request, mono_svc)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return user


async def get_default_view_ctx(
    collection_id: str,
    mono_svc: MonoService = Depends(get_mono_svc),
    user: User = Depends(get_user_anonymous_ok),
):
    return await mono_svc.get_default_view_ctx(collection_id, user)
