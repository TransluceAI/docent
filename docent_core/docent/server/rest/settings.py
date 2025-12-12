from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from docent._log_util import get_logger
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.server.dependencies.analytics import use_posthog_user_context
from docent_core.docent.server.dependencies.database import get_mono_svc
from docent_core.docent.server.dependencies.services import get_usage_svc
from docent_core.docent.server.dependencies.user import get_authenticated_user
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.usage import (
    FREE_CAP_CENTS,
    RATE_LIMIT_WINDOW_SECONDS,
    UsageService,
)

logger = get_logger(__name__)


settings_router = APIRouter()


@settings_router.get("/usage/summary")
async def get_usage_summary(
    user: User = Depends(get_authenticated_user),
    usage_svc: UsageService = Depends(get_usage_svc),
):
    window_seconds = RATE_LIMIT_WINDOW_SECONDS
    total_cents, models = await usage_svc.get_free_usage_breakdown(user.id, window_seconds)

    if FREE_CAP_CENTS is None:
        free: dict[str, Any] = {
            "has_cap": False,
            "total_cents": total_cents,
            "models": models,
        }
    else:
        cap_cents = FREE_CAP_CENTS
        fraction_used = (total_cents / cap_cents) if cap_cents and cap_cents > 0 else 0.0
        free = {
            "has_cap": True,
            "total_cents": total_cents,
            "fraction_used": fraction_used,
            "models": models,
        }

    # BYOK usage
    keys = await usage_svc.get_byok_usage_by_key(user.id, RATE_LIMIT_WINDOW_SECONDS)
    byok = {"window_seconds": RATE_LIMIT_WINDOW_SECONDS, "keys": keys}

    return {
        "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
        "free": free,
        "byok": byok,
    }


class ModelApiKeyResponse(BaseModel):
    id: str
    provider: str
    masked_api_key: str


class UpsertModelApiKeyRequest(BaseModel):
    provider: str
    api_key: str


def _mask_api_key(key: str):
    if len(key) <= 8:
        return "••••••••"
    return key[:4] + "••••••••" + key[-4:]


@settings_router.get("/model-api-keys", response_model=list[ModelApiKeyResponse])
async def list_model_api_keys(
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
):
    """List all model API keys for the authenticated user."""
    model_api_keys = await mono_svc.get_model_api_keys(user.id)
    return [
        ModelApiKeyResponse(
            id=key.id,
            provider=key.provider,
            masked_api_key=_mask_api_key(key.api_key),
        )
        for key in model_api_keys
    ]


@settings_router.put("/model-api-keys", response_model=ModelApiKeyResponse)
async def upsert_model_api_key(
    request: UpsertModelApiKeyRequest,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Create or update a model API key for the authenticated user."""
    # Validate provider
    valid_providers = ["openai", "anthropic", "google", "openrouter"]
    if request.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {', '.join(valid_providers)}",
        )

    model_api_key = await mono_svc.upsert_model_api_key(user.id, request.provider, request.api_key)

    # Track with PostHog
    analytics.track_event(
        "model_api_key_saved",
        properties={
            "provider": model_api_key.provider,
        },
    )

    return ModelApiKeyResponse(
        id=model_api_key.id,
        provider=model_api_key.provider,
        masked_api_key=_mask_api_key(model_api_key.api_key),
    )


@settings_router.delete("/model-api-keys/{provider}")
async def delete_model_api_key(
    provider: str,
    user: User = Depends(get_authenticated_user),
    mono_svc: MonoService = Depends(get_mono_svc),
    analytics: AnalyticsClient = Depends(use_posthog_user_context),
):
    """Delete a model API key for the authenticated user and provider."""
    success = await mono_svc.delete_model_api_key(user.id, provider)
    if not success:
        raise HTTPException(status_code=404, detail="Model API key not found")
    # Track with PostHog
    analytics.track_event(
        "model_api_key_deleted",
        properties={
            "provider": provider,
        },
    )
    return {"message": "Model API key deleted successfully"}
