from typing import Any, AsyncContextManager, Callable, Sequence, cast
from uuid import uuid4

import jsonschema
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._llm_util.model_registry import estimate_cost_cents
from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util import get_logger
from docent.sdk.llm_context import AgentRunRef, LLMContextSpec, TranscriptRef
from docent.sdk.llm_request import ExternalAnalysisResult, LLMRequest
from docent_core._db_service.batched_writer import BatchedWriter
from docent_core._server._broker.redis_client import enqueue_job
from docent_core._worker.constants import WorkerFunction
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.result_tables import (
    SQLAResult,
    SQLAResultSet,
)
from docent_core.docent.db.schemas.tables import (
    JobStatus,
    SQLAAgentRun,
    SQLAJob,
    SQLATranscript,
)
from docent_core.docent.services.job import JobService

logger = get_logger(__name__)

PREVIEW_MAX_LENGTH = 100
RUN_KEY_SUFFIX = "run_id"
RESULT_KEY_SUFFIX = "result_id"


def _preview_from_segments(segments: list[Any]) -> str | None:
    """Extract a text preview from prompt segments, truncating to 100 chars."""
    text_parts: list[str] = [s for s in segments if isinstance(s, str)]
    if not text_parts:
        return None
    preview_text = "".join(text_parts)
    return (
        preview_text[:PREVIEW_MAX_LENGTH] + "..."
        if len(preview_text) > PREVIEW_MAX_LENGTH
        else preview_text
    )


DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"output": {"type": "string", "citations": True}},
    "required": ["output"],
}


def validate_result_set_schema(output_schema: dict[str, Any]) -> None:
    """Validate that the schema is a valid JSON Schema and an object at the top level."""
    jsonschema.Draft202012Validator.check_schema(output_schema)
    if output_schema.get("type") != "object":
        raise ValueError(
            "Result set schemas must be objects. "
            "Use the default schema or provide a schema with type: 'object'."
        )


def validate_result_output(output: Any, output_schema: dict[str, Any]) -> None:
    """Validate a single result output object against the result set schema."""
    if not isinstance(output, dict):
        raise TypeError(f"Result output must be a dict, got {type(output).__name__}")
    try:
        jsonschema.validate(cast(dict[str, Any], output), output_schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"Result output does not match schema: {e.message}") from e


