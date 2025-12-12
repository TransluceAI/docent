"""Server utilities for working with LLMContext.

This module depends on database services (MonoService) and is separated from the SDK.
"""

from typing import Any

import tiktoken

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.formatted_objects import FormattedAgentRun, FormattedTranscript
from docent.data_models.transcript import Transcript
from docent.sdk.llm_context import (
    AgentRunRef,
    ContextItemRef,
    LLMContext,
    LLMContextSpec,
    TranscriptRef,
)
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


async def load_context_objects(spec: LLMContextSpec, mono_svc: MonoService) -> LLMContext:
    object_cache: dict[str, Any] = {}

    agent_run_ids: set[str] = set()
    transcript_ids: set[str] = set()
    for ref in spec.items.values():
        if isinstance(ref, AgentRunRef):
            agent_run_ids.add(ref.id)
        else:
            transcript_ids.add(ref.id)

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

    for ref in spec.items.values():
        if isinstance(ref, AgentRunRef):
            agent_run = object_cache.get(ref.id)
            if agent_run is None:
                logger.error(f"Agent run {ref.id} not found in database (may have been deleted)")
                continue
            if not isinstance(agent_run, AgentRun):
                raise TypeError(f"Expected AgentRun for {ref.id}, got {type(agent_run)}")
            loaded_agent_runs[ref.id] = agent_run
        else:
            transcript = object_cache.get(ref.id)
            if transcript is None:
                logger.error(f"Transcript {ref.id} not found in database (may have been deleted)")
                continue
            loaded_transcripts[ref.id] = transcript

    return LLMContext.from_spec(spec, agent_runs=loaded_agent_runs, transcripts=loaded_transcripts)


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
            else:
                logger.warning(f"Unknown alias prefix: {alias}")
                continue

            estimates[alias] = len(encoding.encode(text))
        except Exception as e:
            logger.warning(f"Failed to compute token estimate for {alias}: {e}")
            estimates[alias] = 0

    return estimates
