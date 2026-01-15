"""Server utilities for working with LLMContext.

This module depends on database services (MonoService) and is separated from the SDK.
"""

from typing import Any

import tiktoken
from sqlalchemy import select

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.formatted_objects import FormattedAgentRun, FormattedTranscript
from docent.data_models.transcript import Transcript
from docent.sdk.llm_context import (
    AgentRunRef,
    AnalysisResult,
    ContextItemRef,
    LLMContext,
    LLMContextSpec,
    ResultRef,
    TranscriptRef,
)
from docent_core.docent.db.schemas.result_tables import SQLAResult
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


async def load_context_objects(spec: LLMContextSpec, mono_svc: MonoService) -> LLMContext:
    object_cache: dict[str, Any] = {}

    agent_run_ids: set[str] = set()
    transcript_ids: set[str] = set()
    result_refs: list[ResultRef] = []
    for ref in spec.items.values():
        if isinstance(ref, AgentRunRef):
            agent_run_ids.add(ref.id)
        elif isinstance(ref, TranscriptRef):
            transcript_ids.add(ref.id)
        else:
            result_refs.append(ref)

    for obj_id, obj_data in spec.inline_data.items():
        if obj_id in agent_run_ids:
            formatted_run = FormattedAgentRun.model_validate(obj_data)
            object_cache[obj_id] = formatted_run
            for transcript in formatted_run.transcripts:
                object_cache[transcript.id] = transcript
        elif obj_id in transcript_ids:
            formatted_transcript = FormattedTranscript.model_validate(obj_data)
            object_cache[obj_id] = formatted_transcript

    agent_run_ids_to_fetch = [arid for arid in agent_run_ids if arid not in object_cache]
    if agent_run_ids_to_fetch:
        agent_runs = await mono_svc.get_agent_runs(
            ctx=None, agent_run_ids=agent_run_ids_to_fetch, apply_base_filter=False
        )
        for agent_run in agent_runs:
            object_cache[agent_run.id] = agent_run
            for transcript in agent_run.transcripts:
                object_cache[transcript.id] = transcript

    transcript_ids_to_fetch = [tid for tid in transcript_ids if tid not in object_cache]
    if transcript_ids_to_fetch:
        transcripts = await mono_svc.get_transcripts_by_ids(transcript_ids_to_fetch)
        for transcript in transcripts:
            object_cache[transcript.id] = transcript

    loaded_agent_runs: dict[str, AgentRun] = {}
    loaded_transcripts: dict[str, Transcript] = {}

    # Work on a copy of the spec so we can add missing transcript refs
    spec_copy = spec.model_copy(deep=True)

    for ref in spec.items.values():
        if isinstance(ref, AgentRunRef):
            agent_run = object_cache.get(ref.id)
            if agent_run is None:
                logger.error(f"Agent run {ref.id} not found in database (may have been deleted)")
                continue
            if not isinstance(agent_run, AgentRun):
                raise TypeError(f"Expected AgentRun for {ref.id}, got {type(agent_run)}")
            loaded_agent_runs[ref.id] = agent_run

            # Ensure all transcripts from this agent run are registered in the spec
            for transcript in agent_run.transcripts:
                loaded_transcripts[transcript.id] = transcript
                # Add transcript ref if not already present
                if not any(
                    isinstance(r, TranscriptRef) and r.id == transcript.id
                    for r in spec_copy.items.values()
                ):
                    spec_copy.add_transcript(
                        id=transcript.id,
                        agent_run_id=agent_run.id,
                        collection_id=ref.collection_id,
                        is_root=False,
                    )
        elif isinstance(ref, TranscriptRef):
            transcript = object_cache.get(ref.id)
            if transcript is None:
                logger.error(f"Transcript {ref.id} not found in database (may have been deleted)")
                continue
            loaded_transcripts[ref.id] = transcript

    loaded_results: dict[str, AnalysisResult] = {}
    if result_refs:
        result_ids = [ref.id for ref in result_refs]
        ref_by_id = {ref.id: ref for ref in result_refs}
        async with mono_svc.db.session() as session:
            result = await session.execute(select(SQLAResult).where(SQLAResult.id.in_(result_ids)))
            for sqla_result in result.scalars():
                ref = ref_by_id[sqla_result.id]
                loaded_results[sqla_result.id] = AnalysisResult(
                    id=sqla_result.id,
                    result_set_id=sqla_result.result_set_id,
                    collection_id=ref.collection_id,
                    output=sqla_result.output,
                )

    return LLMContext.from_spec(
        spec_copy,
        agent_runs=loaded_agent_runs,
        transcripts=loaded_transcripts,
        results=loaded_results,
    )


def compute_context_token_estimates(
    context: LLMContext, encoding_name: str = "o200k_base"
) -> dict[str, int]:
    """Compute token estimates for all root items in an LLMContext.

    PERF: This function loads and tokenizes all context items on every call.

    Args:
        context: LLMContext with loaded items
        encoding_name: Tiktoken encoding to use (default: o200k_base for GPT-4o)

    Returns:
        Dict mapping alias (e.g., "R0", "R1") to estimated token count
    """
    encoding = tiktoken.get_encoding(encoding_name)
    estimates: dict[str, int] = {}

    for alias in context.root_items:
        prefix = alias[0]

        try:
            if prefix == "R":
                view = context.build_agent_run_view(alias)
                id_to_idx_map = {
                    ref.id: int(t_alias[1:])
                    for t_alias, ref in context.spec.items.items()
                    if t_alias.startswith("T")
                    and t_alias[1:].isdigit()
                    and isinstance(ref, TranscriptRef)
                }
                text = view.to_text(agent_run_alias=alias, t_idx_map=id_to_idx_map)
            elif prefix == "T":
                ref: ContextItemRef | None = context.spec.items.get(alias)
                if ref is None or not isinstance(ref, TranscriptRef):
                    raise ValueError(f"Transcript {alias} not found")
                transcript = context.transcripts.get(ref.id)
                if transcript is None:
                    raise ValueError(f"Transcript {alias} not found")
                text = transcript.to_text(transcript_alias=alias)
            elif prefix == "A":
                ref = context.spec.items.get(alias)
                if ref is None or not isinstance(ref, ResultRef):
                    raise ValueError(f"Result {alias} not found")
                result = context.results.get(ref.id)
                if result is None:
                    raise ValueError(f"Result {alias} not found")
                text = result.to_text(alias)
            else:
                logger.warning(f"Unknown alias prefix: {alias}")
                continue

            estimates[alias] = len(encoding.encode(text, disallowed_special=()))
        except Exception as e:
            logger.warning(f"Failed to compute token estimate for {alias}: {e}")
            estimates[alias] = 0

    return estimates


def segments_to_aliased_string(segments: list[str | dict[str, str]]) -> str:
    """Convert prompt segments to aliased string for chat messages."""
    parts: list[str] = []
    for seg in segments:
        if isinstance(seg, dict) and "alias" in seg:
            parts.append(f"[{seg['alias']}]")
        else:
            parts.append(str(seg))
    return "\n\n".join(parts)
