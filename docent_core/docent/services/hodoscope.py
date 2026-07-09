from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docent_core._env_util import ENV
from docent_core._llm_util.providers.openai import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
)
from docent_core._server._broker.redis_client import cancel_job, enqueue_job
from docent_core._worker.constants import WorkerFunction
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import (
    JobStatus,
    SQLAHodoscopeAnalysis,
    SQLAJob,
)

HodoscopeAnalysisStatus = Literal["pending", "running", "complete", "error", "canceled"]
HodoscopeProjectionMethod = Literal["pca", "tsne", "umap", "trimap", "pacmap"]

HODOSCOPE_EMBEDDING_MODEL = DEFAULT_EMBEDDING_MODEL
HODOSCOPE_EMBEDDING_DIM = DEFAULT_EMBEDDING_DIMENSIONS


def _env_value(name: str) -> str | None:
    value = ENV.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_int_or_none(*names: str) -> int | None:
    for name in names:
        raw_value = _env_value(name)
        if raw_value is None:
            continue
        if raw_value.lower() in {"none", "null", "auto"}:
            return None
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer, none, null, or auto") from exc
    return None


def get_hodoscope_embedding_model() -> str:
    return (
        _env_value("DOCENT_HODOSCOPE_EMBEDDING_MODEL")
        or _env_value("DOCENT_EMBEDDING_MODEL")
        or HODOSCOPE_EMBEDDING_MODEL
    )


def get_hodoscope_embedding_base_url() -> str | None:
    return _env_value("DOCENT_HODOSCOPE_EMBEDDING_BASE_URL")


def get_hodoscope_embedding_api_key() -> str | None:
    return _env_value("DOCENT_HODOSCOPE_EMBEDDING_API_KEY")


def get_hodoscope_embedding_dimensionality() -> int | None:
    configured = _env_int_or_none(
        "DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS",
        "DOCENT_HODOSCOPE_EMBEDDING_DIM",
        "DOCENT_EMBEDDING_DIMENSIONS",
        "DOCENT_EMBEDDING_DIM",
    )
    if configured is not None:
        return configured
    if any(
        _env_value(name) is not None
        for name in (
            "DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS",
            "DOCENT_HODOSCOPE_EMBEDDING_DIM",
            "DOCENT_EMBEDDING_DIMENSIONS",
            "DOCENT_EMBEDDING_DIM",
        )
    ):
        return None

    if get_hodoscope_embedding_model().startswith("text-embedding-3-"):
        return HODOSCOPE_EMBEDDING_DIM
    return None


class HodoscopeAnalysisConfig(BaseModel):
    name: str = "Hodoscope analysis"
    group_by: str | None = None
    limit: int = Field(default=500, ge=1, le=10_000)
    seed: int = 42
    projection_method: HodoscopeProjectionMethod = "tsne"
    summary_model: str = "docent-provider-preferences"
    embedding_model: str = Field(default_factory=get_hodoscope_embedding_model)
    embedding_dimensionality: int | None = Field(
        default_factory=get_hodoscope_embedding_dimensionality
    )


class HodoscopeAnalysisSummary(BaseModel):
    id: str
    collection_id: str
    job_id: str | None
    name: str
    status: HodoscopeAnalysisStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    config: dict[str, Any]
    error: str | None
    stage: str | None = None
    progress: int | None = None
    point_count: int = 0
    group_count: int = 0


class HodoscopeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _summary_from_sqla(sq_analysis: SQLAHodoscopeAnalysis) -> HodoscopeAnalysisSummary:
        projection = sq_analysis.projection_json or {}
        points_raw: object = projection.get("points", [])
        groups_raw: object = projection.get("groups", [])
        job_state_raw: object = sq_analysis.config_json.get("_job_state", {})
        job_state = cast(dict[str, Any], job_state_raw) if isinstance(job_state_raw, dict) else {}
        stage_raw: object = job_state.get("stage")
        progress_raw: object = job_state.get("progress")
        return HodoscopeAnalysisSummary(
            id=sq_analysis.id,
            collection_id=sq_analysis.collection_id,
            job_id=sq_analysis.job_id,
            name=sq_analysis.name,
            status=sq_analysis.status,  # type: ignore[arg-type]
            created_at=sq_analysis.created_at,
            updated_at=sq_analysis.updated_at,
            completed_at=sq_analysis.completed_at,
            config={k: v for k, v in sq_analysis.config_json.items() if k != "_job_state"},
            error=sq_analysis.error,
            stage=stage_raw if isinstance(stage_raw, str) else None,
            progress=progress_raw if isinstance(progress_raw, int) else None,
            point_count=len(cast(list[object], points_raw)) if isinstance(points_raw, list) else 0,
            group_count=len(cast(list[object], groups_raw)) if isinstance(groups_raw, list) else 0,
        )

    async def get_analysis(
        self, ctx: ViewContext, analysis_id: str
    ) -> SQLAHodoscopeAnalysis | None:
        result = await self.session.execute(
            select(SQLAHodoscopeAnalysis).where(
                SQLAHodoscopeAnalysis.collection_id == ctx.collection_id,
                SQLAHodoscopeAnalysis.id == analysis_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_analysis_summary(
        self, ctx: ViewContext, analysis_id: str
    ) -> HodoscopeAnalysisSummary | None:
        sq_analysis = await self.get_analysis(ctx, analysis_id)
        return self._summary_from_sqla(sq_analysis) if sq_analysis else None

    async def list_analyses(self, ctx: ViewContext) -> list[HodoscopeAnalysisSummary]:
        result = await self.session.execute(
            select(SQLAHodoscopeAnalysis)
            .where(SQLAHodoscopeAnalysis.collection_id == ctx.collection_id)
            .order_by(SQLAHodoscopeAnalysis.created_at.desc())
        )
        return [self._summary_from_sqla(sq_analysis) for sq_analysis in result.scalars().all()]

    async def get_active_analysis(self, ctx: ViewContext) -> SQLAHodoscopeAnalysis | None:
        result = await self.session.execute(
            select(SQLAHodoscopeAnalysis)
            .where(
                SQLAHodoscopeAnalysis.collection_id == ctx.collection_id,
                SQLAHodoscopeAnalysis.status.in_(["pending", "running"]),
            )
            .order_by(SQLAHodoscopeAnalysis.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def start_or_get_analysis(
        self, ctx: ViewContext, config: HodoscopeAnalysisConfig
    ) -> HodoscopeAnalysisSummary:
        sq_active = await self.get_active_analysis(ctx)
        if sq_active is not None:
            return self._summary_from_sqla(sq_active)

        analysis_id = str(uuid4())
        job_id = str(uuid4())
        now = self._now()
        config_json = config.model_dump()
        config_json["_job_state"] = {"stage": "pending", "progress": 0}
        sq_analysis = SQLAHodoscopeAnalysis(
            id=analysis_id,
            collection_id=ctx.collection_id,
            job_id=job_id,
            name=config.name,
            status="pending",
            created_at=now,
            updated_at=now,
            completed_at=None,
            config_json=config_json,
            artifact_json=None,
            projection_json=None,
            error=None,
        )
        sq_job = SQLAJob(
            id=job_id,
            type=WorkerFunction.HODOSCOPE_ANALYSIS.value,
            created_at=now,
            job_json={
                "collection_id": ctx.collection_id,
                "analysis_id": analysis_id,
                "stage": "pending",
                "progress": 0,
            },
            status=JobStatus.PENDING,
        )
        self.session.add(sq_job)
        await self.session.flush()
        self.session.add(sq_analysis)
        await self.session.commit()
        await enqueue_job(ctx, job_id)
        await self.session.refresh(sq_analysis)
        return self._summary_from_sqla(sq_analysis)

    async def get_projection(self, ctx: ViewContext, analysis_id: str) -> dict[str, Any] | None:
        sq_analysis = await self.get_analysis(ctx, analysis_id)
        return sq_analysis.projection_json if sq_analysis else None

    async def get_artifact(self, ctx: ViewContext, analysis_id: str) -> dict[str, Any] | None:
        sq_analysis = await self.get_analysis(ctx, analysis_id)
        return sq_analysis.artifact_json if sq_analysis else None

    async def cancel_analysis(
        self, ctx: ViewContext, analysis_id: str
    ) -> HodoscopeAnalysisSummary | None:
        sq_analysis = await self.get_analysis(ctx, analysis_id)
        if sq_analysis is None:
            return None

        if sq_analysis.status in {"pending", "running"}:
            sq_analysis.status = "canceled"
            sq_analysis.completed_at = self._now()
            sq_analysis.updated_at = self._now()
            sq_analysis.error = "Canceled by user"
            config_json = dict(sq_analysis.config_json)
            config_json["_job_state"] = {"stage": "canceled", "progress": 0}
            sq_analysis.config_json = config_json
            await self.session.commit()
            if sq_analysis.job_id:
                await cancel_job(sq_analysis.job_id)

        await self.session.refresh(sq_analysis)
        return self._summary_from_sqla(sq_analysis)
