import asyncio
import json
import os
import sys
from typing import Any

import inspect_ai
from docent.types import TASK_ARGS_DICT, RunnerArgs


def write_result(path: str, data: dict[str, Any]) -> None:
    """Write results to the output file with appropriate permissions."""
    # Ensure the output directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Write to the output file
    with open(path, "w") as f:
        # Set file permissions to be world readable/writable
        os.chmod(path, 0o666)
        json.dump(data, f)


async def main():
    """Main function that runs the inspect experiment.

    Raises:
        RuntimeError: If the process fails.
    """

    # Read arguments from stdin as JSON
    args = RunnerArgs.model_validate_json(sys.stdin.read())

    # Get the appropriate TaskArgs class based on task_id, then validate the task args
    # This also helps parse out sub-fields that are not primitives, e.g., ChatMessage.
    task_args_class = TASK_ARGS_DICT.get(args.task_id)
    if not task_args_class:
        raise ValueError(f"Unknown task_id: {args.task_id}. Not found in TASK_ARGS_DICT.")
    task_args = task_args_class.model_validate(args.task_args_dict)

    results = await inspect_ai.eval_async(
        tasks=[args.task_id],
        task_args={"args": task_args},
        model=args.model,
        sample_id=args.sample_ids,
        epochs=args.epochs,
        max_connections=args.max_connections,
        log_dir=args.log_dir,
        event_stream_dir=args.event_stream_dir,
    )

    results_fpaths = [result.location for result in results]

    write_result(
        args.result_path,
        data={"results": results_fpaths},
    )


if __name__ == "__main__":
    asyncio.run(main())