class ResultSetService:
    """Service for managing LLM analysis result sets."""

    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
    ):
        self.session = session
        self.session_cm_factory = session_cm_factory
        self.job_svc = JobService(session, session_cm_factory)

    #################
    # ResultSet CRUD #
    #################

    async def create_result_set(
        self,
        collection_id: str,
        user_id: str,
        output_schema: dict[str, Any],
        name: str | None = None,
    ) -> SQLAResultSet:
        """Create a new result set."""
        validate_result_set_schema(output_schema)
        result_set = SQLAResultSet(
            id=str(uuid4()),
            collection_id=collection_id,
            user_id=user_id,
            name=name,
            output_schema=output_schema,
        )
        self.session.add(result_set)
        await self.session.flush()
        return result_set

    async def get_result_set(
        self,
        id_or_name: str,
        collection_id: str,
    ) -> SQLAResultSet | None:
        """Get a result set by ID or name."""
        # Try by ID first (if it looks like a UUID)
        if len(id_or_name) == 36 and "-" in id_or_name:
            result = await self.session.execute(
                select(SQLAResultSet).where(
                    SQLAResultSet.id == id_or_name,
                    SQLAResultSet.collection_id == collection_id,
                )
            )
            rs = result.scalar_one_or_none()
            if rs is not None:
                return rs

        # Try by name
        result = await self.session.execute(
            select(SQLAResultSet).where(
                SQLAResultSet.name == id_or_name,
                SQLAResultSet.collection_id == collection_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_result_set(
        self,
        collection_id: str,
        user_id: str,
        output_schema: dict[str, Any],
        name: str | None = None,
        exists_ok: bool = False,
    ) -> tuple[SQLAResultSet, bool]:
        """Get an existing result set by name or create a new one.

        Returns:
            Tuple of (result_set, created) where created is True if a new result set was created.
        """
        if name is not None:
            existing = await self.get_result_set(name, collection_id)
            if existing is not None:
                if not exists_ok:
                    raise ValueError(f"Result set with name '{name}' already exists")
                return existing, False

        result_set = await self.create_result_set(
            collection_id=collection_id,
            user_id=user_id,
            output_schema=output_schema,
            name=name,
        )
        return result_set, True

    async def list_result_sets(
        self,
        collection_id: str,
        prefix: str | None = None,
    ) -> Sequence[SQLAResultSet]:
        """List result sets in a collection, optionally filtered by name prefix."""
        query = (
            select(SQLAResultSet)
            .where(SQLAResultSet.collection_id == collection_id)
            .order_by(SQLAResultSet.created_at.desc())
        )

        if prefix is not None:
            query = query.where(SQLAResultSet.name.ilike(f"{prefix}%"))

        result = await self.session.execute(query)
        return result.scalars().all()

    async def delete_result_set(
        self,
        id_or_name: str,
        collection_id: str,
    ) -> bool:
        """Delete a result set and all its results. Returns True if deleted."""
        result_set = await self.get_result_set(id_or_name, collection_id)
        if result_set is None:
            return False

        await self.session.delete(result_set)
        return True

    async def update_result_set_name(
        self,
        id_or_name: str,
        collection_id: str,
        new_name: str | None,
    ) -> SQLAResultSet | None:
        """Update the name of a result set."""
        result_set = await self.get_result_set(id_or_name, collection_id)
        if result_set is None:
            return None

        result_set.name = new_name
        return result_set

    async def get_result_set_stats(self, result_set_id: str) -> tuple[int, str | None] | None:
        """Get stats for a result set: (count, first_prompt_preview)."""
        count_result = await self.session.execute(
            select(func.count(SQLAResult.id)).where(SQLAResult.result_set_id == result_set_id)
        )
        count = count_result.scalar_one() or 0

        if count == 0:
            return count, None

        # Get first result's prompt segments for preview
        first_result = await self.session.execute(
            select(SQLAResult.prompt_segments)
            .where(SQLAResult.result_set_id == result_set_id)
            .order_by(SQLAResult.created_at.asc())
            .limit(1)
        )
        segments = first_result.scalar_one_or_none()
        preview = _preview_from_segments(segments) if segments else None
        return count, preview

    async def get_bulk_result_set_stats(
        self, result_set_ids: list[str]
    ) -> dict[str, tuple[int, str | None]]:
        """Get stats for multiple result sets in bulk: {id: (count, preview)}."""
        if not result_set_ids:
            return {}

        count_result = await self.session.execute(
            select(SQLAResult.result_set_id, func.count(SQLAResult.id))
            .where(SQLAResult.result_set_id.in_(result_set_ids))
            .group_by(SQLAResult.result_set_id)
        )
        counts: dict[str, int] = {row[0]: row[1] for row in count_result.all()}

        result_set_ids_with_results = [
            rs_id for rs_id in result_set_ids if counts.get(rs_id, 0) > 0
        ]

        previews: dict[str, str | None] = {}
        if result_set_ids_with_results:
            from sqlalchemy import literal_column

            ranked_subq = (
                select(
                    SQLAResult.result_set_id,
                    SQLAResult.prompt_segments,
                    func.row_number()
                    .over(
                        partition_by=SQLAResult.result_set_id,
                        order_by=SQLAResult.created_at.asc(),
                    )
                    .label("rn"),
                )
                .where(SQLAResult.result_set_id.in_(result_set_ids_with_results))
                .subquery()
            )
            preview_result = await self.session.execute(
                select(ranked_subq.c.result_set_id, ranked_subq.c.prompt_segments).where(
                    literal_column("rn") == 1
                )
            )
            for rs_id, segments in preview_result.all():
                if segments:
                    previews[rs_id] = _preview_from_segments(segments)

        return {rs_id: (counts.get(rs_id, 0), previews.get(rs_id)) for rs_id in result_set_ids}

    ####################
    # Result operations #
    ####################

    async def submit_results_direct(
        self,
        result_set_id: str,
        results: list[ExternalAnalysisResult],
        expected_collection_id: str | None = None,
    ) -> None:
        """Submit pre-computed results directly to the database."""
        if not results:
            raise ValueError("results must be a non-empty list")

        result_set_row = await self.session.execute(
            select(SQLAResultSet.output_schema).where(SQLAResultSet.id == result_set_id)
        )
        output_schema_raw = result_set_row.scalar_one_or_none()
        if output_schema_raw is None:
            raise ValueError(f"Result set {result_set_id} not found")

        output_schema = output_schema_raw
        validate_result_set_schema(output_schema)

        # Parse and validate all specs before inserting to prevent cross-collection spoofing.
        parsed_requests: list[
            tuple[LLMContextSpec, list[str | dict[str, str]], ExternalAnalysisResult]
        ] = []
        agent_run_ids: set[str] = set()
        transcript_ids: set[str] = set()
        result_ids: set[str] = set()

        for result in results:
            validate_result_output(result.output, output_schema)
            spec_dict, segments = result.request.prompt.to_storage()
            spec = LLMContextSpec.model_validate(spec_dict)
            if expected_collection_id:
                self._validate_context_collection(spec, expected_collection_id)

            parsed_requests.append((spec, segments, result))

            for ref in spec.items.values():
                if isinstance(ref, AgentRunRef):
                    agent_run_ids.add(ref.id)
                elif isinstance(ref, TranscriptRef):
                    transcript_ids.add(ref.id)
                else:
                    result_ids.add(ref.id)

        # Verify that all referenced items actually belong to the expected collection.
        if agent_run_ids or transcript_ids or result_ids:
            actual_collections = await self._batch_get_item_collections(
                agent_run_ids, transcript_ids, result_ids
            )

            effective_collection = expected_collection_id
            if effective_collection is None and parsed_requests:
                for ref in parsed_requests[0][0].items.values():
                    effective_collection = getattr(ref, "collection_id", None)
                    if effective_collection:
                        break

            if effective_collection is None:
                raise ValueError("Unable to determine collection for submitted results")

            for spec, _, _ in parsed_requests:
                self._validate_spec_ownership(spec, actual_collections, effective_collection)

        async with BatchedWriter(self.session_cm_factory) as writer:
            sqla_results: list[Any] = []
            for spec, segments, result in parsed_requests:
                sqla_results.append(
                    SQLAResult(
                        id=str(uuid4()),
                        result_set_id=result_set_id,
                        llm_context_spec=spec.model_dump(),
                        prompt_segments=segments,
                        user_metadata=result.request.metadata,
                        output=result.output,
                    )
                )
            await writer.add_all(sqla_results)

    async def get_results(
        self,
        result_set_id: str,
        collection_id: str,
        with_auto_joins: bool = True,
        limit: int | None = None,
        offset: int = 0,
        include_incomplete: bool = False,
    ) -> list[dict[str, Any]]:
        """Get results for a result set, optionally with auto-joins.

        Args:
            collection_id: The collection that owns this result set. Used to scope
                auto-joins to prevent cross-collection data leaks.
            include_incomplete: If False (default), only return successful results
                (output is not null and error_json is null). If True, return all results.

        Auto-joins: If user_metadata contains keys ending in '_result_id' or '_run_id',
        the related data is joined and included in the response. Joins are batched
        to avoid N+1 queries.
        """
        query = (
            select(SQLAResult)
            .where(SQLAResult.result_set_id == result_set_id)
            .order_by(SQLAResult.created_at.asc())
            .offset(offset)
        )

        if not include_incomplete:
            query = query.where(
                SQLAResult.output.isnot(None),
                SQLAResult.error_json.is_(None),
            )

        if limit is not None:
            query = query.limit(limit)

        result = await self.session.execute(query)
        rows = result.scalars().all()

        # Phase 1: Build result dicts and collect IDs for batch joins
        results: list[dict[str, Any]] = []
        # join_plan[row_index] = [(prefix, "run"|"result", foreign_id), ...]
        join_plan: dict[int, list[tuple[str, str, str]]] = {}
        run_ids_to_fetch: set[str] = set()
        result_ids_to_fetch: set[str] = set()

        for idx, row in enumerate(rows):
            cost_cents: float | None = None
            if row.model and row.input_tokens is not None and row.output_tokens is not None:
                try:
                    input_cost = estimate_cost_cents(row.model, row.input_tokens, "input")
                    output_cost = estimate_cost_cents(row.model, row.output_tokens, "output")
                    cost_cents = input_cost + output_cost
                except Exception:
                    pass

            result_dict = {
                "id": row.id,
                "result_set_id": row.result_set_id,
                "llm_context_spec": row.llm_context_spec,
                "prompt_segments": row.prompt_segments,
                "user_metadata": row.user_metadata,
                "output": row.output,
                "error_json": row.error_json,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "model": row.model,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "cost_cents": cost_cents,
            }
            results.append(result_dict)

            if with_auto_joins and row.user_metadata:
                row_joins: list[tuple[str, str, str]] = []
                for key, value in row.user_metadata.items():
                    if not isinstance(value, str):
                        continue
                    if key.endswith(RUN_KEY_SUFFIX):
                        prefix = key[: -len(RUN_KEY_SUFFIX)]
                        row_joins.append((prefix, "run", value))
                        run_ids_to_fetch.add(value)
                    elif key.endswith(RESULT_KEY_SUFFIX):
                        prefix = key[: -len(RESULT_KEY_SUFFIX)]
                        row_joins.append((prefix, "result", value))
                        result_ids_to_fetch.add(value)
                if row_joins:
                    join_plan[idx] = row_joins

        # Phase 2: Bulk fetch joined data (scoped to collection to prevent cross-collection leaks)
        run_data_map: dict[str, dict[str, Any]] = {}
        result_data_map: dict[str, dict[str, Any]] = {}

        if run_ids_to_fetch:
            run_data_map = await self._bulk_fetch_agent_runs(run_ids_to_fetch, collection_id)
        if result_ids_to_fetch:
            result_data_map = await self._bulk_fetch_results(result_ids_to_fetch, collection_id)

        # Phase 3: Stitch joined data into result dicts
        for idx, row_joins in join_plan.items():
            result_dict = results[idx]
            joined_obj: dict[str, dict[str, Any]] = {}
            for prefix, join_type, foreign_id in row_joins:
                join_key = f"{prefix}{join_type}"
                if join_type == "run":
                    data = run_data_map.get(foreign_id)
                else:
                    data = result_data_map.get(foreign_id)
                if data:
                    joined_obj[join_key] = data
            if joined_obj:
                result_dict["joined"] = joined_obj

        return results

    async def _bulk_fetch_agent_runs(
        self, run_ids: set[str], collection_id: str
    ) -> dict[str, dict[str, Any]]:
        """Bulk fetch agent run metadata for auto-joins, scoped to collection."""
        if not run_ids:
            return {}
        result = await self.session.execute(
            select(SQLAAgentRun.id, SQLAAgentRun.metadata_json).where(
                SQLAAgentRun.id.in_(run_ids),
                SQLAAgentRun.collection_id == collection_id,
            )
        )
        return {row[0]: row[1] for row in result.all() if row[1] is not None}

    async def _bulk_fetch_results(
        self, result_ids: set[str], collection_id: str
    ) -> dict[str, dict[str, Any]]:
        """Bulk fetch result metadata and output for auto-joins, scoped to collection."""
        if not result_ids:
            return {}
        result = await self.session.execute(
            select(SQLAResult.id, SQLAResult.user_metadata, SQLAResult.output)
            .join(SQLAResultSet, SQLAResult.result_set_id == SQLAResultSet.id)
            .where(
                SQLAResult.id.in_(result_ids),
                SQLAResultSet.collection_id == collection_id,
            )
        )
        data_map: dict[str, dict[str, Any]] = {}
        for row in result.all():
            data: dict[str, Any] = {}
            if row[1]:  # user_metadata
                data.update(row[1])
            if row[2]:  # output
                data.update(row[2])
            if data:
                data_map[row[0]] = data
        return data_map

    async def get_result_by_id(self, result_id: str) -> SQLAResult | None:
        """Get a single result by ID."""
        result = await self.session.execute(select(SQLAResult).where(SQLAResult.id == result_id))
        return result.scalar_one_or_none()

    ####################
    # Context completion #
    ####################

    async def _complete_context_spec(self, context: LLMContextSpec) -> LLMContextSpec:
        """Ensure context spec has transcript refs for all agent runs.

        When a context spec is created with just agent run IDs (without transcript refs),
        the frontend can't display transcript counts or navigate to transcripts.
        This method queries the DB for transcript IDs and adds TranscriptRef entries.
        """
        from docent.sdk.llm_context import AgentRunRef, TranscriptRef

        # Collect agent run IDs that might need transcript refs
        agent_run_ids: list[str] = []
        agent_run_collection_ids: dict[str, str] = {}
        existing_transcript_ids: set[str] = set()

        for ref in context.items.values():
            if isinstance(ref, AgentRunRef):
                agent_run_ids.append(ref.id)
                agent_run_collection_ids[ref.id] = ref.collection_id
            elif isinstance(ref, TranscriptRef):
                existing_transcript_ids.add(ref.id)

        if not agent_run_ids:
            return context

        # Query transcript IDs for all agent runs in one batch
        result = await self.session.execute(
            select(SQLATranscript.id, SQLATranscript.agent_run_id).where(
                SQLATranscript.agent_run_id.in_(agent_run_ids)
            )
        )
        rows = result.all()

        # Add missing transcript refs
        for transcript_id, agent_run_id in rows:
            if transcript_id not in existing_transcript_ids:
                context.add_transcript(
                    id=transcript_id,
                    agent_run_id=agent_run_id,
                    collection_id=agent_run_collection_ids[agent_run_id],
                    is_root=False,
                )

        return context

    ####################
    # Job management   #
    ####################

    async def submit_requests(
        self,
        ctx: ViewContext,
        result_set_id: str,
        requests: list[LLMRequest],
        analysis_model: ModelOption | None = None,
    ) -> str:
        """Submit LLM requests for processing.

        Creates placeholder results in the database and starts a job to process them.

        Returns:
            The job ID.
        """
        if ctx.user is None:
            raise ValueError("User is required to submit requests")
        if not requests:
            raise ValueError("requests must be a non-empty list")

        parsed_specs: list[tuple[LLMContextSpec, list[str | dict[str, str]]]] = []
        all_agent_run_ids: set[str] = set()
        all_transcript_ids: set[str] = set()
        all_result_ids: set[str] = set()

        for request in requests:
            spec_dict, segments = request.prompt.to_storage()
            spec = LLMContextSpec.model_validate(spec_dict)
            self._validate_context_collection(spec, ctx.collection_id)
            parsed_specs.append((spec, segments))

            for ref in spec.items.values():
                if isinstance(ref, AgentRunRef):
                    all_agent_run_ids.add(ref.id)
                elif isinstance(ref, TranscriptRef):
                    all_transcript_ids.add(ref.id)
                else:
                    all_result_ids.add(ref.id)

        actual_collections = await self._batch_get_item_collections(
            all_agent_run_ids, all_transcript_ids, all_result_ids
        )

        for spec, _ in parsed_specs:
            self._validate_spec_ownership(spec, actual_collections, ctx.collection_id)

        result_ids: list[str] = []
        for (spec, segments), request in zip(parsed_specs, requests):
            completed_context = await self._complete_context_spec(spec)
            result = SQLAResult(
                id=str(uuid4()),
                result_set_id=result_set_id,
                llm_context_spec=completed_context.model_dump(),
                prompt_segments=segments,
                user_metadata=request.metadata,
            )
            self.session.add(result)
            result_ids.append(result.id)

        await self.session.flush()

        job_id = str(uuid4())
        job_json: dict[str, Any] = {
            "result_set_id": result_set_id,
            "result_ids": result_ids,
            "user_id": ctx.user.id,
            "user_email": ctx.user.email,
        }
        if analysis_model is not None:
            job_json["analysis_model"] = analysis_model.model_dump()

        job = SQLAJob(
            id=job_id,
            type=WorkerFunction.LLM_RESULT_JOB.value,
            job_json=job_json,
        )
        self.session.add(job)
        await self.session.flush()
        await self.session.commit()

        await enqueue_job(ctx, job_id, job_type=WorkerFunction.LLM_RESULT_JOB)
        return job_id

    async def get_active_job_for_result_set(self, result_set_id: str) -> SQLAJob | None:
        """Get the currently active job for a result set, if any."""
        result = await self.session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.LLM_RESULT_JOB.value)
            .where(SQLAJob.job_json["result_set_id"].astext == result_set_id)
            .where(SQLAJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.CANCELLING]))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_jobs_for_result_set(self, result_set_id: str) -> list[SQLAJob]:
        """Get all active jobs for a result set."""
        result = await self.session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.LLM_RESULT_JOB.value)
            .where(SQLAJob.job_json["result_set_id"].astext == result_set_id)
            .where(SQLAJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.CANCELLING]))
        )
        return list(result.scalars().all())

    async def cancel_all_jobs_for_result_set(self, result_set_id: str) -> int:
        """Cancel all active jobs for a result set. Returns the number of jobs cancelled."""
        jobs = await self.get_active_jobs_for_result_set(result_set_id)
        for job in jobs:
            await self.job_svc.cancel_job(job.id)
        return len(jobs)

    @staticmethod
    def _validate_context_collection(spec: LLMContextSpec, expected_collection_id: str) -> None:
        """Ensure all claimed collection_ids match the expected collection."""
        for ref in spec.items.values():
            if getattr(ref, "collection_id", None) != expected_collection_id:
                raise ValueError(
                    f"Context reference collection mismatch: expected {expected_collection_id}, got {getattr(ref, 'collection_id', None)}"
                )

    async def _batch_get_item_collections(
        self,
        agent_run_ids: set[str],
        transcript_ids: set[str],
        result_ids: set[str],
    ) -> dict[str, str]:
        """Batch query actual collection_ids for all referenced items."""
        actual_collections: dict[str, str] = {}

        if agent_run_ids:
            result = await self.session.execute(
                select(SQLAAgentRun.id, SQLAAgentRun.collection_id).where(
                    SQLAAgentRun.id.in_(agent_run_ids)
                )
            )
            for row in result.all():
                actual_collections[row[0]] = row[1]

        if transcript_ids:
            result = await self.session.execute(
                select(SQLATranscript.id, SQLATranscript.collection_id).where(
                    SQLATranscript.id.in_(transcript_ids)
                )
            )
            for row in result.all():
                actual_collections[row[0]] = row[1]

        if result_ids:
            result = await self.session.execute(
                select(SQLAResult.id, SQLAResultSet.collection_id)
                .join(SQLAResultSet, SQLAResult.result_set_id == SQLAResultSet.id)
                .where(SQLAResult.id.in_(result_ids))
            )
            for row in result.all():
                actual_collections[row[0]] = row[1]

        return actual_collections

    @staticmethod
    def _validate_spec_ownership(
        spec: LLMContextSpec,
        actual_collections: dict[str, str],
        expected_collection_id: str,
    ) -> None:
        """Verify items actually belong to their claimed collections."""
        for ref in spec.items.values():
            actual = actual_collections.get(ref.id)
            if actual is None:
                raise ValueError(f"Item {ref.id} not found")
            if actual != expected_collection_id:
                raise ValueError(
                    f"Item {ref.id} belongs to collection {actual}, not {expected_collection_id}"
                )
