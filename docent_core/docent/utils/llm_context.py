"""Utilities for working with LLMContext in the server environment.

This module contains server-side utilities for LLMContext that require access
to database services like MonoService. These functions are separate from the
SDK to keep the SDK lightweight and dependency-free.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models.formatted_objects import FormattedAgentRun, FormattedTranscript
from docent.sdk.llm_context import LLMContext
from docent_core.docent.db.schemas.tables import SQLAAgentRun, SQLATranscript
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


async def enrich_llm_context_metadata(
    context_serialized: dict[str, Any], session: AsyncSession
) -> None:
    """Enrich serialized LLMContext with metadata from database.

    Populates both agent_run_collection_ids and transcript_to_agent_run mappings
    by querying the database.

    Args:
        context_serialized: Serialized LLMContext data (v2 format)
        session: Database session for querying metadata

    Note:
        Modifies context_serialized in-place by adding/updating metadata dicts.
    """
    # Extract all unique agent run and transcript IDs from alias dicts
    agent_run_ids = set(context_serialized.get("agent_run_aliases", {}).values())
    transcript_ids = set(context_serialized.get("transcript_aliases", {}).values())

    # Initialize or get existing dicts
    agent_run_collection_ids = context_serialized.get("agent_run_collection_ids", {})
    transcript_to_agent_run = context_serialized.get("transcript_to_agent_run", {})

    # Query transcript parentage
    if transcript_ids:
        result = await session.execute(
            select(SQLATranscript.id, SQLATranscript.agent_run_id).where(
                SQLATranscript.id.in_(transcript_ids)
            )
        )
        for transcript_id, agent_run_id in result:
            transcript_to_agent_run[str(transcript_id)] = str(agent_run_id)
            agent_run_ids.add(agent_run_id)

    # Query agent run collection IDs
    if agent_run_ids:
        result = await session.execute(
            select(SQLAAgentRun.id, SQLAAgentRun.collection_id).where(
                SQLAAgentRun.id.in_(agent_run_ids)
            )
        )
        for agent_run_id, collection_id in result:
            agent_run_collection_ids[str(agent_run_id)] = str(collection_id)

    # Update the serialized context
    context_serialized["agent_run_collection_ids"] = agent_run_collection_ids
    context_serialized["transcript_to_agent_run"] = transcript_to_agent_run


async def deserialize_llm_context(data: dict[str, Any], mono_svc: MonoService) -> LLMContext:
    """Reconstruct an LLMContext from serialized data.

    Uses v2 format with explicit alias mappings for stable citations.

    Args:
        data: Serialized context data from LLMContext.to_dict()
        mono_svc: MonoService instance for fetching agent runs from database

    Returns:
        Reconstructed LLMContext instance with all objects loaded

    Example:
        >>> context_data = session.context_serialized
        >>> context = await deserialize_llm_context(context_data, mono_svc)
        >>> system_prompt = context.get_system_message()
    """
    context = LLMContext()

    # Extract alias dicts
    transcript_aliases_serialized = data.get("transcript_aliases", {})
    agent_run_aliases_serialized = data.get("agent_run_aliases", {})
    formatted_data = data.get("formatted_data", {})

    # Collect all unique object IDs from aliases
    all_transcript_ids = set(transcript_aliases_serialized.values())
    all_agent_run_ids = set(agent_run_aliases_serialized.values())

    # Step 1: Deserialize formatted objects and build initial cache
    object_cache: dict[str, Any] = {}

    for obj_id, obj_data in formatted_data.items():
        if obj_id in all_agent_run_ids:
            formatted_obj = FormattedAgentRun.model_validate(obj_data)
            object_cache[obj_id] = formatted_obj
            for transcript in formatted_obj.transcripts:
                object_cache[transcript.id] = transcript
        elif obj_id in all_transcript_ids:
            formatted_obj = FormattedTranscript.model_validate(obj_data)
            object_cache[obj_id] = formatted_obj
        else:
            logger.warning(f"Formatted object {obj_id} not found in alias dicts, skipping")

    # Step 2: Determine what needs to be fetched (what's not already in cache)
    transcript_ids_to_fetch = [tid for tid in all_transcript_ids if tid not in object_cache]
    agent_run_ids_to_fetch = [arid for arid in all_agent_run_ids if arid not in object_cache]

    # Step 3: Fetch missing objects from database
    if agent_run_ids_to_fetch:
        agent_runs = await mono_svc.get_agent_runs(
            ctx=None, agent_run_ids=agent_run_ids_to_fetch, apply_base_where_clause=False
        )
        for agent_run in agent_runs:
            object_cache[agent_run.id] = agent_run
            # Index child transcripts
            for transcript in agent_run.transcripts:
                object_cache[transcript.id] = transcript

    if transcript_ids_to_fetch:
        transcripts = await mono_svc.get_transcripts_by_ids(transcript_ids_to_fetch)
        for transcript in transcripts:
            object_cache[transcript.id] = transcript

    # Populate alias dicts directly (convert string keys back to int)
    for str_idx, transcript_id in transcript_aliases_serialized.items():
        idx = int(str_idx)
        if transcript_id in object_cache:
            context.transcript_aliases[idx] = object_cache[transcript_id]
        else:
            logger.warning(f"Transcript {transcript_id} not found in cache, skipping")

    for str_idx, agent_run_id in agent_run_aliases_serialized.items():
        idx = int(str_idx)
        if agent_run_id in object_cache:
            context.agent_run_aliases[idx] = object_cache[agent_run_id]
        else:
            logger.warning(f"Agent run {agent_run_id} not found in cache, skipping")

    # Copy metadata dicts
    context.root_items = data.get("root_items", [])
    context.agent_run_collection_ids = data.get("agent_run_collection_ids", {})
    context.transcript_to_agent_run = data.get("transcript_to_agent_run", {})

    return context
