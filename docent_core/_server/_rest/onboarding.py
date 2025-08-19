from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from docent._log_util import get_logger
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.server.dependencies.services import get_onboarding_service
from docent_core.docent.server.dependencies.user import get_authenticated_user
from docent_core.services.onboarding import OnboardingService

logger = get_logger(__name__)

onboarding_router = APIRouter(dependencies=[Depends(get_authenticated_user)])


class MultiSelectData(BaseModel):
    selected: list[str] = []
    other: list[str] = []


class OnboardingData(BaseModel):
    institution: str | None = None
    task: str | None = None
    help_type: str | None = None
    frameworks: MultiSelectData | None = None
    providers: MultiSelectData | None = None
    discovery_source: str | None = None


@onboarding_router.post("/onboarding")
async def save_onboarding_data(
    data: OnboardingData,
    user: User = Depends(get_authenticated_user),
    onboarding_svc: OnboardingService = Depends(get_onboarding_service),
):
    """Save onboarding data for the authenticated user."""
    try:
        result = await onboarding_svc.save_user_profile(
            user_id=user.id,
            institution=data.institution,
            task=data.task,
            help_type=data.help_type,
            frameworks=data.frameworks.model_dump() if data.frameworks else None,
            providers=data.providers.model_dump() if data.providers else None,
            discovery_source=data.discovery_source,
        )

        logger.info(f"Saved onboarding data for user {user.id}")
        return {
            "success": True,
            "message": "Onboarding data saved successfully",
            "onboarding_id": result.id,
        }
    except Exception as e:
        logger.error(f"Failed to save onboarding data for user {user.id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save onboarding data")


@onboarding_router.get("/onboarding")
async def get_onboarding_data(
    user: User = Depends(get_authenticated_user),
    onboarding_svc: OnboardingService = Depends(get_onboarding_service),
):
    """Get onboarding data for the authenticated user."""
    try:
        result = await onboarding_svc.get_user_profile(user.id)

        if result is None:
            return {"success": True, "data": None, "message": "No onboarding data found"}

        return {
            "success": True,
            "data": {
                "institution": result.institution,
                "task": result.task,
                "help_type": result.help_type,
                "frameworks": result.frameworks,
                "providers": result.providers,
                "discovery_source": result.discovery_source,
                "created_at": result.created_at.isoformat() if result.created_at else None,
                "updated_at": result.updated_at.isoformat() if result.updated_at else None,
            },
        }
    except Exception as e:
        logger.error(f"Failed to get onboarding data for user {user.id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get onboarding data")
