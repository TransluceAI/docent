import asyncio
import atexit
import contextvars
import inspect
import itertools
import logging
import os
import signal
import sys
import threading
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Union

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.instrumentation.bedrock import BedrockInstrumentor
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Span

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.disabled = True

# Default configuration
DEFAULT_ENDPOINT = "https://api.docent.transluce.org/rest/telemetry"


def _is_async_context() -> bool:
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


def _is_running_in_event_loop() -> bool:
    """Check if we're running in an event loop."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _is_notebook() -> bool:
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
        agent_run_id: Optional[str] = None,
        endpoint: Union[str, List[str]] = DEFAULT_ENDPOINT,
        headers: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
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
            agent_run_id: Optional agent_run_id to use for code outside of an agent run context (auto-generated if not provided)
            endpoint: OTLP endpoint URL(s) - can be a single string or list of strings for multiple endpoints
            headers: Optional headers for authentication
            api_key: Optional API key for bearer token authentication (takes precedence over env var)
            enable_console_export: Whether to export to console
            enable_otlp_export: Whether to export to OTLP endpoint
            disable_batch: Whether to disable batch processing (use SimpleSpanProcessor)
            span_postprocess_callback: Optional callback for post-processing spans
        """
        self.collection_name: str = collection_name
        self.collection_id: str = collection_id if collection_id else str(uuid.uuid4())
        self.default_agent_run_id: str = agent_run_id if agent_run_id else str(uuid.uuid4())
        self.endpoints: List[str]

        # Handle endpoint parameter - convert to list if it's a string
        if isinstance(endpoint, str):
            self.endpoints = [endpoint]
        else:
            self.endpoints = endpoint

        # Build headers with authentication if provided
        self.headers = headers or {}

        # Handle API key authentication (takes precedence over custom headers)
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
            logger.info(f"Using API key authentication for {self.collection_name}")
        elif self.headers.get("Authorization"):
            logger.info(f"Using custom Authorization header for {self.collection_name}")
        else:
            logger.info(f"No authentication configured for {self.collection_name}")

        self.enable_console_export = enable_console_export
        self.enable_otlp_export = enable_otlp_export
        self.disable_batch = disable_batch
        self.span_postprocess_callback = span_postprocess_callback

        # Use separate tracer provider to avoid interfering with existing OTEL setup
        self._tracer_provider: Optional[TracerProvider] = None
        self._root_span: Optional[Span] = None
        self._root_context: Context = Context()
        self._tracer: Optional[trace.Tracer] = None
        self._initialized: bool = False
        self._cleanup_registered: bool = False
        self._disabled: bool = False
        self._spans_processors: List[Union[BatchSpanProcessor, SimpleSpanProcessor]] = []

        # Context variables for agent_run_id and transcript_id (thread/async safe)
        self._collection_id_var: ContextVar[str] = contextvars.ContextVar("docent_collection_id")
        self._agent_run_id_var: ContextVar[str] = contextvars.ContextVar("docent_agent_run_id")
        self._transcript_id_var: ContextVar[str] = contextvars.ContextVar("docent_transcript_id")
        self._attributes_var: ContextVar[dict[str, Any]] = contextvars.ContextVar(
            "docent_attributes"
        )
        # Store atomic span order counters per transcript_id to persist across context switches
        self._transcript_counters: defaultdict[str, itertools.count[int]] = defaultdict(
            lambda: itertools.count(0)
        )
        self._transcript_counter_lock = threading.Lock()

    def get_current_docent_span(self) -> Optional[Span]:
        """
        Get the current span from our isolated context.
        This never touches the global OpenTelemetry context.
        """
        if self._root_context is None:
            return None

        try:
            return trace.get_current_span(context=self._root_context)
        except Exception:
            return None

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

    def _signal_handler(self, signum: int, frame: Optional[object]):
        """Handle shutdown signals."""
        self.cleanup()
        sys.exit(0)

    def _init_spans_exporter(self, endpoint: str) -> Optional[Union[HTTPExporter, GRPCExporter]]:
        """Initialize the appropriate span exporter based on endpoint."""
        if not self.enable_otlp_export:
            return None

        try:
            if "http" in endpoint.lower() or "https" in endpoint.lower():
                http_exporter: HTTPExporter = HTTPExporter(
                    endpoint=f"{endpoint}/v1/traces", headers=self.headers
                )
                return http_exporter
            else:
                grpc_exporter: GRPCExporter = GRPCExporter(endpoint=endpoint, headers=self.headers)
                return grpc_exporter
        except Exception as e:
            logger.error(f"Failed to initialize span exporter for {endpoint}: {e}")
            return None

    def _init_spans_exporters(self) -> List[Union[HTTPExporter, GRPCExporter]]:
        """Initialize span exporters for all endpoints."""
        exporters: List[Union[HTTPExporter, GRPCExporter]] = []

        for endpoint in self.endpoints:
            exporter = self._init_spans_exporter(endpoint)
            if exporter:
                exporters.append(exporter)
                logger.info(f"Initialized exporter for endpoint: {endpoint}")
            else:
                logger.warning(f"Failed to initialize exporter for endpoint: {endpoint}")

        return exporters

    def _create_span_processor(
        self, exporter: Union[HTTPExporter, GRPCExporter, ConsoleSpanExporter]
    ) -> Union[SimpleSpanProcessor, BatchSpanProcessor]:
        """Create appropriate span processor based on configuration."""
        if self.disable_batch or _is_notebook():
            simple_processor: SimpleSpanProcessor = SimpleSpanProcessor(exporter)
            return simple_processor
        else:
            batch_processor: BatchSpanProcessor = BatchSpanProcessor(exporter)
            return batch_processor

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
            class ContextSpanProcessor(SpanProcessor):
                def __init__(self, manager: "DocentTracer"):
                    self.manager: "DocentTracer" = manager

                def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
                    # Add collection_id, agent_run_id, transcript_id, and any other current attributes
                    # Always add collection_id as it's always available
                    span.set_attribute("collection_id", self.manager.collection_id)

                    # Handle agent_run_id
                    try:
                        agent_run_id: str = self.manager._agent_run_id_var.get()
                        if agent_run_id:
                            span.set_attribute("agent_run_id", agent_run_id)
                        else:
                            span.set_attribute("agent_run_id_default", True)
                            span.set_attribute("agent_run_id", self.manager.default_agent_run_id)
                    except LookupError:
                        span.set_attribute("agent_run_id_default", True)
                        span.set_attribute("agent_run_id", self.manager.default_agent_run_id)

                    # Handle transcript_id
                    try:
                        transcript_id: str = self.manager._transcript_id_var.get()
                        if transcript_id:
                            span.set_attribute("transcript_id", transcript_id)
                            # Add atomic span order number
                            span_order: int = self.manager._next_span_order(transcript_id)
                            span.set_attribute("span_order", span_order)
                    except LookupError:
                        # transcript_id not available, skip it
                        pass

                    # Handle attributes
                    try:
                        attributes: dict[str, Any] = self.manager._attributes_var.get()
                        for key, value in attributes.items():
                            span.set_attribute(key, value)
                    except LookupError:
                        # attributes not available, skip them
                        pass

                def on_end(self, span: ReadableSpan) -> None:
                    pass

                def shutdown(self) -> None:
                    pass

                def force_flush(self, timeout_millis: Optional[float] = None) -> bool:
                    return True

            # Configure span exporters for our isolated provider
            if self.enable_otlp_export:
                otlp_exporters: List[Union[HTTPExporter, GRPCExporter]] = (
                    self._init_spans_exporters()
                )

                if otlp_exporters:
                    # Create a processor for each exporter
                    for exporter in otlp_exporters:
                        otlp_processor: Union[SimpleSpanProcessor, BatchSpanProcessor] = (
                            self._create_span_processor(exporter)
                        )
                        self._tracer_provider.add_span_processor(otlp_processor)
                        self._spans_processors.append(otlp_processor)

                    logger.info(
                        f"Added {len(otlp_exporters)} OTLP exporters for {len(self.endpoints)} endpoints"
                    )
                else:
                    logger.warning("Failed to initialize OTLP exporter")

            if self.enable_console_export:
                console_exporter: ConsoleSpanExporter = ConsoleSpanExporter()
                console_processor: Union[SimpleSpanProcessor, BatchSpanProcessor] = (
                    self._create_span_processor(console_exporter)
                )
                self._tracer_provider.add_span_processor(console_processor)
                self._spans_processors.append(console_processor)

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
                },
            )
            self._root_context = trace.set_span_in_context(
                self._root_span, context=self._root_context
            )

            # Instrument threading for better context propagation
            try:
                ThreadingInstrumentor().instrument()
            except Exception as e:
                logger.warning(f"Failed to instrument threading: {e}")

            # Instrument OpenAI with our isolated tracer provider
            try:
                OpenAIInstrumentor().instrument(tracer_provider=self._tracer_provider)
                logger.info("Instrumented OpenAI")
            except Exception as e:
                logger.warning(f"Failed to instrument OpenAI: {e}")

            # Instrument Anthropic with our isolated tracer provider
            try:
                AnthropicInstrumentor().instrument(tracer_provider=self._tracer_provider)
                logger.info("Instrumented Anthropic")
            except Exception as e:
                logger.warning(f"Failed to instrument Anthropic: {e}")

            # Instrument Bedrock with our isolated tracer provider
            try:
                BedrockInstrumentor().instrument(tracer_provider=self._tracer_provider)
                logger.info("Instrumented Bedrock")
            except Exception as e:
                logger.warning(f"Failed to instrument Bedrock: {e}")

            # Instrument LangChain with our isolated tracer provider
            try:
                LangchainInstrumentor().instrument(tracer_provider=self._tracer_provider)
                logger.info("Instrumented LangChain")
            except Exception as e:
                logger.warning(f"Failed to instrument LangChain: {e}")

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
            # Create an explicit end-of-trace span before ending the root span
            if self._tracer and self._root_span:
                end_span = self._tracer.start_span(
                    "trace_end",
                    context=self._root_context,
                    attributes={
                        "event.type": "trace_end",
                    },
                )
                end_span.end()

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
            self._root_context = None  # type: ignore

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

    def flush(self) -> None:
        """Force flush all spans to exporters."""
        try:
            for processor in self._spans_processors:
                if hasattr(processor, "force_flush"):
                    processor.force_flush()
        except Exception as e:
            logger.error(f"Error during flush: {e}")

    def set_disabled(self, disabled: bool) -> None:
        """Enable or disable tracing."""
        self._disabled = disabled
        if disabled and self._initialized:
            self.cleanup()

    def verify_initialized(self) -> bool:
        """Verify if the manager is properly initialized."""
        if self._disabled:
            return False
        return self._initialized

    def __enter__(self) -> "DocentTracer":
        """Context manager entry."""
        self.initialize()
        return self

    def __exit__(self, exc_type: type[BaseException], exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

    @property
    def tracer(self) -> Optional[trace.Tracer]:
        """Get the tracer instance."""
        if not self._initialized:
            self.initialize()
        return self._tracer

    @property
    def root_context(self) -> Optional[Context]:
        """Get the root context."""
        if not self._initialized:
            self.initialize()
        return self._root_context

    @contextmanager
    def span(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> Iterator[Span]:
        """
        Context manager for creating spans with attributes.
        """
        if not self._initialized:
            self.initialize()

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")

        span_attributes: dict[str, Any] = attributes or {}

        with self._tracer.start_as_current_span(
            name, context=self._root_context, attributes=span_attributes
        ) as span:
            yield span

    @asynccontextmanager
    async def async_span(
        self, name: str, attributes: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[Span]:
        """
        Async context manager for creating spans with attributes.

        Args:
            name: Name of the span
            attributes: Dictionary of attributes to add to the span
        """
        if not self._initialized:
            self.initialize()

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")

        span_attributes: dict[str, Any] = attributes or {}

        with self._tracer.start_as_current_span(
            name, context=self._root_context, attributes=span_attributes
        ) as span:
            yield span

    @contextmanager
    def agent_run_context(
        self,
        agent_run_id: Optional[str] = None,
        transcript_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **attributes: Any,
    ) -> Iterator[tuple[str, str]]:
        """
        Context manager for setting up an agent run context.

        Args:
            agent_run_id: Optional agent run ID (auto-generated if not provided)
            transcript_id: Optional transcript ID (auto-generated if not provided)
            metadata: Optional nested dictionary of metadata to attach as events
            **attributes: Additional attributes to add to the context

        Yields:
            Tuple of (agent_run_id, transcript_id)
        """
        if not self._initialized:
            self.initialize()

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")

        if agent_run_id is None:
            agent_run_id = str(uuid.uuid4())
        if transcript_id is None:
            transcript_id = str(uuid.uuid4())

        # Set context variables for this execution context
        agent_run_id_token: Token[str] = self._agent_run_id_var.set(agent_run_id)
        transcript_id_token: Token[str] = self._transcript_id_var.set(transcript_id)
        attributes_token: Token[dict[str, Any]] = self._attributes_var.set(attributes)

        try:
            # Create a span with the agent run attributes
            span_attributes: dict[str, Any] = {
                "agent_run_id": agent_run_id,
                "transcript_id": transcript_id,
                **attributes,
            }
            with self._tracer.start_as_current_span(
                "agent_run_context", context=self._root_context, attributes=span_attributes
            ) as _span:
                # Attach metadata as events if provided
                if metadata:
                    _add_metadata_event_to_span(_span, metadata)

                yield agent_run_id, transcript_id
        finally:
            self._agent_run_id_var.reset(agent_run_id_token)
            self._transcript_id_var.reset(transcript_id_token)
            self._attributes_var.reset(attributes_token)

    @asynccontextmanager
    async def async_agent_run_context(
        self,
        agent_run_id: Optional[str] = None,
        transcript_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **attributes: Any,
    ) -> AsyncIterator[tuple[str, str]]:
        """
        Async context manager for setting up an agent run context.
        Modifies the OpenTelemetry context so all spans inherit agent_run_id and transcript_id.

        Args:
            agent_run_id: Optional agent run ID (auto-generated if not provided)
            transcript_id: Optional transcript ID (auto-generated if not provided)
            metadata: Optional nested dictionary of metadata to attach as events
            **attributes: Additional attributes to add to the context

        Yields:
            Tuple of (agent_run_id, transcript_id)
        """
        if not self._initialized:
            self.initialize()

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")

        if agent_run_id is None:
            agent_run_id = str(uuid.uuid4())
        if transcript_id is None:
            transcript_id = str(uuid.uuid4())

        # Set context variables for this execution context
        agent_run_id_token: Token[str] = self._agent_run_id_var.set(agent_run_id)
        transcript_id_token: Token[str] = self._transcript_id_var.set(transcript_id)
        attributes_token: Token[dict[str, Any]] = self._attributes_var.set(attributes)

        try:
            # Create a span with the agent run attributes
            span_attributes: dict[str, Any] = {
                "agent_run_id": agent_run_id,
                "transcript_id": transcript_id,
                **attributes,
            }
            with self._tracer.start_as_current_span(
                "agent_run_context", context=self._root_context, attributes=span_attributes
            ) as _span:
                # Attach metadata as events if provided
                if metadata:
                    _add_metadata_event_to_span(_span, metadata)

                yield agent_run_id, transcript_id
        finally:
            self._agent_run_id_var.reset(agent_run_id_token)
            self._transcript_id_var.reset(transcript_id_token)
            self._attributes_var.reset(attributes_token)

    def start_transcript(
        self,
        agent_run_id: Optional[str] = None,
        transcript_id: Optional[str] = None,
        **attributes: Any,
    ) -> tuple[Any, str, str]:
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

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")

        if agent_run_id is None:
            agent_run_id = str(uuid.uuid4())
        if transcript_id is None:
            transcript_id = str(uuid.uuid4())

        span_attributes: dict[str, Any] = {
            "agent_run_id": agent_run_id,
            "transcript_id": transcript_id,
            **attributes,
        }

        span: Any = self._tracer.start_span(
            "transcript_span", context=self._root_context, attributes=span_attributes
        )

        return span, agent_run_id, transcript_id

    def stop_transcript(self, span: Span) -> None:
        """
        Manually stop a transcript span.

        Args:
            span: The span to stop
        """
        if span and hasattr(span, "end"):
            span.end()

    def start_span(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> Span:
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

        if self._tracer is None:
            raise RuntimeError("Tracer not initialized")

        span_attributes: dict[str, Any] = attributes or {}

        span: Span = self._tracer.start_span(
            name, context=self._root_context, attributes=span_attributes
        )

        return span

    def stop_span(self, span: Span) -> None:
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
    endpoint: Union[str, List[str]] = DEFAULT_ENDPOINT,
    headers: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None,
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
        collection_name: Name of the collection
        collection_id: Optional collection ID (auto-generated if not provided)
        endpoint: OTLP endpoint URL(s) for span export - can be a single string or list of strings for multiple endpoints
        headers: Optional headers for authentication
        api_key: Optional API key for bearer token authentication (takes precedence over env var)
        enable_console_export: Whether to export spans to console
        enable_otlp_export: Whether to export spans to OTLP endpoint
        disable_batch: Whether to disable batch processing (use SimpleSpanProcessor)
        span_postprocess_callback: Optional callback for post-processing spans

    Returns:
        The initialized Docent tracer

    Example:
        # Basic setup
        initialize_tracing("my-collection")
    """
    global _global_tracer

    # Check for API key in environment variable if not provided as parameter
    if api_key is None:
        env_api_key: Optional[str] = os.environ.get("DOCENT_API_KEY")
        api_key = env_api_key

    if _global_tracer is None:
        _global_tracer = DocentTracer(
            collection_name=collection_name,
            collection_id=collection_id,
            endpoint=endpoint,
            headers=headers,
            api_key=api_key,
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


def close_tracing() -> None:
    """Close the global Docent tracer."""
    global _global_tracer
    if _global_tracer:
        _global_tracer.close()
        _global_tracer = None


def flush_tracing() -> None:
    """Force flush all spans to exporters."""
    if _global_tracer:
        _global_tracer.flush()


def verify_initialized() -> bool:
    """Verify if the global Docent tracer is properly initialized."""
    if _global_tracer is None:
        return False
    return _global_tracer.verify_initialized()


def set_disabled(disabled: bool) -> None:
    """Enable or disable global tracing."""
    if _global_tracer:
        _global_tracer.set_disabled(disabled)


def get_api_key() -> Optional[str]:
    """
    Get the API key from environment variable.

    Returns:
        The API key from DOCENT_API_KEY environment variable, or None if not set
    """
    return os.environ.get("DOCENT_API_KEY")


def agent_run_score(name: str, score: float, attributes: Optional[Dict[str, Any]] = None) -> None:
    """
    Record a score event on the current span.
    Automatically works in both sync and async contexts.

    Args:
        name: Name of the score metric
        score: Numeric score value
        attributes: Optional additional attributes for the score event
    """
    try:
        # Get current span from our isolated context instead of global context
        current_span: Optional[Span] = get_tracer().get_current_docent_span()
        if current_span and hasattr(current_span, "add_event"):
            event_attributes: dict[str, Any] = {
                "score.name": name,
                "score.value": score,
                "event.type": "score",
            }
            if attributes:
                event_attributes.update(attributes)

            current_span.add_event(name="agent_run_score", attributes=event_attributes)
        else:
            logger.warning("No current span available for recording score")
    except Exception as e:
        logger.error(f"Failed to record score event: {e}")


def _flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten nested dictionary with dot notation."""
    flattened: Dict[str, Any] = {}
    for key, value in d.items():
        new_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flattened.update(_flatten_dict(dict(value), new_key))  # type: ignore
        else:
            flattened[new_key] = value
    return flattened


def _add_metadata_event_to_span(span: Span, metadata: Dict[str, Any]) -> None:
    """
    Add metadata as an event to a span.

    Args:
        span: The span to add the event to
        metadata: Dictionary of metadata (can be nested)
    """
    if span and hasattr(span, "add_event"):
        event_attributes: dict[str, Any] = {
            "event.type": "metadata",
        }

        # Flatten nested metadata and add as event attributes
        flattened_metadata = _flatten_dict(metadata)
        for key, value in flattened_metadata.items():
            event_attributes[f"metadata.{key}"] = value
        span.add_event(name="agent_run_metadata", attributes=event_attributes)


def agent_run_metadata(metadata: Dict[str, Any]) -> None:
    """
    Record metadata as an event on the current span.
    Automatically works in both sync and async contexts.
    Supports nested dictionaries by flattening them with dot notation.

    Args:
        metadata: Dictionary of metadata to attach to the current span (can be nested)

    Example:
        agent_run_metadata({"user": "John", "id": 123, "flagged": True})
        agent_run_metadata({"user": {"id": "123", "name": "John"}, "config": {"model": "gpt-4"}})
    """
    try:
        current_span: Optional[Span] = get_tracer().get_current_docent_span()
        if current_span:
            _add_metadata_event_to_span(current_span, metadata)
        else:
            logger.warning("No current span available for recording metadata")
    except Exception as e:
        logger.error(f"Failed to record metadata event: {e}")


# Unified functions that automatically detect context
@asynccontextmanager
async def span(name: str, attributes: Optional[Dict[str, Any]] = None) -> AsyncIterator[Span]:
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


class AgentRunContext:
    """Context manager that works in both sync and async contexts."""

    def __init__(
        self,
        agent_run_id: Optional[str] = None,
        transcript_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **attributes: Any,
    ):
        self.agent_run_id = agent_run_id
        self.transcript_id = transcript_id
        self.metadata = metadata
        self.attributes: dict[str, Any] = attributes
        self._sync_context: Optional[Any] = None
        self._async_context: Optional[Any] = None

    def __enter__(self) -> tuple[str, str]:
        """Sync context manager entry."""
        self._sync_context = get_tracer().agent_run_context(
            self.agent_run_id, self.transcript_id, metadata=self.metadata, **self.attributes
        )
        return self._sync_context.__enter__()

    def __exit__(self, exc_type: type[BaseException], exc_val: Any, exc_tb: Any) -> None:
        """Sync context manager exit."""
        if self._sync_context:
            self._sync_context.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> tuple[str, str]:
        """Async context manager entry."""
        self._async_context = get_tracer().async_agent_run_context(
            self.agent_run_id, self.transcript_id, metadata=self.metadata, **self.attributes
        )
        return await self._async_context.__aenter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._async_context:
            await self._async_context.__aexit__(exc_type, exc_val, exc_tb)


def agent_run(
    func: Optional[Callable[..., Any]] = None, *, metadata: Optional[Dict[str, Any]] = None
):
    """
    Decorator to wrap a function in an agent_run_context (sync or async).
    Injects agent_run_id and transcript_id as function attributes.
    Optionally accepts metadata to attach to the agent run context.

    Example:
        @agent_run
        def my_func(x, y):
            print(my_func.docent.agent_run_id, my_func.docent.transcript_id)

        @agent_run(metadata={"user": "John", "model": "gpt-4"})
        def my_func_with_metadata(x, y):
            print(my_func_with_metadata.docent.agent_run_id)

        @agent_run(metadata={"config": {"model": "gpt-4", "temperature": 0.7}})
        async def my_async_func(z):
            print(my_async_func.docent.agent_run_id)
    """
    import functools
    import inspect

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(f):

            @functools.wraps(f)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                async with AgentRunContext(metadata=metadata) as (agent_run_id, transcript_id):
                    # Store docent data as function attributes
                    setattr(
                        async_wrapper,
                        "docent",
                        type(
                            "DocentData",
                            (),
                            {
                                "agent_run_id": agent_run_id,
                                "transcript_id": transcript_id,
                            },
                        )(),
                    )
                    return await f(*args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(f)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with AgentRunContext(metadata=metadata) as (agent_run_id, transcript_id):
                    # Store docent data as function attributes
                    setattr(
                        sync_wrapper,
                        "docent",
                        type(
                            "DocentData",
                            (),
                            {
                                "agent_run_id": agent_run_id,
                                "transcript_id": transcript_id,
                            },
                        )(),
                    )
                    return f(*args, **kwargs)

            return sync_wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)


def agent_run_context(
    agent_run_id: Optional[str] = None,
    transcript_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **attributes: Any,
) -> AgentRunContext:
    """
    Create an agent run context for tracing.

    Args:
        agent_run_id: Optional agent run ID (auto-generated if not provided)
        transcript_id: Optional transcript ID (auto-generated if not provided)
        metadata: Optional nested dictionary of metadata to attach as events
        **attributes: Additional attributes to add to the context

    Returns:
        A context manager that can be used with both 'with' and 'async with'

    Example:
        # Sync usage
        with agent_run_context() as (agent_run_id, transcript_id):
            pass

        # Async usage
        async with agent_run_context() as (agent_run_id, transcript_id):
            pass

        # With metadata
        with agent_run_context(metadata={"user": "John", "model": "gpt-4"}) as (agent_run_id, transcript_id):
            pass
    """
    return AgentRunContext(agent_run_id, transcript_id, metadata=metadata, **attributes)
