"""
Authentication guards for protecting API endpoints.

This module provides FastAPI dependency functions for requiring user authentication
in API endpoints. Supports both session-based auth (web UI) and API key auth (SDK).
"""

from fastapi import HTTPException, Request

from docent._db_service.service import DBService
from docent.data_models.user import User


async def validate_api_key(api_key: str) -> User | None:
    """
    Validate an API key and return the associated user.

    Currently uses the user's email as the API key for simplicity.

    Args:
        api_key: The API key to validate (user email)

    Returns:
        User object if valid, None otherwise
    """
    try:
        db = await DBService.init()
        user = await db.get_user_by_email(api_key)
        return user
    except Exception:
        # If any error occurs during validation, treat as invalid
        return None


async def require_authenticated_user(request: Request) -> User:
    """
    FastAPI dependency that requires a valid authenticated user.

    Supports two authentication methods:
    1. Session-based auth (populated by SessionAuthMiddleware)
    2. API key auth via Authorization: Bearer <email> header

    This should be used as a dependency in endpoints that require authentication:

    ```python
    from fastapi import Depends

    @app.get("/protected")
    def protected_endpoint(user: User = Depends(require_authenticated_user)):
        return {"user_id": user.id}
    ```

    Args:
        request: The FastAPI request object

    Returns:
        The authenticated User object

    Raises:
        HTTPException: 401 if no valid session/API key is found
    """
    # Method 1: Check for session-based authentication (from middleware)
    if hasattr(request.state, "user") and request.state.user is not None:
        return request.state.user

    # Method 2: Check for API key authentication
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header[7:]  # Remove "Bearer " prefix
        user = await validate_api_key(api_key)
        if user:
            return user

    # No valid authentication found
    raise HTTPException(
        status_code=401, detail="Authentication required. Please log in or provide a valid API key."
    )


async def get_current_user_optional(request: Request) -> User | None:
    """
    FastAPI dependency that returns the current user if authenticated, None otherwise.

    Checks both session and API key authentication methods.
    This is useful for endpoints that have different behavior for authenticated vs
    unauthenticated users, but don't strictly require authentication.

    Args:
        request: The FastAPI request object

    Returns:
        The authenticated User object if available, None otherwise
    """
    try:
        return await require_authenticated_user(request)
    except HTTPException:
        return None
