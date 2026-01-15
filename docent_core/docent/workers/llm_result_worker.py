import json
from typing import Any, AsyncContextManager, Callable

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._llm_util.data_models.llm_output import AsyncLLMOutputStreamingCallback, LLMOutput
from docent._llm_util.model_registry import estimate_cost_cents
from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util import get_logger
from docent.data_models.chat.message import SystemMessage, UserMessage
from docent.judges.types import traverse_schema_and_transform
from docent.judges.util.parse_output import parse_and_validate_output_str
from docent.sdk.llm_context import LLMContextSpec, resolve_citations_with_context
from docent_core._db_service.db import DocentDB
from docent_core._server._broker.redis_client import publish_result_set_event
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.result_tables import SQLAResult, SQLAResultSet
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.llms import PROVIDER_PREFERENCES, LLMService
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.result_set import ResultSetService
from docent_core.docent.services.usage import UsageService
from docent_core.docent.utils.llm_context import load_context_objects

logger = get_logger(__name__)


async def llm_result_job(ctx: ViewContext | None, job: SQLAJob):
    """Process LLM requests for a result set.

    This worker processes pending results that have no output yet,
    calling the LLM service and updating the results with the response.
    """
    db = await DocentDB.init()
    mono_svc = await MonoService.init()

    async with db.session() as session:
        if ctx is None or ctx.user is None:
            result_set_id = job.job_json.get("result_set_id")
            user_id = job.job_json.get("user_id")
            user_email = job.job_json.get("user_email")
            if not isinstance(result_set_id, str) or not result_set_id:
                raise ValueError("Job is missing result_set_id; cannot construct context")
            if not isinstance(user_id, str) or not user_id:
                raise ValueError("Job is missing user_id; cannot construct context")

            result_set_row = await session.execute(
                select(SQLAResultSet).where(SQLAResultSet.id == result_set_id)
            )
            result_set = result_set_row.scalar_one_or_none()
            if result_set is None:
                raise ValueError(f"Result set {result_set_id} not found")

            from docent_core.docent.db.schemas.tables import SQLAUser

            user_row = await session.execute(select(SQLAUser).where(SQLAUser.id == user_id))
            sqla_user = user_row.scalar_one_or_none()
            if sqla_user is None:
                raise ValueError(
                    f"User {user_id} not found for LLM result job"
                    + (f" (email={user_email})" if user_email else "")
                )

            ctx = ViewContext(
                collection_id=result_set.collection_id,
                view_id="doesn't matter",
                user=sqla_user.to_user(),
                base_filter=None,
            )

        assert ctx.user is not None
        usage_svc = UsageService(db.session)
        llm_svc = LLMService(db.session, ctx.user, usage_svc)
        result_set_svc = ResultSetService(session, db.session)

        await _run_llm_result_job(ctx, job, db.session, result_set_svc, llm_svc, mono_svc)


def _is_default_output_schema(output_schema: dict[str, Any]) -> bool:
    """Check if the schema is the default output schema (object with just 'output' string property).

    When True, we skip adding schema instructions to the prompt and expect raw text.
    """
    if output_schema.get("type") != "object":
        return False
    properties = output_schema.get("properties", {})
    if set(properties.keys()) != {"output"}:
        return False
    output_prop = properties.get("output", {})
    if output_prop.get("type") != "string":
        return False
    allowed_keys = {"type", "citations"}
    return set(output_prop.keys()).issubset(allowed_keys)


def _schema_wants_citations(output_schema: dict[str, Any]) -> bool:
    """Check if any string property in the schema requests citation parsing."""
    if output_schema.get("type") == "string" and output_schema.get("citations") is True:
        return True
    for prop in output_schema.get("properties", {}).values():
        if _schema_wants_citations(prop):
            return True
    if "items" in output_schema:
        if _schema_wants_citations(output_schema["items"]):
            return True
    return False


