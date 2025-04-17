import asyncio
import json
import traceback
from pathlib import Path
from typing import Any, Protocol

from llm_util.types import ChatMessage, parse_chat_message
from log_util import get_logger
from watchdog.events import FileModifiedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

logger = get_logger(__name__)


class AsyncMessageCallback(Protocol):
    async def __call__(
        self, task_id: str, sample_id: str | int, epoch_id: int, messages: list[ChatMessage]
    ) -> None: ...


class EventStreamHandler(FileSystemEventHandler):
    def __init__(self, message_stream_callback: AsyncMessageCallback):
        super().__init__()
        self.message_stream_callback = message_stream_callback
        self.loop = asyncio.get_event_loop()

    def on_modified(self, event: FileSystemEvent) -> None:
        if not isinstance(event, FileModifiedEvent):
            return

        logger.info(f"Event: {event}")

        # Handle the case where src_path might be bytes
        src_path = event.src_path
        if isinstance(src_path, bytes):
            src_path = src_path.decode()

        # Only process messages.jsonl files
        if not src_path.endswith("messages.jsonl"):
            return

        # Get the directory containing messages.jsonl
        event_dir = Path(src_path).parent

        try:
            # Read metadata.json from the same directory
            metadata_path = event_dir / "metadata.json"
            if not metadata_path.exists():
                return

            with open(metadata_path) as f:
                metadata: dict[str, Any] = json.load(f)

            # Extract required parameters
            task_id = metadata["task_id"]
            sample_id = metadata["sample_id"]
            epoch_id = metadata["epoch_id"]

            # Read messages from messages.jsonl
            with open(src_path) as f:
                messages = [parse_chat_message(json.loads(line)) for line in f]

            # Call the callback asynchronously
            asyncio.run_coroutine_threadsafe(
                self.message_stream_callback(task_id, sample_id, epoch_id, messages), self.loop
            )

        except Exception as e:
            logger.error(
                f"Error processing event stream file: {e}. Traceback: {traceback.format_exc()}"
            )


async def monitor_event_stream(
    event_stream_dir: str, message_stream_callback: AsyncMessageCallback, stop_event: asyncio.Event
) -> None:
    """Monitor the event stream directory for changes and call the message stream callback.

    Args:
        event_stream_dir: Directory to monitor for changes
        message_stream_callback: Callback to call when new messages are found
        stop_event: Event that will be set when monitoring should stop
    """
    logger.info(f"Setting up event stream monitoring for {event_stream_dir}")

    # Create the event handler and observer
    event_handler = EventStreamHandler(message_stream_callback)
    observer = PollingObserver()  # Use polling observer which works reliably across platforms
    observer.schedule(event_handler, event_stream_dir, recursive=True)
    observer.start()

    try:
        # Keep running until the stop event is set
        while not stop_event.is_set():
            await asyncio.sleep(0.1)
    finally:
        logger.info("Cleaning up event stream monitoring")
        observer.stop()
        observer.join()
