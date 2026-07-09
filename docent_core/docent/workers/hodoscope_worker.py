from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from docent._log_util import get_logger
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAHodoscopeAnalysis, SQLAJob
from docent_core.docent.services.hodoscope import HodoscopeAnalysisConfig
from docent_core.docent.services.hodoscope_pipeline import (
    build_hodoscope_outputs,
    embed_hodoscope_summaries,
    extract_hodoscope_actions,
    summarize_hodoscope_actions,
)
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _load_analysis(
    mono_svc: MonoService,
    analysis_id: str,
) -> SQLAHodoscopeAnalysis:
    async with mono_svc.db.session() as session:
        result = await session.execute(
            select(SQLAHodoscopeAnalysis).where(SQLAHodoscopeAnalysis.id == analysis_id)
        )
        sq_analysis = result.scalar_one_or_none()
        if sq_analysis is None:
            raise ValueError(f"Hodoscope analysis {analysis_id} not found")
        return sq_analysis


async def _set_analysis_state(
    mono_svc: MonoService,
    *,
    analysis_id: str,
    job: SQLAJob,
    stage: str,
    progress: int,
    status: str = "running",
    error: str | None = None,
    artifact: dict[str, Any] | None = None,
    projection: dict[str, Any] | None = None,
    config_updates: dict[str, Any] | None = None,
    completed: bool = False,
) -> None:
    job_json = dict(job.job_json)
    job_json.update({"stage": stage, "progress": progress})
    await mono_svc.set_job_json(job.id, job_json)
    job.job_json = job_json

    async with mono_svc.db.session() as session:
        result = await session.execute(
            select(SQLAHodoscopeAnalysis).where(SQLAHodoscopeAnalysis.id == analysis_id)
        )
        sq_analysis = result.scalar_one()
        config_json = dict(sq_analysis.config_json)
        if config_updates:
            config_json.update(config_updates)
        config_json["_job_state"] = {"stage": stage, "progress": progress}

        sq_analysis.status = status
        sq_analysis.updated_at = _now()
        sq_analysis.config_json = config_json
        if completed:
            sq_analysis.completed_at = _now()
        if error is not None:
            sq_analysis.error = error
        if artifact is not None:
            sq_analysis.artifact_json = artifact
        if projection is not None:
            sq_analysis.projection_json = projection


async def hodoscope_analysis_job(ctx: ViewContext, job: SQLAJob) -> None:
    mono_svc = await MonoService.init()
    analysis_id = str(job.job_json["analysis_id"])

    try:
        await _set_analysis_state(
            mono_svc,
            analysis_id=analysis_id,
            job=job,
            stage="loading_runs",
            progress=5,
        )
        sq_analysis = await _load_analysis(mono_svc, analysis_id)
        config = HodoscopeAnalysisConfig.model_validate(
            {k: v for k, v in sq_analysis.config_json.items() if k != "_job_state"}
        )

        agent_run_ids = await mono_svc.get_agent_run_ids(ctx)
        if config.limit and len(agent_run_ids) > config.limit:
            import random

            rng = random.Random(config.seed)
            agent_run_ids = list(agent_run_ids)
            rng.shuffle(agent_run_ids)
            agent_run_ids = agent_run_ids[: config.limit]

        agent_runs = await mono_svc.get_agent_runs(ctx, agent_run_ids=agent_run_ids)

        await _set_analysis_state(
            mono_svc,
            analysis_id=analysis_id,
            job=job,
            stage="extracting_actions",
            progress=15,
        )
        actions, group_by = extract_hodoscope_actions(agent_runs, config.group_by)
        config = config.model_copy(update={"group_by": group_by})

        await _set_analysis_state(
            mono_svc,
            analysis_id=analysis_id,
            job=job,
            stage="summarizing",
            progress=30,
            config_updates={"group_by": group_by},
        )
        summaries = await summarize_hodoscope_actions(actions)

        async def embedding_progress(progress: int) -> None:
            await _set_analysis_state(
                mono_svc,
                analysis_id=analysis_id,
                job=job,
                stage="embedding",
                progress=40 + int(progress * 0.4),
            )

        await _set_analysis_state(
            mono_svc,
            analysis_id=analysis_id,
            job=job,
            stage="embedding",
            progress=40,
        )
        summaries = await embed_hodoscope_summaries(
            summaries,
            embedding_progress,
            model_name=config.embedding_model,
            dimensions=config.embedding_dimensionality,
        )

        await _set_analysis_state(
            mono_svc,
            analysis_id=analysis_id,
            job=job,
            stage="projecting",
            progress=85,
        )
        artifact, projection = build_hodoscope_outputs(
            summaries,
            config,
            group_by=group_by,
            source=f"docent:{ctx.collection_id}",
        )

        await _set_analysis_state(
            mono_svc,
            analysis_id=analysis_id,
            job=job,
            stage="complete",
            progress=100,
            status="complete",
            artifact=artifact,
            projection=projection,
            completed=True,
        )
    except Exception as exc:
        logger.error(f"Hodoscope analysis {analysis_id} failed: {exc}")
        await _set_analysis_state(
            mono_svc,
            analysis_id=analysis_id,
            job=job,
            stage="error",
            progress=0,
            status="error",
            error=str(exc),
            completed=True,
        )
        raise
