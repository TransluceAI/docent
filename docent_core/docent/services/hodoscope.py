from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
HODOSCOPE_CONTEXT_EXCERPT_MAX_CHARS = 320
HODOSCOPE_MAX_LOADED_RUNS = 500

_HODOSCOPE_PROJECTION_TOP_LEVEL_FIELDS = (
    "version",
    "created_at",
    "group_by",
    "projection_method",
    "requested_projection_method",
    "groups",
)
_HODOSCOPE_PROJECTION_POINT_FIELDS = (
    "id",
    "trajectory_id",
    "turn_id",
    "agent_run_id",
    "transcript_id",
    "transcript_idx",
    "action_unit_idx",
    "first_block_idx",
    "summary",
    "group",
    "x",
    "y",
    "fps_rank",
)


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


def _bounded_compact_text(value: object, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None

    compact = " ".join(value.split())
    if not compact:
        return None
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 1].rstrip()}…"


def _metadata_sources(metadata: object) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        return []

    root = cast(dict[str, Any], metadata)
    sources = [root]
    for key in ("metadata", "agent_run_metadata"):
        nested = root.get(key)
        if isinstance(nested, dict):
            sources.append(cast(dict[str, Any], nested))
    for source in list(sources):
        scores = source.get("scores")
        if isinstance(scores, dict):
            sources.append(cast(dict[str, Any], scores))
    return sources


def _metadata_value(metadata: object, key: str) -> object | None:
    for source in _metadata_sources(metadata):
        for candidate in (key, f"metadata.{key}"):
            value = source.get(candidate)
            if value is not None:
                return cast(object, value)
    return None


def _compact_scalar(value: object, max_chars: int) -> str | None:
    if isinstance(value, str):
        return _bounded_compact_text(value, max_chars)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _bounded_compact_text(str(value), max_chars)
    return None


def _compact_task_id(metadata: object) -> str | None:
    for key in ("task_id", "task_name", "task_slug"):
        value = _metadata_value(metadata, key)
        compact = _compact_scalar(value, 256)
        if compact is not None:
            return compact

        if isinstance(value, dict):
            task_id = cast(dict[str, Any], value)
            org = _compact_scalar(task_id.get("org"), 96)
            name = _compact_scalar(task_id.get("name"), 160)
            if org and name:
                return _bounded_compact_text(f"{org}/{name}", 256)
            if name:
                return name
    return None


def _compact_outcome(metadata: object, exception_type: str | None) -> str | None:
    terminal_outcome = _compact_scalar(_metadata_value(metadata, "terminal_outcome"), 64)
    normalized_exception = (exception_type or "").lower()
    normalized_terminal = (terminal_outcome or "").lower()

    if "timeout" in normalized_exception or "timeout" in normalized_terminal:
        return "timeout"
    if exception_type is not None or any(
        marker in normalized_terminal for marker in ("exception", "error")
    ):
        return "exception"

    for key in ("passed", "success"):
        success = _metadata_value(metadata, key)
        if isinstance(success, bool):
            return "passed" if success else "failed"

    reward = _metadata_value(metadata, "reward")
    if isinstance(reward, int | float) and not isinstance(reward, bool):
        if reward == 1:
            return "passed"
        if reward == 0:
            return "failed"

    return terminal_outcome


def build_hodoscope_projection_view(projection: dict[str, Any]) -> dict[str, Any]:
    """Build the compact public projection without mutating the stored projection."""

    view = {
        key: deepcopy(projection[key])
        for key in _HODOSCOPE_PROJECTION_TOP_LEVEL_FIELDS
        if key in projection
    }
    view["view_schema_version"] = "hodoscope_projection_view.v1"
    points_raw: object = projection.get("points", [])
    public_points: list[dict[str, Any]] = []

    if isinstance(points_raw, list):
        for point_raw in cast(list[object], points_raw):
            if not isinstance(point_raw, dict):
                continue

            point = cast(dict[str, Any], point_raw)
            public_point = {
                key: deepcopy(point.get(key)) for key in _HODOSCOPE_PROJECTION_POINT_FIELDS
            }
            context_excerpt = (
                _bounded_compact_text(
                    point.get("context_excerpt"), HODOSCOPE_CONTEXT_EXCERPT_MAX_CHARS
                )
                or _bounded_compact_text(
                    point.get("task_context"), HODOSCOPE_CONTEXT_EXCERPT_MAX_CHARS
                )
                or _bounded_compact_text(
                    point.get("action_text"), HODOSCOPE_CONTEXT_EXCERPT_MAX_CHARS
                )
            )
            public_point["context_excerpt"] = context_excerpt or ""

            metadata = point.get("metadata")
            exception_type = _compact_scalar(point.get("exception_type"), 128) or _compact_scalar(
                _metadata_value(metadata, "exception_type"), 128
            )
            outcome = _compact_scalar(point.get("outcome"), 64) or _compact_outcome(
                metadata, exception_type
            )
            task_id = _compact_scalar(point.get("task_id"), 256) or _compact_task_id(metadata)
            if outcome is not None:
                public_point["outcome"] = outcome
            if exception_type is not None:
                public_point["exception_type"] = exception_type
            if task_id is not None:
                public_point["task_id"] = task_id

            public_points.append(public_point)

    view["points"] = public_points
    return view


