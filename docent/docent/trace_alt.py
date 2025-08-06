import asyncio
import atexit
import functools
import logging
import os
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from typing import Any, AsyncIterator, Callable, Dict, Iterator, Optional, Set

import requests
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import Span
from traceloop.sdk import Traceloop

DEFAULT_ENDPOINT = "https://api.docent.transluce.org/rest/telemetry"

# Context variables for tracking current agent run and collection
_current_agent_run_id: ContextVar[Optional[str]] = ContextVar("current_agent_run_id", default=None)
_current_collection_id: ContextVar[Optional[str]] = ContextVar(
    "current_collection_id", default=None
)

# Global configuration
_tracing_initialized = False
_collection_name: Optional[str] = None
_collection_id: Optional[str] = None
_endpoint: Optional[str] = None
_api_key: Optional[str] = None
_enable_console_export = False
_disable_batch = False
_instruments: Optional[Set[Any]] = None
_block_instruments: Optional[Set[Any]] = None


class DocentSpanProcessor(SpanProcessor):
    """Custom span processor to add Docent metadata to spans.

    This processor integrates cleanly with Traceloop's existing span processing
    and adds Docent-specific attributes to all spans.
    """

    def __init__(self, collection_id: str, enable_console_export: bool = False):
        self.collection_id = collection_id
        self.enable_console_export = enable_console_export

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        """Add Docent metadata when a span starts."""
        # Always add collection_id
        span.set_attribute("collection_id", self.collection_id)

        # Add agent_run_id if available
        agent_run_id = _get_current_agent_run_id()
        if agent_run_id:
            span.set_attribute("agent_run_id", agent_run_id)
        else:
            # If no agent_run_id in context, mark this as a default span
            span.set_attribute("agent_run_id_default", True)

        # Add service name for better integration with existing OTEL setups
        span.set_attribute("service.name", _collection_name or "docent-service")

        if self.enable_console_export:
            logging.debug(
                f"Span started - collection_id: {self.collection_id}, agent_run_id: {agent_run_id}"
            )

    def on_end(self, span: ReadableSpan) -> None:
        pass

    def shutdown(self) -> None:
        """Called when the processor is shut down."""

    def force_flush(self, timeout_millis: float = 30000) -> bool:
        """Force flush any pending spans."""
        return True


def initialize_tracing(
    collection_name: str,
    collection_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    enable_console_export: bool = False,
    disable_batch: bool = False,
    instruments: Optional[Set[Any]] = None,
    block_instruments: Optional[Set[Any]] = None,
) -> None:
    """Initialize Docent tracing with the specified configuration.

    This function provides a comprehensive initialization that integrates cleanly
    with existing OpenTelemetry setups and provides extensive configuration options.

    Args:
        collection_name: Name for your application/collection
        collection_id: Optional collection ID (auto-generated if not provided)
        endpoint: Optional OTLP endpoint URL (defaults to Docent's hosted service)
        api_key: Optional API key (uses DOCENT_API_KEY environment variable if not provided)
        enable_console_export: Whether to also export traces to console for debugging
        disable_batch: Whether to disable batch processing (use SimpleSpanProcessor)
        instruments: Set of instruments to enable (None = all instruments)
        block_instruments: Set of instruments to explicitly disable
    """
    global _tracing_initialized, _collection_name, _collection_id, _endpoint, _api_key
    global _enable_console_export, _disable_batch, _instruments, _block_instruments

    if _tracing_initialized:
        logging.warning("Docent tracing already initialized")
        return

    _collection_name = collection_name
    _collection_id = collection_id or _generate_id()
    _endpoint = endpoint or DEFAULT_ENDPOINT
    _api_key = api_key or os.getenv("DOCENT_API_KEY")
    _enable_console_export = enable_console_export
    _disable_batch = disable_batch
    _instruments = instruments
    _block_instruments = block_instruments

    _set_current_collection_id(_collection_id)

    if not _api_key:
        raise ValueError(
            "API key is required. Set DOCENT_API_KEY environment variable or pass api_key parameter."
        )

    # Initialize Traceloop with comprehensive configuration

    # Get Traceloop's default span processor
    from traceloop.sdk.tracing.tracing import get_default_span_processor

    # Create our custom context span processor (only adds metadata, doesn't export)
    docent_processor = DocentSpanProcessor(_collection_id, enable_console_export)

    # Get Traceloop's default span processor for export
    traceloop_processor = get_default_span_processor(
        disable_batch=_disable_batch,
        api_endpoint=_endpoint,
        headers={"Authorization": f"Bearer {_api_key}"},
    )

    # Combine both processors
    processors = [docent_processor, traceloop_processor]

    os.environ["TRACELOOP_METRICS_ENABLED"] = "false"
    os.environ["TRACELOOP_TRACE_ENABLED"] = "true"
    # Temporarily redirect stdout to suppress Traceloop's print statements
    # with redirect_stdout(io.StringIO()):
    Traceloop.init(  # type: ignore
        app_name=collection_name,
        api_endpoint=_endpoint,
        api_key=_api_key,
        telemetry_enabled=False,  # don't send telemetry to traceloop's backend
        disable_batch=_disable_batch,
        instruments=_instruments,
        block_instruments=_block_instruments,
        processor=processors,  # Add both our context processor and Traceloop's export processor
    )

    _tracing_initialized = True
    logging.info(
        f"Docent tracing initialized for collection: {collection_name} with collection_id: {_collection_id}"
    )

    # Register cleanup handlers
    atexit.register(_cleanup_tracing)


