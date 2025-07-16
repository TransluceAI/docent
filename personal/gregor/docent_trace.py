import asyncio
import atexit
import contextvars
import inspect
import itertools
import logging
import signal
import sys
import threading
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Callable, Dict, Optional, Union

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _is_async_context():
    """Detect if we're in an async context."""
    try:
        # Check if we're in an async function
        frame = inspect.currentframe()
        while frame:
            if frame.f_code.co_flags & inspect.CO_COROUTINE:
                return True
            frame = frame.f_back
        return False
    except:
        return False


def _is_running_in_event_loop():
    """Check if we're running in an event loop."""
    try:
        return asyncio.get_running_loop() is not None
    except RuntimeError:
        return False


def _is_notebook():
    """Check if we're running in a Jupyter notebook."""
    try:
        return "ipykernel" in sys.modules
    except:
        return False


class DocentTracer:
    """Manages Docent tracing setup and provides tracing utilities."""

    def __init__(
        self,
        collection_name: str = "default-collection-name",
        collection_id: Optional[str] = None,
        endpoint: str = "http://localhost:4318",
        headers: Optional[Dict[str, str]] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        enable_console_export: bool = False,
        enable_otlp_export: bool = True,
        disable_batch: bool = False,
        span_postprocess_callback: Optional[Callable[[ReadableSpan], None]] = None,
    ):
        """
        Initialize Docent tracing manager.

        Args:
            collection_name: Name of the collection for resource attributes
            collection_id: Optional collection ID (auto-generated if not provided)
            endpoint: OTLP endpoint URL
            headers: Optional headers for authentication
            email: Optional email for basic authentication
            password: Optional password for basic authentication
            enable_console_export: Whether to export to console
            enable_otlp_export: Whether to export to OTLP endpoint
            disable_batch: Whether to disable batch processing (use SimpleSpanProcessor)
            span_postprocess_callback: Optional callback for post-processing spans
        """
        self.collection_name = collection_name
        self.collection_id = collection_id if collection_id else str(uuid.uuid4())
        self.endpoint = endpoint
        self.email = email
        self.password = password

        # Build headers with authentication if provided
        self.headers = headers or {}
        if email and password:
            # Add basic auth header
            import base64

            auth_string = f"{email}:{password}"
            auth_bytes = auth_string.encode("ascii")
            auth_b64 = base64.b64encode(auth_bytes).decode("ascii")
            self.headers["Authorization"] = f"Basic {auth_b64}"

        self.enable_console_export = enable_console_export
        self.enable_otlp_export = enable_otlp_export
        self.disable_batch = disable_batch
        self.span_postprocess_callback = span_postprocess_callback

        # Use separate tracer provider to avoid interfering with existing OTEL setup
        self._tracer_provider = None
        self._root_span = None
        self._root_context = None
        self._tracer = None
        self._initialized = False
        self._cleanup_registered = False
        self._disabled = False

        # Context variables for agent_run_id and transcript_id (thread/async safe)
        self._collection_id_var = contextvars.ContextVar("collection_id")
        self._agent_run_id_var = contextvars.ContextVar("agent_run_id")
        self._transcript_id_var = contextvars.ContextVar("transcript_id")
        self._attributes_var = contextvars.ContextVar("attributes")
        # Store atomic span order counters per transcript_id to persist across context switches
        self._transcript_counters = defaultdict(lambda: itertools.count(0))
        self._transcript_counter_lock = threading.Lock()

    def _register_cleanup(self):
        """Register cleanup handlers."""
        if self._cleanup_registered:
            return

        # Register atexit handler
        atexit.register(self.cleanup)

        # Register signal handlers for graceful shutdown
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (ValueError, OSError):
            # Signal handlers might not work in all environments
            pass

        self._cleanup_registered = True

    def _next_span_order(self, transcript_id: str) -> int:
        """
        Get the next atomic span order for a given transcript_id.
        Thread-safe and guaranteed to be unique and monotonic.
        """
        with self._transcript_counter_lock:
            return next(self._transcript_counters[transcript_id])

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.cleanup()
        sys.exit(0)

    def _init_spans_exporter(self) -> Optional[Union[HTTPExporter, GRPCExporter]]:
        """Initialize the appropriate span exporter based on endpoint."""
        if not self.enable_otlp_export:
            return None

        try:
            if "http" in self.endpoint.lower() or "https" in self.endpoint.lower():
                return HTTPExporter(endpoint=f"{self.endpoint}/v1/traces", headers=self.headers)
            else:
                return GRPCExporter(endpoint=self.endpoint, headers=self.headers)
        except Exception as e:
            logger.error(f"Failed to initialize span exporter: {e}")
            return None

    def _create_span_processor(self, exporter):
        """Create appropriate span processor based on configuration."""
        if self.disable_batch or _is_notebook():
            processor = SimpleSpanProcessor(exporter)
        else:
            processor = BatchSpanProcessor(exporter)

        # Add post-processing callback if provided
        if self.span_postprocess_callback:
            original_on_end = processor.on_end

            def wrapped_on_end(span):
                # Call the custom on_end first
                self.span_postprocess_callback(span)
                # Then call the original to ensure normal processing
                original_on_end(span)

            processor.on_end = wrapped_on_end

        return processor

    def initialize(self):
        """Initialize Docent tracing setup."""
        if self._initialized or self._disabled:
            return

        try:
            # Create our own isolated tracer provider
            self._tracer_provider = TracerProvider(
                resource=Resource.create({"service.name": self.collection_name})
            )

            # Add custom span processor for run_id and transcript_id
            class ContextSpanProcessor:
                def __init__(self, manager):
                    self.manager = manager

                def on_start(self, span, parent_context=None):
                    # Add collection_id, agent_run_id, transcript_id, and any other current attributes
                    try:
                        span.set_attribute("collection_id", self.manager.collection_id)

                        agent_run_id = self.manager._agent_run_id_var.get()
                        if agent_run_id:
                            span.set_attribute("agent_run_id", agent_run_id)

                        transcript_id = self.manager._transcript_id_var.get()
                        if transcript_id:
                            span.set_attribute("transcript_id", transcript_id)
                            # Add atomic span order number
                            span_order = self.manager._next_span_order(transcript_id)
                            span.set_attribute("span_order", span_order)

                        # Add any other current attributes
                        attributes = self.manager._attributes_var.get()
                        for key, value in attributes.items():
                            span.set_attribute(key, value)
                    except LookupError:
                        # Still add collection_id as it's always available
                        span.set_attribute("collection_id", self.manager.collection_id)

                def on_end(self, span):
                    pass

                def shutdown(self):
                    pass

                def force_flush(self):
                    pass

            # Configure span exporters for our isolated provider
            if self.enable_otlp_export:
                exporter = self._init_spans_exporter()
                if exporter:
                    processor = self._create_span_processor(exporter)
                    self._tracer_provider.add_span_processor(processor)
                    self._spans_processor = processor
                else:
                    logger.warning(
                        "Failed to initialize OTLP exporter, falling back to console only"
                    )

            if self.enable_console_export:
                console_exporter = ConsoleSpanExporter()
                console_processor = self._create_span_processor(console_exporter)
                self._tracer_provider.add_span_processor(console_processor)
                if not hasattr(self, "_spans_processor"):
                    self._spans_processor = console_processor

            # Add our custom context span processor
            context_processor = ContextSpanProcessor(self)
            self._tracer_provider.add_span_processor(context_processor)

            # Get tracer from our isolated provider (don't set global provider)
            self._tracer = self._tracer_provider.get_tracer(__name__)

            # Start root span
            self._root_span = self._tracer.start_span(
                "application_session",
                attributes={
                    "service.name": self.collection_name,
                    "session.type": "application_root",
                    "endpoint": self.endpoint,
                },
            )
            self._root_context = trace.set_span_in_context(self._root_span)

            # Instrument OpenAI with our isolated tracer provider
            try:
                OpenAIInstrumentor().instrument(tracer_provider=self._tracer_provider)
            except Exception as e:
                logger.warning(f"Failed to instrument OpenAI: {e}")

            # Instrument threading for better context propagation
            try:
                ThreadingInstrumentor().instrument()
            except Exception as e:
                logger.warning(f"Failed to instrument threading: {e}")

            # Register cleanup handlers
            self._register_cleanup()

            self._initialized = True
            logger.info(f"Docent tracing initialized for {self.collection_name}")

        except Exception as e:
            logger.error(f"Failed to initialize Docent tracing: {e}")
            self._disabled = True
            raise

    def cleanup(self):
        """Clean up Docent tracing resources."""
        try:
            if (
                self._root_span
                and hasattr(self._root_span, "is_recording")
                and self._root_span.is_recording()
            ):
                self._root_span.end()
            elif self._root_span:
                # Fallback if is_recording is not available
                self._root_span.end()

            self._root_span = None
            self._root_context = None

            # Shutdown our isolated tracer provider
            if self._tracer_provider:
                self._tracer_provider.shutdown()
                self._tracer_provider = None
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def close(self):
        """Explicitly close the Docent tracing manager."""
        try:
            self.cleanup()
            if self._cleanup_registered:
                atexit.unregister(self.cleanup)
                self._cleanup_registered = False
        except Exception as e:
            logger.error(f"Error during close: {e}")

    def flush(self):
        """Force flush all spans to exporters."""
        try:
            if hasattr(self, "_spans_processor") and self._spans_processor:
                self._spans_processor.force_flush()
        except Exception as e:
            logger.error(f"Error during flush: {e}")

    def set_disabled(self, disabled: bool):
        """Enable or disable tracing."""
        self._disabled = disabled
        if disabled and self._initialized:
            self.cleanup()

    def verify_initialized(self) -> bool:
        """Verify if the manager is properly initialized."""
        if self._disabled:
            return False
        return self._initialized

    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    @property
    def tracer(self):
        """Get the tracer instance."""
        if not self._initialized:
            self.initialize()
        return self._tracer

    @property
    def root_context(self):
        """Get the root context."""
        if not self._initialized:
            self.initialize()
        return self._root_context

    @contextmanager
    def span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """
        Context manager for creating spans with attributes.

        Args:
            name: Name of the span
            attributes: Dictionary of attributes to add to the span
        """
        if not self._initialized:
            self.initialize()

        span_attributes = attributes or {}

        with self._tracer.start_as_current_span(
            name, context=self._root_context, attributes=span_attributes
        ) as span:
            yield span

    @asynccontextmanager
    async def async_span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """
        Async context manager for creating spans with attributes.

        Args:
            name: Name of the span
            attributes: Dictionary of attributes to add to the span
        """
        if not self._initialized:
            self.initialize()

        span_attributes = attributes or {}

        with self._tracer.start_as_current_span(
            name, context=self._root_context, attributes=span_attributes
        ) as span:
            yield span

    @contextmanager
    def transcript_context(
        self, agent_run_id: Optional[str] = None, transcript_id: Optional[str] = None, **attributes
    ):
        """
        Context manager for setting up a transcript context.
        Modifies the OpenTelemetry context so all spans inherit agent_run_id and transcript_id.

        Args:
            agent_run_id: Optional agent run ID (auto-generated if not provided)
            transcript_id: Optional transcript ID (auto-generated if not provided)
            **attributes: Additional attributes to add to the context

        Yields:
            Tuple of (context, agent_run_id, transcript_id)
        """
        if not self._initialized:
            self.initialize()

        if agent_run_id is None:
            agent_run_id = str(uuid.uuid4())
        if transcript_id is None:
            transcript_id = str(uuid.uuid4())

        # Set context variables for this execution context
        token1 = self._agent_run_id_var.set(agent_run_id)
        token2 = self._transcript_id_var.set(transcript_id)
        token3 = self._attributes_var.set(attributes)

        try:
            # Create a span with the transcript attributes
            span_attributes = {
                "agent_run_id": agent_run_id,
                "transcript_id": transcript_id,
                **attributes,
            }
            with self._tracer.start_as_current_span(
                "transcript_context", context=self._root_context, attributes=span_attributes
            ) as span:
                context = trace.get_current_span().get_span_context()
                yield context, agent_run_id, transcript_id
        finally:
            self._agent_run_id_var.reset(token1)
            self._transcript_id_var.reset(token2)
            self._attributes_var.reset(token3)

    @asynccontextmanager
    async def async_transcript_context(
        self, agent_run_id: Optional[str] = None, transcript_id: Optional[str] = None, **attributes
    ):
        """
        Async context manager for setting up a transcript context.
        Modifies the OpenTelemetry context so all spans inherit agent_run_id and transcript_id.

        Args:
            agent_run_id: Optional agent run ID (auto-generated if not provided)
            transcript_id: Optional transcript ID (auto-generated if not provided)
            **attributes: Additional attributes to add to the context

        Yields:
            Tuple of (context, agent_run_id, transcript_id)
        """
        if not self._initialized:
            self.initialize()

        if agent_run_id is None:
            agent_run_id = str(uuid.uuid4())
        if transcript_id is None:
            transcript_id = str(uuid.uuid4())

        # Set context variables for this execution context
        token1 = self._agent_run_id_var.set(agent_run_id)
        token2 = self._transcript_id_var.set(transcript_id)
        token3 = self._attributes_var.set(attributes)

        try:
            # Create a span with the transcript attributes
            span_attributes = {
                "agent_run_id": agent_run_id,
                "transcript_id": transcript_id,
                **attributes,
            }
            with self._tracer.start_as_current_span(
                "transcript_context", context=self._root_context, attributes=span_attributes
            ) as span:
                context = trace.get_current_span().get_span_context()
                yield context, agent_run_id, transcript_id
        finally:
            self._agent_run_id_var.reset(token1)
            self._transcript_id_var.reset(token2)
            self._attributes_var.reset(token3)

    def start_transcript(
        self, agent_run_id: Optional[str] = None, transcript_id: Optional[str] = None, **attributes
    ):
        """
        Manually start a transcript span.

        Args:
            agent_run_id: Optional agent run ID (auto-generated if not provided)
            transcript_id: Optional transcript ID (auto-generated if not provided)
            **attributes: Additional attributes to add to the span

        Returns:
            Tuple of (span, agent_run_id, transcript_id)
        """
        if not self._initialized:
            self.initialize()

        if agent_run_id is None:
            agent_run_id = str(uuid.uuid4())
        if transcript_id is None:
            transcript_id = str(uuid.uuid4())

        span_attributes = {
            "agent_run_id": agent_run_id,
            "transcript_id": transcript_id,
            **attributes,
        }

        span = self._tracer.start_span(
            "transcript_span", context=self._root_context, attributes=span_attributes
        )

        return span, agent_run_id, transcript_id

    def stop_transcript(self, span):
        """
        Manually stop a transcript span.

        Args:
            span: The span to stop
        """
        if span and hasattr(span, "end"):
            span.end()

    def start_span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """
        Manually start a span.

        Args:
            name: Name of the span
            attributes: Dictionary of attributes to add to the span

        Returns:
            The created span
        """
        if not self._initialized:
            self.initialize()

        span_attributes = attributes or {}

        span = self._tracer.start_span(name, context=self._root_context, attributes=span_attributes)

        return span

    def stop_span(self, span):
        """
        Manually stop a span.

        Args:
            span: The span to stop
        """
        if span and hasattr(span, "end"):
            span.end()


