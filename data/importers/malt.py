import asyncio
import json
import random
from pathlib import Path
from typing import Any, List, Tuple

from datasets import load_dataset

from docent.data_models.agent_run import AgentRun, AgentRunWithoutMetadataValidator
from docent.data_models.chat import parse_chat_message
from docent.data_models.chat.message import ChatMessage
from docent.data_models.metadata import BaseAgentRunMetadata
from docent.data_models.transcript import Transcript

tool_call_id = 0


def _convert_malt_node_to_message(node: dict[str, Any]) -> dict[str, Any]:
    """Convert a MALT node to a message format compatible with parse_chat_message."""
    global tool_call_id

    node_data = node["node_data"]
    message = node_data["message"]

    # Extract basic message data
    result = {
        "role": message["role"],
        "content": message["content"] or "",
    }

    # Handle function calls for assistant messages
    if message.get("function_call"):
        function_call = message["function_call"]
        tool_call_id += 1
        result["tool_calls"] = [
            {
                "type": "function",
                "function": function_call["name"],
                "arguments": json.loads(function_call["arguments"]),
                "id": f"tool_call_{tool_call_id}",
            }
        ]

    # Handle tool messages (function role responses)
    if message["role"] == "function":
        result["role"] = "tool"
        result["function"] = message.get("name")

    return result


class MALTRunMetadata(BaseAgentRunMetadata):
    run_id: int
    version: str
    labels: list[str]
    task_id: str
    model: str
    has_chain_of_thought: bool


def load_malt_record(record: dict[str, Any]) -> AgentRun:
    """Convert a single MALT record to an AgentRun."""
    # Extract metadata
    metadata = MALTRunMetadata(
        run_id=record["run_id"],
        version=record["version"],
        labels=record["labels"],
        task_id=record["task_id"],
        model=record["model"],
        has_chain_of_thought=record["has_chain_of_thought"],
        scores={},  # MALT doesn't seem to have explicit scores in the example
    )

    # Convert nodes to messages, filtering out token usage messages
    messages: list[ChatMessage] = []
    for node in record["nodes"]:
        node_data = node["node_data"]
        message = node_data["message"]

        # Skip token usage messages
        if "So far in this attempt at the task, you have used" in message.get("content", ""):
            continue

        try:
            message_dict = _convert_malt_node_to_message(node)
            chat_message = parse_chat_message(message_dict)
            messages.append(chat_message)
        except Exception as e:
            # Skip problematic messages but log them
            print(f"Warning: Skipped message due to parsing error: {e}")
            continue

    # Create transcript
    transcript = Transcript(messages=messages, name=f"MALT Run {record.get('run_id', 'unknown')}")

    # Create AgentRun
    agent_run = AgentRun(
        name=f"MALT Task {record.get('task_id', 'unknown')} - Run {record.get('run_id', 'unknown')}",
        description=f"MALT evaluation run using model {record.get('model', 'unknown')}",
        transcripts={"main": transcript},
        metadata=metadata,
    )

    return agent_run


async def process_malt_dataset() -> Tuple[List[AgentRun], dict[str, Any]]:
    """
    Load the MALT dataset and extract agent runs. Note: this is a large dataset!

    Returns:
        tuple: (agent_runs, dataset_info) where dataset_info contains metadata about the dataset

    Raises:
        ValueError: If dataset loading fails
    """
    try:
        # Load the MALT dataset (requires HuggingFace authentication)
        ds = load_dataset("metr-evals/malt-transcripts-public", "default")

        agent_runs = []
        for record in ds["transcripts"]:
            try:
                agent_run = load_malt_record(record)
                agent_runs.append(agent_run)
            except Exception as e:
                print(f"Warning: Failed to convert record {record.get('run_id', 'unknown')}: {e}")
                continue

        # Extract dataset metadata
        dataset_info = {
            "source": "MALT (metr-evals/malt-transcripts-public)",
            "total_records": len(ds["transcripts"]),
            "processed_records": len(agent_runs),
            "features": list(ds["transcripts"].features.keys()) if ds["transcripts"] else [],
        }

        return agent_runs, dataset_info

    except Exception as e:
        raise ValueError(f"Failed to load MALT dataset: {str(e)}")


