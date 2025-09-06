import json
from pathlib import Path
from typing import Any, List, Tuple
from uuid import uuid4

from docent.data_models.agent_run import AgentRun


async def import_agent_runs_from_json(file_path: Path) -> Tuple[List[AgentRun], dict[str, Any]]:
    """Import agent runs from a JSON file containing a list of agent run dictionaries.

    Args:
        file_path: Path to the JSON file containing a list of agent run dictionaries

    Returns:
        tuple: (agent_runs, file_info) where file_info contains metadata about the file

    Raises:
        ValueError: If the JSON structure is invalid or agent run validation fails
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file contains invalid JSON
    """
    with open(file_path, "r") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON file to contain a list, got {type(data).__name__}")

    agent_runs = []
    for i, agent_run_dict in enumerate(data):
        try:
            # Replace agent run ID with new UUID
            agent_run_dict["id"]
            new_agent_run_id = str(uuid4())
            agent_run_dict["id"] = new_agent_run_id

            # Create mapping for transcript IDs and replace them
            transcript_id_mapping = {}
            for t_key, transcript in agent_run_dict["transcripts"].items():
                old_transcript_id = transcript["id"]
                new_transcript_id = str(uuid4())
                transcript["id"] = new_transcript_id
                transcript_id_mapping[old_transcript_id] = new_transcript_id

            # Create mapping for transcript group IDs and replace them
            transcript_group_id_mapping = {}
            for tg_key, transcript_group in agent_run_dict["transcript_groups"].items():
                old_tg_id = transcript_group["id"]
                new_tg_id = str(uuid4())
                transcript_group["id"] = new_tg_id
                transcript_group_id_mapping[old_tg_id] = new_tg_id

                # Update agent_run_id reference
                transcript_group["agent_run_id"] = new_agent_run_id

            # Update parent_transcript_group_id references
            for tg in agent_run_dict["transcript_groups"].values():
                if tg["parent_transcript_group_id"] is not None:
                    old_parent_id = tg["parent_transcript_group_id"]
                    if old_parent_id in transcript_group_id_mapping:
                        tg["parent_transcript_group_id"] = transcript_group_id_mapping[
                            old_parent_id
                        ]

            # Update transcript_group_id references in transcripts
            for transcript in agent_run_dict["transcripts"].values():
                if transcript.get("transcript_group_id") is not None:
                    old_tg_id = transcript["transcript_group_id"]
                    if old_tg_id in transcript_group_id_mapping:
                        transcript["transcript_group_id"] = transcript_group_id_mapping[old_tg_id]

            agent_run = AgentRun.model_validate(agent_run_dict)
            agent_runs.append(agent_run)
        except Exception as e:
            raise ValueError(f"Failed to validate agent run at index {i}: {e}")

    file_info = {
        "filename": file_path.name,
        "total_agent_runs": len(agent_runs),
    }

    return agent_runs, file_info