# Global instance for easy access
_global_tracer: Optional[DocentTracer] = None


def initialize_tracing(
    collection_name: str = "default-service",
    collection_id: Optional[str] = None,
    endpoint: str = "http://localhost:4318",
    headers: Optional[Dict[str, str]] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    enable_console_export: bool = False,
    enable_otlp_export: bool = True,
    disable_batch: bool = False,
    span_postprocess_callback: Optional[Callable[[ReadableSpan], None]] = None,
) -> DocentTracer:
    """
    Initialize the global Docent tracer.

    This is the primary entry point for setting up Docent tracing.
    It creates a global singleton instance that can be accessed via get_tracer().

    Args:
        collection_name: Name of the service/collection for resource attributes
        collection_id: Optional collection ID (auto-generated if not provided)
        endpoint: OTLP endpoint URL for span export
        headers: Optional headers for authentication
        email: Optional email for basic authentication
        password: Optional password for basic authentication
        enable_console_export: Whether to export spans to console
        enable_otlp_export: Whether to export spans to OTLP endpoint
        disable_batch: Whether to disable batch processing (use SimpleSpanProcessor)
        span_postprocess_callback: Optional callback for post-processing spans

    Returns:
        The initialized Docent tracer

    Example:
        # Basic setup
        initialize_tracing("my-service")

        # With authentication
        initialize_tracing(
            collection_name="my-service",
            endpoint="https://my-collector.com:4318",
            email="user@example.com",
            password="secret"
        )
    """
    global _global_tracer

    if _global_tracer is None:
        _global_tracer = DocentTracer(
            collection_name=collection_name,
            collection_id=collection_id,
            endpoint=endpoint,
            headers=headers,
            email=email,
            password=password,
            enable_console_export=enable_console_export,
            enable_otlp_export=enable_otlp_export,
            disable_batch=disable_batch,
            span_postprocess_callback=span_postprocess_callback,
        )
        _global_tracer.initialize()
    else:
        # If already initialized, ensure it's properly set up
        _global_tracer.initialize()

    return _global_tracer


