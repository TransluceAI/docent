import json
from typing import Any, AsyncContextManager, AsyncIterator, Callable, cast

import jsonschema
import redis.asyncio.client as redis_client
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from docent._llm_util.model_registry import get_model_info
from docent._llm_util.providers.preference_types import (
    ModelOption,
    ModelOptionWithContext,
    merge_models_with_byok,
)
from docent._llm_util.providers.provider_registry import PROVIDERS
from docent._log_util.logger import get_logger
from docent.sdk.llm_request import ExternalAnalysisResult, LLMRequest
from docent_core._server._broker.redis_client import (
    RESULT_SET_CHANNEL_FORMAT,
    get_redis_client,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.result_tables import SQLAResultSet
from docent_core.docent.db.schemas.tables import JobStatus
from docent_core.docent.server.dependencies.database import (
    get_session,
    get_session_cm_factory,
)
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    require_collection_permission,
)
from docent_core.docent.server.dependencies.services import get_mono_svc
from docent_core.docent.server.dependencies.user import (
    get_authenticated_user,
    get_default_view_ctx,
    get_user_anonymous_ok,
)
from docent_core.docent.services.llms import PROVIDER_PREFERENCES
from docent_core.docent.services.result_set import DEFAULT_OUTPUT_SCHEMA, ResultSetService

result_set_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])

logger = get_logger(__name__)

DEFAULT_RESULTS_LIMIT = 500
MAX_RESULTS_LIMIT = 2000


################
# Dependencies #
################


def get_result_set_service(
    session: AsyncSession = Depends(get_session),
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]] = Depends(
        get_session_cm_factory
    ),
) -> ResultSetService:
    return ResultSetService(session, session_cm_factory)


async def get_result_set_in_collection(
    collection_id: str,
    result_set_id_or_name: str,
    result_set_svc: ResultSetService = Depends(get_result_set_service),
) -> SQLAResultSet:
    """Fetch result set and validate it belongs to the collection."""
    result_set = await result_set_svc.get_result_set(result_set_id_or_name, collection_id)
    if result_set is None:
        raise HTTPException(
            status_code=404,
            detail=f"Result set '{result_set_id_or_name}' not found",
        )
    return result_set


################
# Request/Response Models #
################


class CreateResultSetRequest(BaseModel):
    name: str | None = None
    output_schema: dict[str, Any] = DEFAULT_OUTPUT_SCHEMA


class ResultSetResponse(BaseModel):
    id: str
    name: str | None
    output_schema: dict[str, Any]
    created_at: str
    result_count: int | None = None
    first_prompt_preview: str | None = None
    job_id: str | None = None
    job_status: JobStatus | None = None


class SubmitRequestsRequest(BaseModel):
    requests: list[LLMRequest] | None = None
    results: list[ExternalAnalysisResult] | None = None
    exists_ok: bool = False
    analysis_model: ModelOption | None = None
    output_schema: dict[str, Any] | None = None


class SubmitResponse(BaseModel):
    result_set_id: str
    job_id: str | None = None
    url: str


class ResultResponse(BaseModel):
    id: str
    result_set_id: str
    llm_context_spec: dict[str, Any]
    prompt_segments: list[str | dict[str, str]]
    user_metadata: dict[str, Any] | None
    output: dict[str, Any] | None
    error_json: dict[str, Any] | None
    input_tokens: int | None
    output_tokens: int | None
    model: str | None
    created_at: str | None
    cost_cents: float | None = None


class UpdateNameRequest(BaseModel):
    name: str | None


@result_set_router.get("/analysis-models")
async def get_analysis_models(
    mono_svc: Any = Depends(get_mono_svc),
    user: User = Depends(get_user_anonymous_ok),
) -> list[ModelOptionWithContext]:
    byok = PROVIDER_PREFERENCES.byok_chat_models + PROVIDER_PREFERENCES.byok_judge_models
    return merge_models_with_byok(
        defaults=PROVIDER_PREFERENCES.default_analysis_models,
        byok=byok,
        api_keys=await mono_svc.get_api_key_overrides(user),
    )


################
# Result Set CRUD #
################


