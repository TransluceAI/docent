"""
This file is called inspect_log to avoid naming conflicts with the built-in inspect module and the inspect_ai library.
"""

import tarfile
import tempfile
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


async def recursively_process_inspect_files(
    root_path: Path,
) -> Tuple[List[AgentRun], dict[str, Any]]:
    """
    Process an Inspect log file and extract agent runs.

    Args:
        file_path: Path to the uploaded file containing Inspect evaluation log

    Returns:
        tuple: (agent_runs, file_info) where file_info contains metadata about the file

    Raises:
        ValueError: If file processing fails
    """
    # Handle .tgz files by extracting to temp directory
    if not root_path.suffix.lower() == ".tgz" or not root_path.is_file():
        raise ValueError(f"File does not exist: {root_path}")

    agent_runs: List[AgentRun] = []
    file_info: dict[str, Any] = {}

    with tempfile.TemporaryDirectory() as temp_dir:
        with tarfile.open(root_path, "r:gz") as tar:
            tar.extractall(temp_dir)

        for file_path in Path(temp_dir).rglob("*.eval"):
            print(file_path)
            try:
                # Load the inspect log using the async interface to avoid uvloop conflicts
                eval_log = await read_eval_log_async(str(file_path))

                # Convert to agent runs using the existing load_inspect_log function
                agent_runs.extend(load_inspect_log(eval_log))

                # Extract file metadata
                file_info[file_path.name] = {
                    "filename": file_path.name,
                    "task": eval_log.eval.task if eval_log.eval else None,
                    "model": eval_log.eval.model if eval_log.eval else None,
                    "total_samples": len(eval_log.samples) if eval_log.samples else 0,
                }

            except Exception as e:
                print(f"Failed to process file '{file_path}': {str(e)}")

    return agent_runs, file_info
