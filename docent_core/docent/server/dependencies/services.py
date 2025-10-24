from typing import AsyncContextManager, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.server.dependencies.database import (
    get_mono_svc,
    get_session,
    get_session_cm_factory,
)
from docent_core.docent.server.dependencies.user import get_user_anonymous_ok
from docent_core.docent.services.charts import ChartsService
from docent_core.docent.services.chat import ChatService
from docent_core.docent.services.job import JobService
from docent_core.docent.services.label import LabelService
from docent_core.docent.services.llms import LLMService
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.onboarding import OnboardingService
from docent_core.docent.services.refinement import RefinementService
from docent_core.docent.services.rubric import RubricService
from docent_core.docent.services.telemetry import TelemetryService
from docent_core.docent.services.telemetry_accumulation import TelemetryAccumulationService
from docent_core.docent.services.usage import UsageService


def get_usage_svc(
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> UsageService:
    return UsageService(session_cm_factory)


def get_llm_svc(
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
    user: User = Depends(get_user_anonymous_ok),
    usage_service: UsageService = Depends(get_usage_svc),
) -> LLMService:
    return LLMService(session_cm_factory, user, usage_service)


def get_rubric_service(
    mono_svc: MonoService = Depends(get_mono_svc),
    session: AsyncSession = Depends(get_session),
    llm_svc: LLMService = Depends(get_llm_svc),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> RubricService:
    return RubricService(session, session_cm_factory, mono_svc, llm_svc)


def get_refinement_service(
    mono_svc: MonoService = Depends(get_mono_svc),
    rubric_svc: RubricService = Depends(get_rubric_service),
    llm_svc: LLMService = Depends(get_llm_svc),
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> RefinementService:
    return RefinementService(session, session_cm_factory, mono_svc, rubric_svc, llm_svc)


def get_label_service(
    mono_svc: MonoService = Depends(get_mono_svc),
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> LabelService:
    return LabelService(session, session_cm_factory, mono_svc)


def get_chat_service(
    mono_svc: MonoService = Depends(get_mono_svc),
    rubric_svc: RubricService = Depends(get_rubric_service),
    label_svc: LabelService = Depends(get_label_service),
    llm_svc: LLMService = Depends(get_llm_svc),
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> ChatService:
    return ChatService(session, session_cm_factory, mono_svc, rubric_svc, label_svc, llm_svc)


def get_job_service(
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> JobService:
    return JobService(session, session_cm_factory)


def get_chart_service(session: AsyncSession = Depends(get_session)) -> ChartsService:
    return ChartsService(session)


def get_onboarding_service(
    mono_svc: MonoService = Depends(get_mono_svc),
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> OnboardingService:
    return OnboardingService(session, session_cm_factory, mono_svc)


def get_telemetry_accumulation_service(
    session: AsyncSession = Depends(get_session),
) -> TelemetryAccumulationService:
    return TelemetryAccumulationService(session)


def get_telemetry_service(
    session: AsyncSession = Depends(get_session),
    mono_svc: MonoService = Depends(get_mono_svc),
) -> TelemetryService:
    return TelemetryService(session, mono_svc)
