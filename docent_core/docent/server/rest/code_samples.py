from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from docent_core.docent.db.filters import ComplexFilter
from docent_core.docent.db.schemas.auth_models import Permission, ResourceType, User
from docent_core.docent.db.schemas.rubric import SQLARubric
from docent_core.docent.server.dependencies.database import get_mono_svc
from docent_core.docent.server.dependencies.services import get_rubric_service
from docent_core.docent.server.dependencies.user import get_user_anonymous_ok
from docent_core.docent.services.code_samples import (
    CodeSampleService,
    PythonSample,
    PythonSampleType,
    SampleFormat,
)
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService

code_samples_router = APIRouter()


class BasePythonSampleRequest(BaseModel):
    api_key: str
    server_url: str | None = None
    collection_id: str
    format: Literal["python", "notebook"] = "python"


class AgentRunSampleRequest(BasePythonSampleRequest):
    type: Literal[PythonSampleType.AGENT_RUNS] = PythonSampleType.AGENT_RUNS
    columns: list[str]
    sort_field: str | None = None
    sort_direction: Literal["asc", "desc"] = "desc"
    base_filter: ComplexFilter | None = None
    limit: int | None = None


class DqlSampleRequest(BasePythonSampleRequest):
    type: Literal[PythonSampleType.DQL] = PythonSampleType.DQL
    dql_query: str
    filename: str | None = None
    description: str | None = None


class RubricSampleRequest(BasePythonSampleRequest):
    type: Literal[PythonSampleType.RUBRIC_RESULTS] = PythonSampleType.RUBRIC_RESULTS
    rubric_id: str
    rubric_version: int | None = None
    runs_filter: ComplexFilter | None = None
    limit: int | None = None


PythonSampleRequest = Annotated[
    AgentRunSampleRequest | DqlSampleRequest | RubricSampleRequest,
    Field(discriminator="type"),
]


class PythonSampleResponse(BaseModel):
    filename: str
    description: str
    dql_query: str
    content: str
    format: Literal["python", "notebook"]

    @classmethod
    def from_sample(cls, sample: PythonSample) -> "PythonSampleResponse":
        return cls(
            filename=sample.filename,
            description=sample.description,
            dql_query=sample.dql_query,
            content=sample.content,
            format=sample.format.value,
        )


@code_samples_router.post("/python", response_model=PythonSampleResponse)
async def create_python_sample(
    request: PythonSampleRequest,
    http_request: Request,
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: MonoService = Depends(get_mono_svc),
    rubric_svc: RubricService = Depends(get_rubric_service),
):
    allowed = await mono_svc.has_permission(
        user=user,
        resource_type=ResourceType.COLLECTION,
        resource_id=request.collection_id,
        permission=Permission.READ,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"User {user.id} does not have read permission on collection {request.collection_id}",
        )

    server_url = request.server_url or str(http_request.base_url).rstrip("/")
    try:
        sample_format = SampleFormat(request.format)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Unsupported format: {request.format}"
        ) from exc

    try:
        if isinstance(request, AgentRunSampleRequest):
            rubric_versions: dict[str, int] | None = None
            rubric_ids = CodeSampleService.collect_rubric_ids(
                request.columns,
                request.base_filter,
                request.sort_field,
            )
            if rubric_ids:
                async with mono_svc.db.session() as session:
                    result = await session.execute(
                        select(SQLARubric.id, func.max(SQLARubric.version))
                        .where(
                            SQLARubric.collection_id == request.collection_id,
                            SQLARubric.id.in_(sorted(rubric_ids)),
                        )
                        .group_by(SQLARubric.id)
                    )
                    rubric_versions = {
                        rubric_id: version
                        for rubric_id, version in result.all()
                        if version is not None
                    }
            sample = CodeSampleService.build_agent_runs_sample(
                api_key=request.api_key,
                server_url=server_url,
                collection_id=request.collection_id,
                columns=request.columns,
                sort_field=request.sort_field,
                sort_direction=request.sort_direction,
                base_filter=request.base_filter,
                limit=request.limit,
                rubric_versions=rubric_versions,
                format=sample_format,
            )
        elif isinstance(request, DqlSampleRequest):
            sample = CodeSampleService.build_dql_sample(
                api_key=request.api_key,
                server_url=server_url,
                collection_id=request.collection_id,
                dql_query=request.dql_query,
                description=request.description
                or "Runs the current DQL query and loads the rows into pandas via the Docent SDK.",
                filename=request.filename or f"dql_query_{request.collection_id}",
                format=sample_format,
            )
        else:  # RubricSampleRequest
            sqla_rubric = await rubric_svc.get_rubric(request.rubric_id, request.rubric_version)
            if sqla_rubric is None or sqla_rubric.collection_id != request.collection_id:
                raise HTTPException(status_code=404, detail=f"Rubric {request.rubric_id} not found")
            effective_version = request.rubric_version or sqla_rubric.version
            sample = CodeSampleService.build_rubric_results_sample(
                api_key=request.api_key,
                server_url=server_url,
                collection_id=request.collection_id,
                rubric_id=request.rubric_id,
                rubric_version=effective_version,
                output_schema=sqla_rubric.output_schema,
                runs_filter=request.runs_filter,
                limit=request.limit,
                format=sample_format,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return PythonSampleResponse.from_sample(sample)
