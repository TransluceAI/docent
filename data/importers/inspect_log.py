"""
This file is called inspect_log to avoid naming conflicts with the built-in inspect module and the inspect_ai library.
"""

from pathlib import Path
from typing import Any, List, Tuple

from inspect_ai.log import read_eval_log_async
from pydantic_core import ValidationError

from docent.data_models.agent_run import AgentRun
from docent.loaders.load_inspect import load_inspect_log


async def process_inspect_file(file_path: Path) -> Tuple[List[AgentRun], dict[str, Any]]:
    """
    Process an Inspect log file and extract agent runs.

    Args:
        file_path: Path to the uploaded file containing Inspect evaluation log

    Returns:
        tuple: (agent_runs, file_info) where file_info contains metadata about the file

    Raises:
        ValueError: If file processing fails
    """
    if file_path.suffix.lower() not in [".eval", ".json"]:
        raise ValueError("File must be an .eval or .json file")

    try:
        # Load the inspect log using the async interface to avoid uvloop conflicts
        eval_log = await read_eval_log_async(str(file_path))

        # Convert to agent runs using the existing load_inspect_log function
        agent_runs = load_inspect_log(eval_log)

        # Extract file metadata
        file_info = {
            "filename": file_path.name,
            "task": eval_log.eval.task if eval_log.eval else None,
            "model": eval_log.eval.model if eval_log.eval else None,
            "total_samples": len(eval_log.samples) if eval_log.samples else 0,
        }

        return agent_runs, file_info

    except ValidationError as e:
        errors = e.errors()
        if not errors:
            message = f"Unknown validation error in file '{file_path}'"
        else:
            message = f"Validation errors in file '{file_path}':\n"
            for error in errors:
                message += f"  - {error['msg']} at {error['loc']}\n"
        raise ValueError(message)
    except Exception as e:
        raise ValueError(f"Failed to process file '{file_path}': {str(e)}")
