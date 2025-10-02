import atexit
import os
import queue
import signal
import threading
import time
from typing import Any, AsyncGenerator, Callable, Coroutine, Optional

import anyio
import backoff
import httpx
import orjson
from backoff.types import Details

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun
from docent.sdk.client import Docent

logger = get_logger(__name__)


def _giveup(exc: BaseException) -> bool:
    """Give up on timeouts and client errors (4xx except 429). Retry others."""

    # Give up immediately on any timeout (connect/read/write/pool)
    if isinstance(exc, httpx.TimeoutException):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status < 500 and status != 429

    return False


def _print_backoff_message(e: Details):
    logger.warning(
        f"AgentRunWriter backing off for {e['wait']:.2f}s due to {e['exception'].__class__.__name__}"  # type: ignore
    )


async def _generate_payload_chunks(runs: list[AgentRun]) -> AsyncGenerator[bytes, None]:
    yield b'{"agent_runs": ['
    for i, ar in enumerate(runs):
        if i > 0:
            yield b","
        yield orjson.dumps(ar.model_dump(mode="json"))
    yield b"]}"


class AgentRunWriter:
    """Background thread for logging agent runs.

    Args:
        api_key (str): API key for the Docent API.
        collection_id (str): ID of the collection to log agent runs to.
        server_url (str): URL of the Docent server.
        num_workers (int): Max number of concurrent tasks to run,
            managed by anyio.CapacityLimiter.
        queue_maxsize (int): Maximum size of the queue.
            If maxsize is <= 0, the queue size is infinite.
        request_timeout (float): Timeout for the HTTP request.
        flush_interval (float): Interval to flush the queue.
        batch_size (int): Number of agent runs to batch together.
        max_retries (int): Maximum number of retries for the HTTP request.
        shutdown_timeout (int): Timeout to wait for the background thread to finish
            after the main thread has requested shutdown.
    """

    _instance: Optional["AgentRunWriter"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        api_key: str,
        collection_id: str,
        server_url: str = "https://api.docent.transluce.org",
        num_workers: int = 2,
        queue_maxsize: int = 20_000,
        request_timeout: float = 30.0,
        flush_interval: float = 1.0,
        batch_size: int = 1_000,
        max_retries: int = 5,
        shutdown_timeout: int = 60,
    ) -> None:
        with self._instance_lock:
            if AgentRunWriter._instance is not None:
                return
            AgentRunWriter._instance = self

        # Request parameters
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._base_url = server_url.rstrip("/") + "/rest"
        self._endpoint = f"{collection_id}/agent_runs"

        self._num_workers = num_workers
        self._request_timeout = request_timeout
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._shutdown_timeout = shutdown_timeout

        self._queue: queue.Queue[AgentRun] = queue.Queue(maxsize=queue_maxsize)
        self._cancel_event = threading.Event()

        # Start background thread
        self._thread = threading.Thread(
            target=lambda: anyio.run(self._async_main),
            name="AgentRunWriterThread",
        )
        self._thread.start()
        logger.info("AgentRunWriter thread started")

        self._register_shutdown_hooks()

    def _register_shutdown_hooks(self) -> None:
        """Register shutdown hooks for atexit and signals."""

        # Register shutdown hooks
        atexit.register(self.finish)

        def _handle_sigint(s: int, f: object) -> None:
            self._shutdown()
            raise KeyboardInterrupt

        def _handle_sigterm(s: int, f: object) -> None:
            self._shutdown()
            raise SystemExit(0)

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, _handle_sigint)  # Ctrl+C
        signal.signal(signal.SIGTERM, _handle_sigterm)  # Kill signal

    def log_agent_runs(self, agent_runs: list[AgentRun]) -> None:
        """Put a list of AgentRun objects into the queue.

        If the queue is full, the method will block until the queue has space.

        Args:
            agent_runs (list[AgentRun]): List of AgentRun objects to put into the queue.
        """

        p_full = (
            (self._queue.qsize() + len(agent_runs)) / self._queue.maxsize
            if self._queue.maxsize > 0
            else 0
        )
        if p_full >= 0.9:
            logger.warning("AgentRunWriter queue is almost full (>=90%).")

        for run in agent_runs:
            try:
                self._queue.put_nowait(run)
            except queue.Full:
                logger.warning("AgentRunWriter queue is full, blocking...")
                self._queue.put(run, block=True)

    def finish(self, force: bool = False) -> None:
        """Request shutdown and wait up to timeout for pending tasks to complete.

        Args:
            force (bool): If True, shut down immediately. If False, wait for pending tasks to complete.
        """
        if not force:
            # Wait for background thread to finish up to timeout
            logger.info("Waiting for pending tasks to complete")

            for i in range(0, self._shutdown_timeout, 5):
                if not self._thread.is_alive():
                    break

                if self._queue.empty():
                    break

                logger.info(
                    f"Waiting for pending tasks to complete " f"({i}/{self._shutdown_timeout})s"
                )
                time.sleep(5)

        self._shutdown()

    def _shutdown(self) -> None:
        """Shutdown the AgentRunWriter thread."""
        if self._thread.is_alive():
            logger.info("Cancelling pending tasks...")
            self._cancel_event.set()
            n_pending = self._queue.qsize()
            logger.info(f"Cancelled ~{n_pending} pending runs")

            # Give a brief moment to exit
            logger.info("Waiting for thread to exit...")
            self._thread.join(timeout=1.0)

    def get_post_batch_fcn(
        self, client: httpx.AsyncClient
    ) -> Callable[[list[AgentRun]], Coroutine[Any, Any, None]]:
        """Return a function that will post a batch of agent runs to the API."""

        @backoff.on_exception(
            backoff.expo,
            exception=httpx.HTTPError,
            giveup=_giveup,
            max_tries=self._max_retries,
            on_backoff=_print_backoff_message,
        )
        async def _post_batch(batch: list[AgentRun]) -> None:
            resp = await client.post(
                self._endpoint,
                content=_generate_payload_chunks(batch),
                timeout=self._request_timeout,
            )
            resp.raise_for_status()

        return _post_batch

    async def _async_main(self) -> None:
        """Main async function for the AgentRunWriter thread."""

        async with httpx.AsyncClient(base_url=self._base_url, headers=self._headers) as client:
            _post_batch = self.get_post_batch_fcn(client)
            async with anyio.create_task_group() as tg:

                async def worker():
                    while not self._cancel_event.is_set():
                        batch = await self._gather_next_batch_from_queue()
                        if not batch:
                            continue
                        try:
                            await _post_batch(batch)
                        except Exception as e:
                            logger.error(
                                f"Failed to post batch of {len(batch)} agent runs: {e.__class__.__name__}: {e}"
                            )

                for _ in range(self._num_workers):
                    tg.start_soon(worker)

    async def _gather_next_batch_from_queue(self) -> list[AgentRun]:
        """Gather a batch of agent runs from the queue.

        Fetches items from the queue until the batch is full or the timeout expires.
        """
        batch: list[AgentRun] = []
        with anyio.move_on_after(self._flush_interval):
            while len(batch) < self._batch_size:
                try:
                    item = self._queue.get_nowait()
                    batch.append(item)
                except queue.Empty:
                    await anyio.sleep(0.1)

        return batch


