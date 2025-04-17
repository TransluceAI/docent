import asyncio
import json
import os
import signal
import uuid
from pathlib import Path

from docent.event_streamer import AsyncMessageCallback, monitor_event_stream
from docent.experiments.experiment_cache import ExperimentCache
from docent.types import ExperimentResult, RunnerArgs, TaskArgs
from log_util import get_logger

logger = get_logger(__name__)


async def run_experiment_in_subprocess(
    task_id: str,
    task_args: TaskArgs,
    model: str,
    sample_ids: list[str | int] | None = None,
    epochs: int = 1,
    max_connections: int = 100,
    log_dir: str = "/home/ubuntu/artifacts/mengk/inspect_paris",
    message_stream_callback: AsyncMessageCallback | None = None,
    use_cache: bool = False,
    api_keys: dict[str, str] = {},
) -> ExperimentResult:
    if task_args.task_id != task_id:
        raise ValueError(
            f"Task ID mismatch: task_args.task_id={task_args.task_id} does not match task_id={task_id}"
        )

    # Check cache first if enabled
    if use_cache:
        cache = ExperimentCache()
        cached_result = cache.get(task_id, task_args, model, sample_ids, epochs)
        if cached_result is not None:
            logger.info("Inspect cache hit")
            return cached_result

    # Generate a unique path for results
    tmp_dir = Path(f"/tmp/inspect_experiment_{uuid.uuid4()}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    result_dir = tmp_dir / "results.json"

    # If we want to monitor the event stream, create a directory for it
    if message_stream_callback:
        event_stream_dir = tmp_dir / "stream"
        Path(event_stream_dir).mkdir(parents=True, exist_ok=True)
    else:
        event_stream_dir = None

    # Prepare the arguments
    args = RunnerArgs(
        task_id=task_id,
        task_args_dict=task_args.model_dump(),
        model=model,
        sample_ids=sample_ids,
        epochs=epochs,
        max_connections=max_connections,
        log_dir=log_dir,
        event_stream_dir=str(event_stream_dir),
        result_path=str(result_dir),
    )

    # Get the path to the runner script
    script_path = Path(__file__).parent / "run_inspect_experiment.sh"

    # If needed, set up monitoring on the stream directory
    monitor_task = None
    stop_event = None
    if event_stream_dir and message_stream_callback:
        stop_event = asyncio.Event()
        monitor_task = asyncio.create_task(
            monitor_event_stream(str(event_stream_dir), message_stream_callback, stop_event)
        )

    # mutate the api keys for the new environment but don't change the current one!
    env = {k: v for k, v in os.environ.items()}
    if "OPENAI_API_KEY" in api_keys:
        env["OPENAI_API_KEY"] = api_keys["OPENAI_API_KEY"]
    if "ANTHROPIC_API_KEY" in api_keys:
        env["ANTHROPIC_API_KEY"] = api_keys["ANTHROPIC_API_KEY"]

    # Create the subprocess with its own process group
    process = await asyncio.create_subprocess_exec(
        str(script_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=os.setsid,  # Create new process group
        env=env,
    )

    # Write the arguments to stdin
    assert process.stdin is not None
    process.stdin.write(args.model_dump_json().encode())
    await process.stdin.drain()
    process.stdin.close()

    captured_stdout: list[str] = []
    captured_stderr: list[str] = []
    try:
        # Create tasks for reading stdout and stderr concurrently

        async def collect_stderr():
            assert process.stderr is not None
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                line_str = line.decode().rstrip()
                captured_stderr.append(line_str)
                logger.warn(f"Stderr: {line_str}")

        async def collect_stdout():
            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode().rstrip()
                captured_stdout.append(line_str)
                logger.info(f"Stdout: {line_str}")

        # Create and run tasks
        stderr_task = asyncio.create_task(collect_stderr())
        stdout_task = asyncio.create_task(collect_stdout())

        # Wait for both stdout and stderr collection to complete
        await asyncio.gather(stdout_task, stderr_task)

        # Wait for process to complete
        await process.wait()

    except (asyncio.CancelledError, KeyboardInterrupt) as e:
        logger.info(f"Interrupt received during process communication (PID: {process.pid})")
        await _cleanup_process(process)
        raise e
    finally:
        if stop_event is not None:
            stop_event.set()
        if monitor_task is not None:
            await monitor_task

    if process.returncode != 0:
        logger.error(
            f"Process failed with return code {process.returncode}. Captured stderr:\n{'\n'.join(captured_stderr)}"
        )
        raise RuntimeError(f"Process failed with return code {process.returncode}.")

    # Read results from the temporary file
    with open(result_dir, "r") as f:
        result = json.load(f)

    experiment_result: ExperimentResult = {
        "results": result["results"],
        "captured_stdout": "\n".join(captured_stdout),
        "captured_stderr": "\n".join(captured_stderr),
    }

    # Cache the result if caching is enabled
    if use_cache:
        cache = ExperimentCache()
        cache.set(task_id, task_args, model, sample_ids, epochs, experiment_result)

    return experiment_result


async def _cleanup_process(process: asyncio.subprocess.Process) -> None:
    """Helper function to clean up a process and its process group."""
    logger.info(f"Attempting to terminate process group (PID: {process.pid})")
    try:
        # Kill the entire process group
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        logger.info("Sent SIGTERM to process group, waiting for graceful shutdown...")
        try:
            await asyncio.wait_for(process.wait(), timeout=10.0)
            logger.info("Process terminated successfully")
        except asyncio.TimeoutError:
            logger.error("Process didn't exit within 10s timeout, force killing with SIGKILL...")
            # If it doesn't exit in time, force kill
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            logger.info("SIGKILL sent to process group")
        except (asyncio.CancelledError, KeyboardInterrupt):
            # If we get interrupted during cleanup, force kill immediately
            logger.error("Received second interrupt during cleanup, force killing...")
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            raise
    except ProcessLookupError:
        # Process may already be gone
        logger.error("Process already terminated")
