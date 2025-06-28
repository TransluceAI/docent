from fastapi import Depends, HTTPException

from docent._log_util import get_logger
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.auth_models import Permission, ResourceType, User
from docent_core._db_service.service import DBService
from docent_core._server._dependencies.database import get_db
from docent_core._server._dependencies.user import get_default_view_ctx, get_user_anonymous_ok

logger = get_logger(__name__)


def require_fg_permission(permission: Permission):
    async def _check_permission(
        fg_id: str,
        user: User = Depends(get_user_anonymous_ok),
        db: DBService = Depends(get_db),
    ) -> None:
        allowed = await db.has_permission(
            user=user,
            resource_type=ResourceType.FRAME_GRID,
            resource_id=fg_id,
            permission=permission,
        )
        if not allowed:
            logger.error(f"Permission denied for user {user.id} on framegrid {fg_id}")
            raise HTTPException(status_code=403, detail="Permission denied")

    return _check_permission


def require_view_permission(permission: Permission):
    async def _check_permission(
        ctx: ViewContext = Depends(get_default_view_ctx),
        user: User = Depends(get_user_anonymous_ok),
        db: DBService = Depends(get_db),
    ) -> None:
        allowed = await db.has_permission(
            user=user,
            resource_type=ResourceType.VIEW,
            resource_id=ctx.view_id,
            permission=permission,
        )
        # TODO(mengk): verify framegrid permissions too - users with framegrid ADMIN/WRITE
        # should automatically have access to views within that framegrid

        if not allowed:
            logger.error(f"Permission denied for user {user.id} on view {ctx.view_id}")
            raise HTTPException(status_code=403, detail="Permission denied")

    return _check_permission