def _make_schema_system_message(output_schema: dict[str, Any]) -> str:
    """Create a system message specifying the expected JSON output schema."""
    schema_str = json.dumps(output_schema, indent=2)
    return f"You must respond with valid JSON that conforms to the following JSON schema:\n\n{schema_str}\n\nRespond with only the JSON object and nothing else."


async def _run_llm_result_job(
    ctx: ViewContext,
    job: SQLAJob,
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
    result_set_svc: ResultSetService,
    llm_svc: LLMService,
    mono_svc: MonoService,
) -> None:
    """Core job logic separated for testing."""
    result_set_id = job.job_json["result_set_id"]
    result_ids = job.job_json["result_ids"]

    logger.info(
        "Processing LLM result job %s with %d results",
        job.id,
        len(result_ids),
    )

    # Get the result set to check the schema (using a temporary session)
    async with session_cm_factory() as session:
        result_set_result = await session.execute(
            select(SQLAResultSet).where(SQLAResultSet.id == result_set_id)
        )
        result_set = result_set_result.scalar_one_or_none()
        if result_set is None:
            raise ValueError(f"Result set {result_set_id} not found")

        output_schema = result_set.output_schema
        is_default_output = _is_default_output_schema(output_schema)
        wants_citations = _schema_wants_citations(output_schema)

    # Use default analysis models for LLM result processing
    model_options = PROVIDER_PREFERENCES.default_analysis_models
    analysis_model_raw = job.job_json.get("analysis_model")
    if analysis_model_raw is not None:
        model_options = [ModelOption.model_validate(analysis_model_raw)]

    # Use semaphore to limit concurrency (similar to rubrics)
    semaphore = anyio.Semaphore(llm_svc.max_concurrency * 2)
    processed_count = 0
    error_count = 0
    count_lock = anyio.Lock()

    async def _process_single_result(result_id: str) -> None:
        nonlocal processed_count, error_count
        async with semaphore:
            # Phase 1: Fetch result data (brief session)
            async with session_cm_factory() as session:
                result_row = await session.execute(
                    select(SQLAResult).where(SQLAResult.id == result_id)
                )
                result = result_row.scalar_one_or_none()
                if result is None:
                    logger.warning("Result %s not found, skipping", result_id)
                    return

                if result.output is not None:
                    logger.debug("Result %s already has output, skipping", result_id)
                    return

                # Extract data we need before releasing session
                spec = LLMContextSpec.model_validate(result.llm_context_spec)
                prompt_segments = result.prompt_segments

            # Phase 2: Load context and call LLM (no session held)
            try:
                context = await load_context_objects(spec, mono_svc)

                system_prompt = context.get_system_message(
                    interactive=False, include_citations=wants_citations
                )
                rendered_prompt = context.render_segments(prompt_segments)

                messages: list[SystemMessage | UserMessage] = [
                    SystemMessage(content=system_prompt),
                    UserMessage(content=rendered_prompt),
                ]

                # For custom schemas, add schema instruction and validation
                validation_callback: AsyncLLMOutputStreamingCallback | None = None
                if not is_default_output:
                    messages.append(
                        SystemMessage(content=_make_schema_system_message(output_schema))
                    )

                    async def _validation_callback(batch_index: int, llm_output: LLMOutput) -> None:
                        raw_text = llm_output.first_text or ""
                        # Not using the return value here - just checking if it's valid
                        parse_and_validate_output_str(raw_text, output_schema)

                    validation_callback = _validation_callback

                outputs = await llm_svc.get_completions(
                    inputs=[messages],
                    model_options=model_options,
                    max_new_tokens=8192,
                    timeout=120.0,
                    use_cache=True,
                    validation_callback=validation_callback,
                )
                llm_output = outputs[0]

                # Process LLM response
                if llm_output.did_error:
                    error_msg = (
                        llm_output.errors[0].user_message if llm_output.errors else "Unknown error"
                    )
                    error_json: dict[str, Any] = {
                        "error": "LLM error",
                        "message": error_msg,
                    }
                    async with session_cm_factory() as session:
                        result_row = await session.execute(
                            select(SQLAResult).where(SQLAResult.id == result_id)
                        )
                        result = result_row.scalar_one_or_none()
                        if result:
                            result.error_json = error_json
                            await session.commit()
                    async with count_lock:
                        error_count += 1
                    await publish_result_set_event(
                        result_set_id,
                        "result_completed",
                        {"result_id": result_id, "error_json": error_json},
                    )
                    return

                completion = llm_output.first
                if completion is None:
                    error_json = {
                        "error": "No response",
                        "message": "The model returned no response",
                    }
                    async with session_cm_factory() as session:
                        result_row = await session.execute(
                            select(SQLAResult).where(SQLAResult.id == result_id)
                        )
                        result = result_row.scalar_one_or_none()
                        if result:
                            result.error_json = error_json
                            await session.commit()
                    async with count_lock:
                        error_count += 1
                    await publish_result_set_event(
                        result_set_id,
                        "result_completed",
                        {"result_id": result_id, "error_json": error_json},
                    )
                    return

                raw_text = completion.text or ""

                if is_default_output:
                    output: dict[str, Any] = {"output": raw_text}
                else:
                    # Already validated by validation callback - now we just need the return value
                    output = parse_and_validate_output_str(raw_text, output_schema)

                if wants_citations:

                    def _resolve_citation_field(text: str) -> dict[str, Any]:
                        cleaned, cites = resolve_citations_with_context(text, context)
                        return {
                            "text": cleaned,
                            "citations": [c.model_dump(mode="json") for c in cites],
                        }

                    output = traverse_schema_and_transform(
                        output, output_schema, _resolve_citation_field
                    )

                # Phase 3: Write results (brief session)
                async with session_cm_factory() as session:
                    result_row = await session.execute(
                        select(SQLAResult).where(SQLAResult.id == result_id)
                    )
                    result = result_row.scalar_one_or_none()
                    if result:
                        result.output = output
                        result.model = llm_output.model
                        result.input_tokens = llm_output.usage["input"] or None
                        result.output_tokens = llm_output.usage["output"] or None
                        await session.commit()

                async with count_lock:
                    processed_count += 1

                input_tokens = llm_output.usage["input"] or None
                output_tokens = llm_output.usage["output"] or None
                cost_cents: float | None = None
                if llm_output.model and input_tokens is not None and output_tokens is not None:
                    try:
                        input_cost = estimate_cost_cents(llm_output.model, input_tokens, "input")
                        output_cost = estimate_cost_cents(llm_output.model, output_tokens, "output")
                        cost_cents = input_cost + output_cost
                    except Exception:
                        pass

                await publish_result_set_event(
                    result_set_id,
                    "result_completed",
                    {
                        "result_id": result_id,
                        "output": output,
                        "model": llm_output.model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_cents": cost_cents,
                    },
                )

            except Exception as e:
                logger.exception("Error processing result %s", result_id)
                async with count_lock:
                    error_count += 1

                error_json = {
                    "error": str(type(e).__name__),
                    "message": str(e),
                }
                try:
                    async with session_cm_factory() as session:
                        result_row = await session.execute(
                            select(SQLAResult).where(SQLAResult.id == result_id)
                        )
                        result = result_row.scalar_one_or_none()
                        if result:
                            result.error_json = error_json
                            await session.commit()
                except Exception:
                    logger.exception("Failed to update error status for result %s", result_id)

                await publish_result_set_event(
                    result_set_id,
                    "result_completed",
                    {"result_id": result_id, "error_json": error_json},
                )

    # Process all results in parallel
    async with anyio.create_task_group() as tg:
        for result_id in result_ids:
            tg.start_soon(_process_single_result, result_id)

    final_processed = processed_count
    final_errors = error_count

    logger.info(
        "Completed LLM result job %s: processed %d, errors %d",
        job.id,
        final_processed,
        final_errors,
    )

    # Publish job completed event
    await publish_result_set_event(
        result_set_id,
        "job_completed",
        {"job_id": job.id, "processed_count": final_processed, "error_count": final_errors},
    )
