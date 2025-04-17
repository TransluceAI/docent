from copy import deepcopy
from datetime import datetime
from typing import Any, cast

from docent.describe_interv import (
    describe_insertion_intervention,
    describe_replacement_intervention,
)
from docent.experiments.runner import run_experiment_in_subprocess
from docent.loader.load_inspect import load_inspect_experiment
from docent.server.ws_handlers.send_framegrid import handle_get_state, send_datapoints_updated
from docent.server.ws_handlers.util import ConnectionManager, WSMessage
from docent.types import TASK_ARGS_DICT
from fastapi import WebSocket
from frames.frame import FrameGrid
from frames.transcript import Transcript, TranscriptMetadata
from frames.types import Datapoint
from llm_util.types import ChatMessage, parse_chat_message
from log_util import get_logger

logger = get_logger(__name__)


async def handle_conversation_intervention(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
):
    """[Setter] Start a conversation intervention.

    Expected payload:
    {
        "datapoint_id": str,  # ID of the datapoint to modify
        "message_index": int,  # Index of the message to replace/insert at
        "new_message": dict,   # New message object to insert with format matching ChatMessage
        "insert": bool = False # If True, insert the message at index, otherwise replace
    }

    Raises:
        ValueError: If payload is incomplete or malformed.
    """
    datapoint_id = msg.payload["datapoint_id"]
    message_index = msg.payload["message_index"]
    new_message_data = msg.payload["new_message"]
    num_additional_messages = msg.payload.get("num_additional_messages", None)
    num_epochs = msg.payload.get("num_epochs", 5)
    is_insert = msg.payload.get("insert", False)

    api_keys = cm.get_api_keys(socket_fg_id)

    logger.info(f"Received conversation intervention: {msg.payload}")

    # Make sure user is not requesting too much stuff
    if num_additional_messages and num_additional_messages > 50:
        raise ValueError("num_additional_messages must be less than 50")
    if num_epochs and num_epochs > 10:
        raise ValueError("num_epochs must be less than 10")

    logger.info(f"Received conversation intervention: {msg.payload}")

    if not isinstance(datapoint_id, str):
        raise ValueError("datapoint_id must be a string")
    if not isinstance(message_index, int):
        raise ValueError("message_index must be an integer")
    if not isinstance(new_message_data, dict):
        raise ValueError("new_message must be a dict")
    if not isinstance(is_insert, bool):
        raise ValueError("insert must be a boolean")

    # Get the transcript from the datapoint
    datapoint = fg.all_data_dict[datapoint_id]
    transcript = datapoint.obj

    # Parameters for the experiment
    task_id = transcript.metadata.task_id
    sample_id = transcript.metadata.sample_id
    experiment_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
    epochs = num_epochs

    # Create TaskArgs for this particular task
    if task_id not in TASK_ARGS_DICT:
        raise ValueError(
            f"Task {task_id} not supported; shape of TaskArgs not known. You need to manually specify these in docent/types.py."
        )
    task_args_dict = transcript.metadata.task_args

    # Parse the new message based on its role
    if "role" not in new_message_data or not isinstance(new_message_data["role"], str):
        raise ValueError("new_message must be a dict with a str 'role' field")
    role = new_message_data["role"]
    if role not in ("system", "user", "assistant", "tool"):
        raise ValueError(f"Invalid message role: {role}")
    new_message = parse_chat_message(cast(dict[str, Any], new_message_data))

    # Create deep copy of the transcript and modify messages
    new_messages: list[ChatMessage] | None = deepcopy(transcript.messages)
    if (
        message_index < 0
        or (is_insert and message_index > len(new_messages))  # For insertion, allow up to len
        or (not is_insert and message_index >= len(new_messages))  # For replacement, must be < len
    ):
        raise ValueError(f"Invalid message index {message_index}")
    if is_insert:
        assert new_message.role != "system", "Cannot insert a new system message"

        # Insert the new message at message_index and remove subsequent messages
        new_messages.insert(message_index, new_message)
        new_messages = new_messages[: message_index + 1]

        # Describe the intervention
        intervention_description = await describe_insertion_intervention(
            new_message, transcript.messages[:message_index], api_keys
        )
    else:
        if new_message.role == "system":
            assert message_index == 0, "Cannot replace a non-first message with a system message"

            # Replace the system message, and don't do anything else
            task_args_dict["solver_system_message"] = new_message.content
            new_messages = None

            intervention_description = await describe_replacement_intervention(
                transcript.messages[message_index], new_message, [], api_keys
            )
        else:
            # Replace the message at message_index and delete all subsequent messages
            new_messages[message_index] = new_message
            new_messages = new_messages[: message_index + 1]

            # Describe the intervention
            intervention_description = await describe_replacement_intervention(
                transcript.messages[message_index],
                new_message,
                transcript.messages[:message_index],
                api_keys,
            )
    logger.info(f"Intervention description: {intervention_description}")

    # Add the new messages to the task args if they exist
    if new_messages:
        if new_messages[0].role == "system":
            new_messages = new_messages[1:]
        task_args_dict |= {"per_sample_inits": [(sample_id, new_messages)]}

    # Set max messages to the number of additional messages minus the number of new messages
    if num_additional_messages is not None:
        task_args_dict |= {
            "solver_max_messages": num_additional_messages
            + (len(new_messages) if new_messages else 0)
            + 1
        }

    # {sample_id: {epoch_id: transcript}}
    timestamp = datetime.now().isoformat()
    result_datapoints: dict[str | int, dict[int, Datapoint]] = {
        sample_id: {
            epoch_id: Datapoint.from_transcript(
                Transcript(
                    messages=[],
                    metadata=TranscriptMetadata(
                        task_id=task_id,
                        sample_id=sample_id,
                        epoch_id=epoch_id,
                        experiment_id=experiment_id,
                        intervention_description=intervention_description,
                        intervention_timestamp=timestamp,
                        intervention_index=message_index,
                        model=transcript.metadata.model,
                        task_args=task_args_dict,
                        is_loading_messages=True,
                        scores={k: 0 for k in transcript.metadata.scores.keys()},
                        default_score_key=transcript.metadata.default_score_key,
                        additional_metadata=transcript.metadata.additional_metadata,
                        scoring_metadata=transcript.metadata.scoring_metadata,
                    ),
                )
            )
            for epoch_id in range(1, epochs + 1)
        }
    }
    # Send the new datapoints to the client
    await fg.add_datapoints(
        [d for epoch_datapoints in result_datapoints.values() for d in epoch_datapoints.values()]
    )
    await handle_get_state(cm, websocket, fg)

    async def _message_stream_callback(
        task_id: str, sample_id: str | int, epoch_id: int, messages: list[ChatMessage]
    ):
        """Create temporary datapoints for each message in the stream, update its data, and send it to the client."""

        logger.info(
            "Message update from task_id %s, sample_id %s, epoch_id %s",
            task_id,
            sample_id,
            epoch_id,
        )

        dp = result_datapoints[sample_id][epoch_id]
        await fg.update_datapoint_content(dp.id, messages=messages)
        await send_datapoints_updated(cm, websocket, [dp.id])

    # Validate args and run experiment
    task_args = TASK_ARGS_DICT[task_id].model_validate(task_args_dict)
    api_keys = cm.get_api_keys(socket_fg_id)
    env_vars: dict[str, str] = {}
    if api_keys["anthropic_key"]:
        env_vars["ANTHROPIC_API_KEY"] = api_keys["anthropic_key"]
    if api_keys["openai_key"]:
        env_vars["OPENAI_API_KEY"] = api_keys["openai_key"]
    experiment_result = await run_experiment_in_subprocess(
        task_id=task_id,
        task_args=task_args,
        model=transcript.metadata.model,
        sample_ids=[sample_id],
        epochs=epochs,
        message_stream_callback=_message_stream_callback,
        use_cache=True,
        api_keys=env_vars,
    )
    logger.info("Experiment result paths: %s", experiment_result["results"])

    # Update the existing datapoints with the new transcripts
    if experiment_result["results"]:
        new_transcripts: list[Transcript] = []
        for result_fpath in experiment_result["results"]:
            new_transcripts.extend(load_inspect_experiment(experiment_id, result_fpath))

        # Update existing datapoints
        for t in new_transcripts:
            sample_id = t.metadata.sample_id
            epoch_id = t.metadata.epoch_id

            # Get the datapoint ID
            dp_id = result_datapoints[sample_id][epoch_id].id

            # Re-add metadata fields so they're not dropped
            metadata_dict = t.metadata.model_dump() | {
                "intervention_description": intervention_description,
                "intervention_index": message_index,
                "intervention_timestamp": timestamp,
                "is_loading_messages": False,
            }
            metadata = TranscriptMetadata.model_validate(metadata_dict)

            # Use the lightweight update_datapoint method to update with the new transcript data
            await fg.update_datapoint_content(
                dp_id,
                messages=t.messages,
                metadata=metadata,
            )

        # Send updated state; this should include the updated datapoints
        await handle_get_state(cm, websocket, fg)

    # fg.to_json("/home/ubuntu/scratch/fg.json")