async def dump_malt_sample_to_json(
    output_path: str | Path, percentage: float = 0.1, seed: int | None = None
) -> dict[str, Any]:
    """
    Dump a random sample of the MALT dataset to a JSON file.

    Args:
        output_path: Path where the JSON file should be saved
        percentage: Percentage of dataset to sample (0.0 to 1.0)
        seed: Random seed for reproducible sampling

    Returns:
        dict: Summary information about the sampling process

    Raises:
        ValueError: If percentage is not between 0 and 1, or if dataset loading fails
    """
    if not 0 < percentage <= 1.0:
        raise ValueError("Percentage must be between 0 and 1")

    if seed is not None:
        random.seed(seed)

    try:
        # Load the MALT dataset
        ds = load_dataset("metr-evals/malt-transcripts-public", "default")
        total_records = len(ds["transcripts"])

        # Calculate sample size and randomly sample records
        sample_size = max(1, int(total_records * percentage))
        record_indices = random.sample(range(total_records), sample_size)
        sampled_records = [ds["transcripts"][i] for i in record_indices]

        # Convert to AgentRuns
        agent_runs = []
        failed_conversions = 0

        for record in sampled_records:
            try:
                agent_run = load_malt_record(record)
                agent_runs.append(agent_run)
            except Exception as e:
                print(f"Warning: Failed to convert record {record.get('run_id', 'unknown')}: {e}")
                failed_conversions += 1
                continue

        # Serialize to JSON
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert AgentRuns to dictionaries for JSON serialization
        serialized_runs = [agent_run.model_dump() for agent_run in agent_runs]

        # Create output data with metadata
        output_data = {
            "metadata": {
                "source": "MALT (metr-evals/malt-transcripts-public)",
                "sampling_info": {
                    "total_records": total_records,
                    "sample_percentage": percentage,
                    "sample_size": sample_size,
                    "successful_conversions": len(agent_runs),
                    "failed_conversions": failed_conversions,
                    "random_seed": seed,
                },
                "sampled_indices": sorted(record_indices),
            },
            "agent_runs": serialized_runs,
        }

        # Write to JSON file
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        summary = {
            "output_file": str(output_path),
            "total_dataset_size": total_records,
            "sampled_records": sample_size,
            "successful_conversions": len(agent_runs),
            "failed_conversions": failed_conversions,
            "sample_percentage": percentage,
        }

        print(f"Successfully dumped {len(agent_runs)} MALT agent runs to {output_path}")
        return summary

    except Exception as e:
        raise ValueError(f"Failed to sample and dump MALT dataset: {str(e)}")


async def process_malt_file_json(json_path: str | Path) -> Tuple[List[AgentRun], dict[str, Any]]:
    """
    Load AgentRuns from a JSON file created by dump_malt_sample_to_json.

    Args:
        json_path: Path to the JSON file containing serialized AgentRuns

    Returns:
        List[AgentRun]: List of deserialized AgentRun objects

    Raises:
        ValueError: If file cannot be read or AgentRuns cannot be deserialized
        FileNotFoundError: If the JSON file doesn't exist
    """
    json_path = Path(json_path)

    if not json_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract agent_runs from the JSON structure
        if "agent_runs" not in data:
            raise ValueError("JSON file missing 'agent_runs' key")

        agent_runs = []
        serialized_runs = data["agent_runs"]

        for i, serialized_run in enumerate(serialized_runs):
            try:
                agent_run = AgentRunWithoutMetadataValidator.model_validate(serialized_run)
                agent_runs.append(agent_run)
            except Exception as e:
                print(f"Warning: Failed to deserialize agent run {i}: {e}")
                continue

        print(f"Successfully loaded {len(agent_runs)} agent runs from {json_path}")

        # Print metadata info if available
        if "metadata" in data and "sampling_info" in data["metadata"]:
            sampling_info = data["metadata"]["sampling_info"]
            print(
                f"Original sample: {sampling_info.get('sample_percentage', 'unknown')}"
                f"of {sampling_info.get('total_records', 'unknown')} total records"
            )

        summary = {
            "total_records": len(agent_runs),
            "processed_records": len(agent_runs),
        }
        return agent_runs, summary

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON file: {e}")
    except Exception as e:
        raise ValueError(f"Failed to load agent runs from JSON: {e}")


async def main():
    # Dump a sample to JSON
    summary = await dump_malt_sample_to_json(
        output_path="malt_sample_1pct.json", percentage=0.01, seed=42
    )
    print(summary)


if __name__ == "__main__":
    asyncio.run(main())