def _cleanup_tracing() -> None:
    """Clean up tracing resources on shutdown."""
    global _tracing_initialized
    if _tracing_initialized:
        try:
            # Notify API that the trace is over
            _notify_trace_done()

            logging.info("Docent tracing cleanup completed")
        except Exception as e:
            logging.warning(f"Error during tracing cleanup: {e}")
        finally:
            _tracing_initialized = False


def _ensure_tracing_initialized():
    """Ensure tracing has been initialized before use."""
    if not _tracing_initialized:
        raise RuntimeError("Docent tracing not initialized. Call initialize_tracing() first.")


def _generate_id() -> str:
    """Generate a unique ID for agent runs or collections."""
    return str(uuid.uuid4())


def _get_current_agent_run_id() -> Optional[str]:
    """Get the current agent run ID from context."""
    return _current_agent_run_id.get()


def _get_current_collection_id() -> Optional[str]:
    """Get the current collection ID from context."""
    return _current_collection_id.get()


def _set_current_agent_run_id(agent_run_id: Optional[str]) -> Token[Optional[str]]:
    """Set the current agent run ID in context."""
    return _current_agent_run_id.set(agent_run_id)


def _set_current_collection_id(collection_id: Optional[str]) -> Token[Optional[str]]:
    """Set the current collection ID in context."""
    return _current_collection_id.set(collection_id)


def _send_to_api(endpoint: str, data: Dict[str, Any]) -> None:
    """Send data to the Docent API endpoint.

    Args:
        endpoint: The API endpoint URL
        data: The data to send
    """
    try:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {_api_key}"}

        response = requests.post(endpoint, json=data, headers=headers, timeout=10)
        response.raise_for_status()

        logging.debug(f"Successfully sent data to {endpoint}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send data to {endpoint}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error sending data to {endpoint}: {e}")


def _notify_trace_done() -> None:
    """Notify the Docent API that the trace is done."""
    collection_id = _get_current_collection_id()
    if collection_id and _endpoint:
        data = {"collection_id": collection_id, "status": "completed"}
        _send_to_api(f"{_endpoint}/v1/trace-done", data)


def agent_run_score(name: str, score: float, attributes: Optional[Dict[str, Any]] = None) -> None:
    """
    Record a score event on the current span.
    Automatically works in both sync and async contexts.

    Args:
        name: Name of the score metric
        score: Numeric score value
        attributes: Optional additional attributes for the score event
    """
    _ensure_tracing_initialized()

    agent_run_id = _get_current_agent_run_id()
    if not agent_run_id:
        logging.warning("No active agent run context. Score will not be sent.")
        return

    collection_id = _get_current_collection_id() or _collection_id
    if not collection_id:
        logging.warning("No collection ID available. Score will not be sent.")
        return

    # Send score directly to API
    score_data = {
        "collection_id": collection_id,
        "agent_run_id": agent_run_id,
        "score_name": name,
        "score_value": score,
    }

    # Add additional attributes if provided
    if attributes:
        score_data.update(attributes)

    _send_to_api(f"{_endpoint}/v1/scores", score_data)


def agent_run_metadata(metadata: Dict[str, Any]) -> None:
    """Attach metadata to the current agent run.

    Args:
        metadata: Dictionary of metadata to attach
    """
    _ensure_tracing_initialized()

    agent_run_id = _get_current_agent_run_id()
    if not agent_run_id:
        logging.warning("No active agent run context. Metadata will not be sent.")
        return

    collection_id = _get_current_collection_id() or _collection_id
    if not collection_id:
        logging.warning("No collection ID available. Metadata will not be sent.")
        return

    # Send metadata directly to API
    metadata_data = {
        "collection_id": collection_id,
        "agent_run_id": agent_run_id,
        "metadata": metadata,
    }

    _send_to_api(f"{_endpoint}/v1/metadata", metadata_data)