def get_tracer() -> DocentTracer:
    """Get the global Docent tracer."""
    if _global_tracer is None:
        # Auto-initialize with defaults if not already done
        return initialize_tracing()
    return _global_tracer


def close_tracing():
    """Close the global Docent tracer."""
    global _global_tracer
    if _global_tracer:
        _global_tracer.close()
        _global_tracer = None


def flush_tracing():
    """Force flush all spans to exporters."""
    if _global_tracer:
        _global_tracer.flush()


def verify_initialized() -> bool:
    """Verify if the global Docent tracer is properly initialized."""
    if _global_tracer is None:
        return False
    return _global_tracer.verify_initialized()


def set_disabled(disabled: bool):
    """Enable or disable global tracing."""
    if _global_tracer:
        _global_tracer.set_disabled(disabled)


# Async convenience functions
@asynccontextmanager
async def async_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Async convenience function for creating spans."""
    async with get_tracer().async_span(name, attributes) as span:
        yield span


@asynccontextmanager
async def async_transcript_context(
    agent_run_id: Optional[str] = None, transcript_id: Optional[str] = None, **attributes
):
    """Async convenience function for creating transcript contexts."""
    async with get_tracer().async_transcript_context(agent_run_id, transcript_id, **attributes) as (
        context,
        agent_run_id,
        transcript_id,
    ):
        yield context, agent_run_id, transcript_id


# Manual start/stop convenience functions
def start_transcript(
    agent_run_id: Optional[str] = None, transcript_id: Optional[str] = None, **attributes
):
    """Convenience function for manually starting a transcript span."""
    return get_tracer().start_transcript(agent_run_id, transcript_id, **attributes)


def stop_transcript(span):
    """Convenience function for manually stopping a transcript span."""
    get_tracer().stop_transcript(span)


def start_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Convenience function for manually starting a span."""
    return get_tracer().start_span(name, attributes)