@result_set_router.post("/{collection_id}/result-sets")
async def create_result_set(
    collection_id: str,
    request: CreateResultSetRequest,
    user: User = Depends(get_authenticated_user),
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
) -> ResultSetResponse:
    """Create a new result set."""
    try:
        result_set = await result_set_svc.create_result_set(
            collection_id=collection_id,
            user_id=user.id,
            output_schema=request.output_schema,
            name=request.name,
        )
    except (ValueError, TypeError, jsonschema.SchemaError, jsonschema.ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ResultSetResponse(
        id=result_set.id,
        name=result_set.name,
        output_schema=result_set.output_schema,
        created_at=result_set.created_at.isoformat() if result_set.created_at else "",
    )


@result_set_router.get("/{collection_id}/result-sets")
async def list_result_sets(
    collection_id: str,
    prefix: str | None = None,
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
) -> list[ResultSetResponse]:
    """List result sets in a collection."""
    result_sets = await result_set_svc.list_result_sets(collection_id, prefix=prefix)

    all_stats = await result_set_svc.get_bulk_result_set_stats([rs.id for rs in result_sets])

    responses: list[ResultSetResponse] = []
    for rs in result_sets:
        count, preview = all_stats.get(rs.id, (0, None))

        # Hide anonymous empty result sets
        if rs.name is None and count == 0:
            continue

        responses.append(
            ResultSetResponse(
                id=rs.id,
                name=rs.name,
                output_schema=rs.output_schema,
                created_at=rs.created_at.isoformat() if rs.created_at else "",
                result_count=count,
                first_prompt_preview=preview,
            )
        )

    return responses


@result_set_router.patch("/{collection_id}/result-sets/{result_set_id_or_name:path}/name")
async def update_result_set_name(
    collection_id: str,
    result_set_id_or_name: str,
    request: UpdateNameRequest,
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
) -> ResultSetResponse:
    """Update the name of a result set."""
    result_set = await result_set_svc.update_result_set_name(
        result_set_id_or_name, collection_id, request.name
    )
    if result_set is None:
        raise HTTPException(
            status_code=404,
            detail=f"Result set '{result_set_id_or_name}' not found",
        )
    return ResultSetResponse(
        id=result_set.id,
        name=result_set.name,
        output_schema=result_set.output_schema,
        created_at=result_set.created_at.isoformat() if result_set.created_at else "",
    )


@result_set_router.get("/{collection_id}/result-sets/{result_set_id_or_name:path}")
async def get_result_set(
    collection_id: str,
    result_set: SQLAResultSet = Depends(get_result_set_in_collection),
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
) -> ResultSetResponse:
    """Get a result set by ID or name."""
    stats = await result_set_svc.get_result_set_stats(result_set.id)
    count, preview = stats if stats else (0, None)

    # Get active job status
    active_job = await result_set_svc.get_active_job_for_result_set(result_set.id)

    return ResultSetResponse(
        id=result_set.id,
        name=result_set.name,
        output_schema=result_set.output_schema,
        created_at=result_set.created_at.isoformat() if result_set.created_at else "",
        result_count=count,
        first_prompt_preview=preview,
        job_id=active_job.id if active_job else None,
        job_status=active_job.status if active_job else None,
    )


@result_set_router.delete("/{collection_id}/result-jobs/{result_set_id_or_name:path}")
async def cancel_result_set_jobs(
    result_set: SQLAResultSet = Depends(get_result_set_in_collection),
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Cancel all active jobs for a result set."""
    cancelled_count = await result_set_svc.cancel_all_jobs_for_result_set(result_set.id)
    return {"message": f"Cancelled {cancelled_count} job(s)"}


@result_set_router.delete("/{collection_id}/result-sets/{result_set_id_or_name:path}")
async def delete_result_set(
    collection_id: str,
    result_set_id_or_name: str,
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, bool]:
    """Delete a result set and all its results."""
    deleted = await result_set_svc.delete_result_set(result_set_id_or_name, collection_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Result set '{result_set_id_or_name}' not found",
        )
    return {"deleted": True}


################
# Submission #
################


@result_set_router.post("/{collection_id}/submit/{result_set_id_or_name:path}")
async def submit_to_result_set(
    collection_id: str,
    result_set_id_or_name: str,
    request: SubmitRequestsRequest,
    ctx: ViewContext = Depends(get_default_view_ctx),
    user: User = Depends(get_user_anonymous_ok),
    mono_svc: Any = Depends(get_mono_svc),
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
) -> SubmitResponse:
    """Submit LLM requests or direct results to a result set."""
    if request.requests is None and request.results is None:
        raise HTTPException(
            status_code=400,
            detail="Either 'requests' or 'results' must be provided",
        )

    if request.requests is not None and request.results is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot provide both 'requests' and 'results'",
        )

    if request.requests is not None and len(request.requests) == 0:
        raise HTTPException(status_code=400, detail="'requests' list must not be empty")
    if request.results is not None and len(request.results) == 0:
        raise HTTPException(status_code=400, detail="'results' list must not be empty")

    analysis_model: ModelOption | None = request.analysis_model

    if analysis_model is not None:
        _validate_analysis_model_choice(analysis_model)

    # Get or create result set
    name = result_set_id_or_name if not _is_uuid(result_set_id_or_name) else None

    # Check if result set already exists
    existing_result_set = None
    if name is not None:
        existing_result_set = await result_set_svc.get_result_set(name, collection_id)

    if request.output_schema is not None:
        effective_request_output_schema = _add_citations_to_strings(request.output_schema)
    else:
        effective_request_output_schema = DEFAULT_OUTPUT_SCHEMA

    if existing_result_set is not None:
        if not request.exists_ok:
            raise HTTPException(
                status_code=409,
                detail=f"Result set with name '{name}' already exists. Make a new result set or pass exists_ok=True to append to this one.",
            )
        if effective_request_output_schema != existing_result_set.output_schema:
            raise HTTPException(
                status_code=400,
                detail=f"Provided output_schema does not match existing result set schema.\nExpected: {existing_result_set.output_schema}\nGot: {effective_request_output_schema}",
            )
        result_set = existing_result_set
    else:
        try:
            result_set = await result_set_svc.create_result_set(
                collection_id=collection_id,
                user_id=user.id,
                output_schema=effective_request_output_schema,
                name=name,
            )
        except (ValueError, TypeError, jsonschema.SchemaError, jsonschema.ValidationError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    job_id = None

    if request.requests:
        # Submit for LLM processing
        try:
            job_id = await result_set_svc.submit_requests(
                ctx,
                result_set.id,
                request.requests,
                analysis_model=analysis_model,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif request.results:
        # Submit direct results
        try:
            await result_set_svc.submit_results_direct(
                result_set.id, request.results, expected_collection_id=collection_id
            )
        except (ValueError, TypeError, jsonschema.SchemaError, jsonschema.ValidationError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # Build URL
    url = f"/dashboard/{collection_id}/results/{result_set.name or result_set.id}"

    return SubmitResponse(
        result_set_id=result_set.id,
        job_id=job_id,
        url=url,
    )


################
# Results #
################


@result_set_router.get("/{collection_id}/result/{result_id}")
async def get_result(
    collection_id: str,
    result_id: str,
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
) -> ResultResponse:
    """Get a single result by ID."""
    from docent._llm_util.model_registry import estimate_cost_cents

    result = await result_set_svc.get_result_by_id(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")

    # Verify the result belongs to a result set in this collection
    result_set = await result_set_svc.get_result_set(result.result_set_id, collection_id)
    if result_set is None:
        raise HTTPException(status_code=404, detail="Result not found")

    # Compute cost if we have model and token counts
    cost_cents: float | None = None
    if result.model and result.input_tokens is not None and result.output_tokens is not None:
        try:
            input_cost = estimate_cost_cents(result.model, result.input_tokens, "input")
            output_cost = estimate_cost_cents(result.model, result.output_tokens, "output")
            cost_cents = input_cost + output_cost
        except Exception:
            # If cost estimation fails, leave it as None
            pass

    return ResultResponse(
        id=result.id,
        result_set_id=result.result_set_id,
        llm_context_spec=result.llm_context_spec,
        prompt_segments=result.prompt_segments,
        user_metadata=result.user_metadata,
        output=result.output,
        error_json=result.error_json,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
        created_at=result.created_at.isoformat() if result.created_at else None,
        cost_cents=cost_cents,
    )


@result_set_router.get("/{collection_id}/results/{result_set_id_or_name:path}")
async def get_results(
    collection_id: str,
    result_set_id_or_name: str,
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    limit: int | None = None,
    offset: int = 0,
    with_auto_joins: bool = True,
    include_incomplete: bool = False,
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    result_set: SQLAResultSet = Depends(get_result_set_in_collection),
) -> list[dict[str, Any]]:
    """Get results for a result set."""
    effective_limit = min(limit or DEFAULT_RESULTS_LIMIT, MAX_RESULTS_LIMIT)
    return await result_set_svc.get_results(
        result_set.id,
        collection_id=collection_id,
        with_auto_joins=with_auto_joins,
        limit=effective_limit,
        offset=offset,
        include_incomplete=include_incomplete,
    )


################
# SSE Streaming #
################


# Type alias for Redis pubsub messages
PubSubMessage = dict[str, Any]


async def _listen_for_result_events(result_set_id: str) -> AsyncIterator[dict[str, Any]]:
    """Listen for result set events via Redis pub/sub."""
    redis_client_instance = await get_redis_client()
    channel = RESULT_SET_CHANNEL_FORMAT.format(result_set_id=result_set_id)

    pubsub: redis_client.PubSub = redis_client_instance.pubsub()  # type: ignore
    await pubsub.subscribe(channel)  # type: ignore[reportUnknownMemberType]

    logger.info(f"Subscribed to result set events on {channel}")

    try:
        async for message in pubsub.listen():  # type: ignore[reportUnknownMemberType]
            message_dict: PubSubMessage = message  # type: ignore[reportUnknownVariableType]
            if isinstance(message_dict, dict) and message_dict.get("type") == "message":  # type: ignore[reportUnknownMemberType]
                data_str: Any = message_dict.get("data")  # type: ignore[reportUnknownMemberType,reportUnknownVariableType]
                if isinstance(data_str, (str, bytes)):
                    data = json.loads(data_str if isinstance(data_str, str) else data_str.decode())
                    yield data
                    # Stop streaming if job is completed
                    if data.get("type") == "job_completed":
                        break
    finally:
        await pubsub.unsubscribe(channel)  # type: ignore[reportUnknownMemberType]
        await pubsub.close()


async def _sse_stream(result_set_id: str) -> AsyncIterator[str]:
    """Convert result events to SSE format."""
    async for event in _listen_for_result_events(result_set_id):
        yield f"data: {json.dumps(event)}\n\n"
    # Send done signal
    yield "data: [DONE]\n\n"


@result_set_router.get("/{collection_id}/stream/{result_set_id_or_name:path}")
async def stream_result_updates(
    collection_id: str,
    result_set_id_or_name: str,
    result_set_svc: ResultSetService = Depends(get_result_set_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    result_set: SQLAResultSet = Depends(get_result_set_in_collection),
) -> StreamingResponse:
    """SSE stream for result set updates.

    Clients subscribe to receive real-time updates as results are processed.
    Events:
    - result_completed: A result has been processed (success or error)
    - job_completed: The job has finished processing all results
    """
    return StreamingResponse(
        _sse_stream(result_set.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


################
# Helpers #
################


def _is_uuid(s: str) -> bool:
    """Check if a string looks like a UUID."""
    return len(s) == 36 and s.count("-") == 4


def _add_citations_to_strings(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively add citations: True to string types in a JSON schema.

    Skips fields that already have a citations key or have an enum defined.
    """
    schema = schema.copy()

    schema_type = schema.get("type")
    is_string = schema_type == "string" or (
        isinstance(schema_type, list) and "string" in schema_type
    )
    if is_string and "citations" not in schema and "enum" not in schema:
        schema["citations"] = True

    props = schema.get("properties")
    if isinstance(props, dict):
        props = cast(dict[str, Any], props)
        schema["properties"] = {
            k: _add_citations_to_strings(cast(dict[str, Any], v))
            for k, v in props.items()
            if isinstance(v, dict)
        }

    items = schema.get("items")
    if isinstance(items, dict):
        schema["items"] = _add_citations_to_strings(cast(dict[str, Any], items))

    for key in ("allOf", "anyOf", "oneOf"):
        arr = schema.get(key)
        if isinstance(arr, list):
            arr = cast(list[Any], arr)
            schema[key] = [
                _add_citations_to_strings(cast(dict[str, Any], s))
                for s in arr
                if isinstance(s, dict)
            ]

    add_props = schema.get("additionalProperties")
    if isinstance(add_props, dict):
        schema["additionalProperties"] = _add_citations_to_strings(cast(dict[str, Any], add_props))

    return schema


def _validate_analysis_model_choice(analysis_model: ModelOption) -> None:
    """Ensure requested analysis model has a valid provider and known model name."""
    if analysis_model.provider not in PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {analysis_model.provider}. "
            f"Valid providers are: {', '.join(sorted(PROVIDERS.keys()))}",
        )
    if get_model_info(analysis_model.model_name) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {analysis_model.model_name}",
        )