def init(
    collection_name: str = "Agent Run Collection",
    collection_id: str | None = None,
    server_url: str = "https://api.docent.transluce.org",
    web_url: str = "https://docent.transluce.org",
    api_key: str | None = None,
    # Writer arguments
    num_workers: int = 4,
    queue_maxsize: int = 20_000,
    request_timeout: float = 30.0,
    flush_interval: float = 1.0,
    batch_size: int = 1_000,
    max_retries: int = 5,
    shutdown_timeout: int = 60,
):
    """Initialize the AgentRunWriter thread.

    Args:
        collection_name (str): Name of the agent run collection.
        collection_id (str): ID of the agent run collection.
        server_url (str): URL of the Docent server.
        web_url (str): URL of the Docent web UI.
        api_key (str): API key for the Docent API.
        num_workers (int): Max number of concurrent tasks to run,
            managed by anyio.CapacityLimiter.
        queue_maxsize (int): Maximum size of the queue.
            If maxsize is <= 0, the queue size is infinite.
        request_timeout (float): Timeout for the HTTP request.
        flush_interval (float): Interval to flush the queue.
        batch_size (int): Number of agent runs to batch together.
        max_retries (int): Maximum number of retries for the HTTP request.
        shutdown_timeout (int): Timeout to wait for the background thread to finish
            after the main thread has requested shutdown.
    """
    api_key = api_key or os.getenv("DOCENT_API_KEY")

    if api_key is None:
        raise ValueError(
            "api_key is required. Please provide an "
            "api_key or set the DOCENT_API_KEY environment variable."
        )

    sdk = Docent(
        server_url=server_url,
        web_url=web_url,
        api_key=api_key,
    )

    collection_id = collection_id or sdk.create_collection(name=collection_name)

    return AgentRunWriter(
        api_key=api_key,
        collection_id=collection_id,
        server_url=server_url,
        # Writer arguments
        num_workers=num_workers,
        queue_maxsize=queue_maxsize,
        request_timeout=request_timeout,
        flush_interval=flush_interval,
        batch_size=batch_size,
        max_retries=max_retries,
        shutdown_timeout=shutdown_timeout,
    )