@contextmanager
def _agent_run_context_sync(
    agent_run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[tuple[str, Optional[str]]]:
    """Synchronous context manager for creating and managing agent runs."""
    _ensure_tracing_initialized()

    # Generate IDs if not provided
    current_agent_run_id = agent_run_id or _generate_id()

    # Set up context
    agent_run_token = _set_current_agent_run_id(current_agent_run_id)

    try:
        # Send metadata to API if provided
        if metadata:
            agent_run_metadata(metadata)

        # Yield the agent run ID and None for transcript_id (handled by backend)
        # Traceloop will automatically create spans for any instrumented operations
        # and our DocentSpanProcessor will add the appropriate metadata
        yield (current_agent_run_id, None)
    finally:
        # Restore context
        _current_agent_run_id.reset(agent_run_token)


@asynccontextmanager
async def _agent_run_context_async(
    agent_run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[tuple[str, Optional[str]]]:
    """Asynchronous context manager for creating and managing agent runs."""
    _ensure_tracing_initialized()

    # Generate IDs if not provided
    current_agent_run_id = agent_run_id or _generate_id()

    # Set up context
    agent_run_token = _set_current_agent_run_id(current_agent_run_id)

    try:
        # Send metadata to API if provided
        if metadata:
            agent_run_metadata(metadata)

        # Yield the agent run ID and None for transcript_id (handled by backend)
        # Traceloop will automatically create spans for any instrumented operations
        # and our DocentSpanProcessor will add the appropriate metadata
        yield (current_agent_run_id, None)
    finally:
        # Restore context
        _current_agent_run_id.reset(agent_run_token)


def agent_run_context(
    agent_run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Context manager for creating and managing agent runs.

    This context manager can be used in both synchronous and asynchronous contexts.
    In async contexts, use it with `async with agent_run_context()`.
    In sync contexts, use it with `with agent_run_context()`.

    Args:
        agent_run_id: Optional agent run ID (auto-generated if not provided)
        metadata: Optional metadata to attach to the agent run

    Returns:
        A context manager that yields a tuple of (agent_run_id, transcript_id)
        where transcript_id is None for now as it's handled by backend
    """
    # Check if we're in an async context by looking at the current frame
    import inspect

    frame = inspect.currentframe()
    try:
        # Look for async context indicators in the call stack
        while frame:
            if frame.f_code.co_flags & 0x80:  # CO_COROUTINE flag
                return _agent_run_context_async(agent_run_id=agent_run_id, metadata=metadata)
            frame = frame.f_back
    finally:
        # Clean up the frame reference
        del frame

    # Default to sync context manager
    return _agent_run_context_sync(agent_run_id=agent_run_id, metadata=metadata)


def agent_run(
    func: Optional[Callable[..., Any]] = None,
    *,
    agent_run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Callable[..., Any]:
    """Decorator for creating agent runs around functions.

    Args:
        func: Function to decorate
        agent_run_id: Optional agent run ID (auto-generated if not provided)
        metadata: Optional metadata to attach to the agent run

    Returns:
        Decorated function
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with _agent_run_context_sync(agent_run_id=agent_run_id, metadata=metadata) as (
                run_id,
                _,
            ):
                result = func(*args, **kwargs)
                # Store agent run ID as an attribute for access
                setattr(sync_wrapper, "docent", type("DocentInfo", (), {"agent_run_id": run_id})())  # type: ignore
                return result

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            async with _agent_run_context_async(agent_run_id=agent_run_id, metadata=metadata) as (
                run_id,
                _,
            ):
                result = await func(*args, **kwargs)
                # Store agent run ID as an attribute for access
                setattr(async_wrapper, "docent", type("DocentInfo", (), {"agent_run_id": run_id})())  # type: ignore
                return result

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    # Handle both @agent_run and @agent_run(agent_run_id=..., metadata=...)
    if func is None:
        return decorator
    else:
        return decorator(func)


# Additional utility functions for better integration


def get_current_agent_run_id() -> Optional[str]:
    """Get the current agent run ID from context.

    Returns:
        The current agent run ID if available, None otherwise
    """
    return _get_current_agent_run_id()


def get_current_collection_id() -> Optional[str]:
    """Get the current collection ID from context.

    Returns:
        The current collection ID if available, None otherwise
    """
    return _get_current_collection_id()


def is_tracing_initialized() -> bool:
    """Check if tracing has been initialized.

    Returns:
        True if tracing is initialized, False otherwise
    """
    return _tracing_initialized


def flush_spans() -> None:
    """Force flush any pending spans to the backend.

    This is useful for ensuring all spans are sent before shutdown
    or for debugging purposes.
    """
    if _tracing_initialized:
        try:
            traceloop_instance = Traceloop.get()
            if hasattr(traceloop_instance, "flush"):
                traceloop_instance.flush()  # type: ignore
            logging.debug("Spans flushed successfully")
        except Exception as e:
            logging.warning(f"Error flushing spans: {e}")
