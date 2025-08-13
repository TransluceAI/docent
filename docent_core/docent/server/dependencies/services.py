from typing import AsyncContextManager, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from docent_core.docent.server.dependencies.database import (
    get_mono_svc,
    get_session,
    get_session_cm_factory,
)
from docent_core.docent.services.charts import ChartsService
from docent_core.docent.services.diff import DiffService
from docent_core.docent.services.job import JobService
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService
from docent_core.services.refinement import RefinementService


def get_diff_service(
    mono_svc: MonoService = Depends(get_mono_svc),
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> DiffService:
    return DiffService(session, session_cm_factory, mono_svc)


def get_rubric_service(
    mono_svc: MonoService = Depends(get_mono_svc),
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> RubricService:
    return RubricService(session, session_cm_factory, mono_svc)


def get_refinement_service(
    mono_svc: MonoService = Depends(get_mono_svc),
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> RefinementService:
    return RefinementService(session, session_cm_factory, mono_svc)


def get_job_service(
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> JobService:
    return JobService(session, session_cm_factory)


def get_chart_service(
    session: AsyncSession = Depends(get_session),
) -> ChartsService:
    return ChartsService(session)