def stop_span(span):
    """Convenience function for manually stopping a span."""
    get_tracer().stop_span(span)


def agent_run_score(name: str, score: float, attributes: Optional[Dict[str, Any]] = None):
    """
    Record a score event on the current span.
    Automatically works in both sync and async contexts.

    Args:
        name: Name of the score metric
        score: Numeric score value
        attributes: Optional additional attributes for the score event
    """
    try:
        current_span = trace.get_current_span()
        if current_span and hasattr(current_span, "add_event"):
            event_attributes = {"score.name": name, "score.value": score, "event.type": "score"}
            if attributes:
                event_attributes.update(attributes)

            current_span.add_event(name="agent_run_score", attributes=event_attributes)
        else:
            logger.warning("No current span available for recording score")
    except Exception as e:
        logger.error(f"Failed to record score event: {e}")


# Unified functions that automatically detect context
@asynccontextmanager
async def span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Automatically choose sync or async span based on context.
    Can be used with both 'with' and 'async with'.
    """
    if _is_async_context() or _is_running_in_event_loop():
        async with get_tracer().async_span(name, attributes) as span:
            yield span
    else:
        with get_tracer().span(name, attributes) as span:
            yield span


@asynccontextmanager
async def transcript_context(
    agent_run_id: Optional[str] = None, transcript_id: Optional[str] = None, **attributes
):
    """
    Automatically choose sync or async transcript_context based on context.
    Can be used with both 'with' and 'async with'.
    """
    if _is_async_context() or _is_running_in_event_loop():
        async with get_tracer().async_transcript_context(
            agent_run_id, transcript_id, **attributes
        ) as (context, agent_run_id, transcript_id):
            yield context, agent_run_id, transcript_id
    else:
        with get_tracer().transcript_context(agent_run_id, transcript_id, **attributes) as (
            context,
            agent_run_id,
            transcript_id,
        ):
            yield context, agent_run_id, transcript_id