def expand_hodoscope_projection_view(
    projection: dict[str, Any], artifact: dict[str, Any] | None
) -> dict[str, Any]:
    """Restore the legacy full projection shape from a compact stored projection."""

    points = projection.get("points")
    if not isinstance(points, list) or not points:
        full_projection = deepcopy(projection)
        full_projection.pop("view_schema_version", None)
        return full_projection
    if isinstance(points[0], dict) and "embedding" in points[0]:
        return projection

    summaries = artifact.get("summaries") if isinstance(artifact, dict) else None
    if not isinstance(summaries, list):
        full_projection = deepcopy(projection)
        full_projection.pop("view_schema_version", None)
        return full_projection

    point_rows = cast(list[object], points)
    summary_rows = cast(list[object], summaries)
    if len(summary_rows) != len(point_rows):
        full_projection = deepcopy(projection)
        full_projection.pop("view_schema_version", None)
        return full_projection

    full_projection = deepcopy(projection)
    full_projection.pop("view_schema_version", None)
    full_points = cast(list[object], full_projection["points"])
    for point_raw, summary_raw in zip(full_points, summary_rows, strict=True):
        if not isinstance(point_raw, dict) or not isinstance(summary_raw, dict):
            continue
        point = cast(dict[str, Any], point_raw)
        summary = cast(dict[str, Any], summary_raw)
        for key in ("action_text", "task_context", "metadata", "embedding"):
            if key in summary:
                point[key] = deepcopy(summary[key])
    return full_projection


class HodoscopeAnalysisConfig(BaseModel):
    name: str = "Hodoscope analysis"
    group_by: str | None = None
    limit: int = Field(default=500, ge=1, le=10_000)
    max_actions: int = Field(default=5_000, ge=500, le=5_000)
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

    @staticmethod
    def _summary_from_mapping(row: Mapping[Any, Any]) -> HodoscopeAnalysisSummary:
        config_json = cast(dict[str, Any], row["config_json"])
        job_state_raw: object = config_json.get("_job_state", {})
        job_state = cast(dict[str, Any], job_state_raw) if isinstance(job_state_raw, dict) else {}
        stage_raw: object = job_state.get("stage")
        progress_raw: object = job_state.get("progress")
        return HodoscopeAnalysisSummary(
            id=row["id"],
            collection_id=row["collection_id"],
            job_id=row["job_id"],
            name=row["name"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            config={k: v for k, v in config_json.items() if k != "_job_state"},
            error=row["error"],
            stage=stage_raw if isinstance(stage_raw, str) else None,
            progress=progress_raw if isinstance(progress_raw, int) else None,
            point_count=int(row["point_count"] or 0),
            group_count=int(row["group_count"] or 0),
        )

    @staticmethod
    def _summary_columns() -> tuple[Any, ...]:
        projection = SQLAHodoscopeAnalysis.projection_json
        return (
            SQLAHodoscopeAnalysis.id,
            SQLAHodoscopeAnalysis.collection_id,
            SQLAHodoscopeAnalysis.job_id,
            SQLAHodoscopeAnalysis.name,
            SQLAHodoscopeAnalysis.status,
            SQLAHodoscopeAnalysis.created_at,
            SQLAHodoscopeAnalysis.updated_at,
            SQLAHodoscopeAnalysis.completed_at,
            SQLAHodoscopeAnalysis.config_json,
            SQLAHodoscopeAnalysis.error,
            func.coalesce(func.jsonb_array_length(projection["points"]), 0).label("point_count"),
            func.coalesce(func.jsonb_array_length(projection["groups"]), 0).label("group_count"),
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
        result = await self.session.execute(
            select(*self._summary_columns()).where(
                SQLAHodoscopeAnalysis.collection_id == ctx.collection_id,
                SQLAHodoscopeAnalysis.id == analysis_id,
            )
        )
        row = result.mappings().one_or_none()
        return self._summary_from_mapping(row) if row else None

    async def list_analyses(self, ctx: ViewContext) -> list[HodoscopeAnalysisSummary]:
        result = await self.session.execute(
            select(*self._summary_columns())
            .where(SQLAHodoscopeAnalysis.collection_id == ctx.collection_id)
            .order_by(SQLAHodoscopeAnalysis.created_at.desc())
        )
        return [self._summary_from_mapping(row) for row in result.mappings().all()]

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

    async def get_projection(
        self, ctx: ViewContext, analysis_id: str, *, compact: bool = False
    ) -> dict[str, Any] | None:
        columns = [SQLAHodoscopeAnalysis.projection_json]
        if not compact:
            columns.append(SQLAHodoscopeAnalysis.artifact_json)
        result = await self.session.execute(
            select(*columns).where(
                SQLAHodoscopeAnalysis.collection_id == ctx.collection_id,
                SQLAHodoscopeAnalysis.id == analysis_id,
            )
        )
        row = result.one_or_none()
        if row is None or row[0] is None:
            return None
        projection = cast(dict[str, Any], row[0])
        if compact:
            return build_hodoscope_projection_view(projection)
        artifact = cast(dict[str, Any] | None, row[1])
        return expand_hodoscope_projection_view(projection, artifact)

    async def get_artifact(self, ctx: ViewContext, analysis_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(SQLAHodoscopeAnalysis.artifact_json).where(
                SQLAHodoscopeAnalysis.collection_id == ctx.collection_id,
                SQLAHodoscopeAnalysis.id == analysis_id,
            )
        )
        return result.scalar_one_or_none()

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
