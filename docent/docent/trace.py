# pyright: reportUnnecessaryIsInstance=false

import atexit
import contextvars
import itertools
import json
import os
import sys
import threading
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from enum import Enum
from importlib.metadata import Distribution, distributions
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Union,
    cast,
)

import requests
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanLimits, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Span
from requests import Response

from docent._log_util import get_logger

logger = get_logger(__name__)

# Default configuration
DEFAULT_ENDPOINT = "https://api.docent.transluce.org/rest/telemetry"
DEFAULT_COLLECTION_NAME = "default-collection-name"
ERROR_DETAIL_MAX_CHARS = 500

# Sentinel values for when tracing is disabled
DISABLED_AGENT_RUN_ID = "disabled"
DISABLED_TRANSCRIPT_ID = "disabled"
DISABLED_TRANSCRIPT_GROUP_ID = "disabled"


def _get_disabled_agent_run_id(agent_run_id: Optional[str]) -> str:
    """Return sentinel value for agent run ID when tracing is disabled."""
    if agent_run_id is None:
        return DISABLED_AGENT_RUN_ID
    return agent_run_id


def _get_disabled_transcript_id(transcript_id: Optional[str]) -> str:
    """Return sentinel value for transcript ID when tracing is disabled."""
    if transcript_id is None:
        return DISABLED_TRANSCRIPT_ID
    return transcript_id


def _get_disabled_transcript_group_id(transcript_group_id: Optional[str]) -> str:
    """Return sentinel value for transcript group ID when tracing is disabled."""
    if transcript_group_id is None:
        return DISABLED_TRANSCRIPT_GROUP_ID
    return transcript_group_id


class DocentTelemetryRequestError(RuntimeError):
    """Raised when the Docent telemetry backend rejects a client request."""


class Instruments(Enum):
    """Enumeration of available instrument types."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    LANGCHAIN = "langchain"
    GOOGLE_GENERATIVEAI = "google_generativeai"


class DocentTracer:
    """
    Manages Docent tracing setup and provides tracing utilities.
    """

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        collection_id: Optional[str] = None,
        agent_run_id: Optional[str] = None,
        endpoint: Union[str, List[str]] = DEFAULT_ENDPOINT,
        headers: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        enable_console_export: bool = False,
        enable_otlp_export: bool = True,
        disable_batch: bool = False,
        instruments: Optional[Set[Instruments]] = None,
        block_instruments: Optional[Set[Instruments]] = None,
    ):
        self._initialized: bool = False
        # Check if tracing is disabled via environment variable
        if _global_tracing_disabled:
            self._disabled = True
            logger.info("Docent tracing disabled.")
            return

        if not isinstance(collection_name, str) or not collection_name:
            logger.error(
                "collection_name must be provided as a non-empty string (got %r); defaulting to %s.",
                collection_name,
                DEFAULT_COLLECTION_NAME,
            )
            self.collection_name = DEFAULT_COLLECTION_NAME
        else:
            self.collection_name = collection_name

        if collection_id is not None:
            if isinstance(collection_id, str) and collection_id:
                self.collection_id = collection_id
            else:
                logger.error(
                    "collection_id must be provided as a non-empty string (got %r); generating a new ID.",
                    collection_id,
                )
                self.collection_id = str(uuid.uuid4())
        else:
            self.collection_id = str(uuid.uuid4())

        if agent_run_id is not None:
            if isinstance(agent_run_id, str) and agent_run_id:
                self.default_agent_run_id = agent_run_id
            else:
                logger.error(
                    "default agent_run_id must be a non-empty string (got %r); generating a new ID.",
                    agent_run_id,
                )
                self.default_agent_run_id = str(uuid.uuid4())
        else:
            self.default_agent_run_id = str(uuid.uuid4())
        self.endpoints: List[str] = self._prepare_endpoints(endpoint)

        # Build headers with authentication if provided
        if headers is None:
            self.headers: Dict[str, str] = {}
        elif not isinstance(headers, dict):
            logger.error(
                "HTTP headers for Docent tracing must be provided as a dict (got %r).",
                headers,
            )
            self.headers = {}
        else:
            sanitized_headers: Dict[str, str] = {}
            for header_key, header_value in headers.items():
                if not isinstance(header_key, str):
                    logger.error(
                        "HTTP header keys must be strings; skipping key %r of type %s.",
                        header_key,
                        type(header_key).__name__,
                    )
                    continue
                if not isinstance(header_value, str):
                    logger.error(
                        "HTTP header values must be strings; skipping '%s' value of type %s.",
                        header_key,
                        type(header_value).__name__,
                    )
                    continue
                sanitized_headers[header_key] = header_value
            self.headers = sanitized_headers

        # Handle API key authentication (takes precedence over custom headers)
        if api_key is not None:
            if isinstance(api_key, str) and api_key:
                self.headers["Authorization"] = f"Bearer {api_key}"
            else:
                logger.error(
                    "api_key must be a non-empty string (got %r); ignoring value.", api_key
                )

        if self.headers.get("Authorization"):
            logger.info(f"Using API key authentication for {self.collection_name}")
        else:
            logger.info(f"No authentication configured for {self.collection_name}")

        self.enable_console_export = enable_console_export
        self.enable_otlp_export = enable_otlp_export
        self.disable_batch = disable_batch
        self.disabled_instruments: Set[Instruments] = {Instruments.LANGCHAIN}
        self.instruments = instruments or (set(Instruments) - self.disabled_instruments)
        self.block_instruments = block_instruments or set()

        # Use separate tracer provider to avoid interfering with existing OTEL setup
        self._tracer_provider: Optional[TracerProvider] = None
        self._root_context: Optional[Context] = Context()
        self._tracer: Optional[trace.Tracer] = None
        self._cleanup_registered: bool = False
        self._disabled: bool = False
        self._spans_processors: List[Union[BatchSpanProcessor, SimpleSpanProcessor]] = []

        # Base HTTP endpoint for direct API calls (scores, metadata, trace-done)
        if len(self.endpoints) > 0:
            self._api_endpoint_base: Optional[str] = self.endpoints[0]

        # Context variables for agent_run_id and transcript_id
        self._collection_id_var: ContextVar[str] = contextvars.ContextVar("docent_collection_id")
        self._agent_run_id_var: ContextVar[str] = contextvars.ContextVar("docent_agent_run_id")
        self._transcript_id_var: ContextVar[str] = contextvars.ContextVar("docent_transcript_id")
        self._transcript_group_id_var: ContextVar[str] = contextvars.ContextVar(
            "docent_transcript_group_id"
        )
        self._attributes_var: ContextVar[dict[str, Any]] = contextvars.ContextVar(
            "docent_attributes"
        )
        # Store atomic span order counters per transcript_id to persist across context switches
        self._transcript_counters: defaultdict[str, itertools.count[int]] = defaultdict(
            lambda: itertools.count(0)
        )
        self._transcript_counter_lock = threading.Lock()
        self._transcript_group_states: dict[str, dict[str, Optional[str]]] = {}
        self._transcript_group_state_lock = threading.Lock()
        self._flush_lock = threading.Lock()

    def _prepare_endpoints(self, endpoint: Union[str, Sequence[str]]) -> List[str]:
        """
        Normalize endpoint input with simple type checks; fall back to DEFAULT_ENDPOINT as needed.
        """
        endpoints: List[str] = []

        if isinstance(endpoint, str):
            candidate = endpoint.strip()
            if not candidate:
                logger.error(
                    "Docent telemetry endpoint cannot be empty; defaulting to %s.", DEFAULT_ENDPOINT
                )
            else:
                endpoints.append(candidate)
        elif isinstance(endpoint, (list, tuple)):
            for index, value in enumerate(endpoint):
                if not isinstance(value, str):
                    logger.error(
                        "Endpoint entries must be strings; entry at index %s is %s (%r). Skipping it.",
                        index,
                        type(value).__name__,
                        value,
                    )
                    continue
                candidate = value.strip()
                if not candidate:
                    logger.error(
                        "Endpoint entries cannot be empty strings (index %s). Skipping it.",
                        index,
                    )
                    continue
                endpoints.append(candidate)
        else:
            logger.error(
                "Endpoint must be a string or list/tuple of strings (got %r). Defaulting to %s.",
                endpoint,
                DEFAULT_ENDPOINT,
            )

        if not endpoints:
            endpoints = [DEFAULT_ENDPOINT]

        return endpoints

    def get_current_agent_run_id(self) -> Optional[str]:
        """
        Get the current agent run ID from context.

        Retrieves the agent run ID that was set in the current execution context.
        If no agent run context is active, returns the default agent run ID.

        Returns:
            The current agent run ID if available, or the default agent run ID
            if no context is active.
        """
        try:
            return self._agent_run_id_var.get()
        except LookupError:
            return self.default_agent_run_id

    def _register_cleanup(self):
        """Register cleanup handlers."""
        if self._cleanup_registered:
            return

        # Register atexit handler
        atexit.register(self.cleanup)

        self._cleanup_registered = True

    def _next_span_order(self, transcript_id: str) -> int:
        """
        Get the next span order for a given transcript_id.
        Thread-safe and guaranteed to be unique and monotonic.
        """
        with self._transcript_counter_lock:
            return next(self._transcript_counters[transcript_id])

    def _init_spans_exporter(self, endpoint: str) -> Optional[Union[HTTPExporter, GRPCExporter]]:
        """Initialize the appropriate span exporter based on endpoint."""
        if not self.enable_otlp_export:
            return None

        try:
            if "http" in endpoint.lower() or "https" in endpoint.lower():
                http_exporter: HTTPExporter = HTTPExporter(
                    endpoint=f"{endpoint}/v1/traces", headers=self.headers, timeout=30
                )
                logger.debug(f"Initialized HTTP exporter for endpoint: {endpoint}/v1/traces")
                return http_exporter
            else:
                grpc_exporter: GRPCExporter = GRPCExporter(
                    endpoint=endpoint, headers=self.headers, timeout=30
                )
                logger.debug(f"Initialized gRPC exporter for endpoint: {endpoint}")
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
                logger.critical(f"Failed to initialize exporter for endpoint: {endpoint}")

        return exporters

    def _create_span_processor(
        self, exporter: Union[HTTPExporter, GRPCExporter, ConsoleSpanExporter]
    ) -> Union[SimpleSpanProcessor, BatchSpanProcessor]:
        """Create appropriate span processor based on configuration."""
        if self.disable_batch or _is_notebook():
            simple_processor: SimpleSpanProcessor = SimpleSpanProcessor(exporter)
            logger.debug("Created SimpleSpanProcessor for immediate export")
            return simple_processor
        else:
            batch_processor: BatchSpanProcessor = BatchSpanProcessor(exporter)
            logger.debug("Created BatchSpanProcessor for batched export")
            return batch_processor

    def initialize(self):
        """Initialize Docent tracing setup."""
        if self._initialized:
            return

        # If tracing is disabled, mark as initialized but don't set up anything
        if self.is_disabled():
            self._initialized = True
            return

        try:

            # Check for OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT environment variable
            default_attribute_limit = 1024 * 16
            env_value = os.environ.get("OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT", "0")
            env_limit = int(env_value) if env_value.isdigit() else 0
            attribute_limit = max(env_limit, default_attribute_limit)

            span_limits = SpanLimits(
                max_attributes=attribute_limit,
            )

            # Create our own isolated tracer provider
            self._tracer_provider = TracerProvider(
                resource=Resource.create({"service.name": self.collection_name}),
                span_limits=span_limits,
            )

            class ContextSpanProcessor(SpanProcessor):
                def __init__(self, manager: "DocentTracer"):
                    self.manager: "DocentTracer" = manager

                def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
                    # Add collection_id, agent_run_id, transcript_id, transcript_group_id, and any other current attributes
                    span.set_attribute("collection_id", self.manager.collection_id)

                    # Set agent_run_id from context
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

                    # Set transcript_group_id from context
                    try:
                        transcript_group_id: str = self.manager._transcript_group_id_var.get()
                        if transcript_group_id:
                            span.set_attribute("transcript_group_id", transcript_group_id)
                    except LookupError:
                        pass

                    # Set transcript_id from context
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

                    # Set custom attributes from context
                    try:
                        attributes: dict[str, Any] = self.manager._attributes_var.get()
                        for key, value in attributes.items():
                            span.set_attribute(key, value)
                    except LookupError:
                        # attributes not available, skip them
                        pass

                    # Debug logging for span creation
                    span_name = getattr(span, "name", "unknown")
                    span_attrs = getattr(span, "attributes", {})
                    logger.debug(
                        f"Created span: name='{span_name}', collection_id={self.manager.collection_id}, agent_run_id={span_attrs.get('agent_run_id')}, transcript_id={span_attrs.get('transcript_id')}"
                    )

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

            # Instrument threading for better context propagation
            try:
                ThreadingInstrumentor().instrument()
            except Exception as e:
                logger.warning(f"Failed to instrument threading: {e}")

            enabled_instruments = self.instruments - self.block_instruments

            # Instrument OpenAI with our isolated tracer provider
            if Instruments.OPENAI in enabled_instruments:
                try:
                    if is_package_installed("openai"):
                        from opentelemetry.instrumentation.openai import OpenAIInstrumentor

                        OpenAIInstrumentor().instrument(tracer_provider=self._tracer_provider)
                        logger.info("Instrumented OpenAI")
                except Exception as e:
                    logger.warning(f"Failed to instrument OpenAI: {e}")

            # Instrument Anthropic with our isolated tracer provider
            if Instruments.ANTHROPIC in enabled_instruments:
                try:
                    if is_package_installed("anthropic"):
                        from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor

                        AnthropicInstrumentor().instrument(tracer_provider=self._tracer_provider)
                        logger.info("Instrumented Anthropic")
                except Exception as e:
                    logger.warning(f"Failed to instrument Anthropic: {e}")

            # Instrument Bedrock with our isolated tracer provider
            if Instruments.BEDROCK in enabled_instruments:
                try:
                    if is_package_installed("boto3"):
                        from opentelemetry.instrumentation.bedrock import BedrockInstrumentor

                        BedrockInstrumentor().instrument(tracer_provider=self._tracer_provider)
                        logger.info("Instrumented Bedrock")
                except Exception as e:
                    logger.warning(f"Failed to instrument Bedrock: {e}")

            # Instrument LangChain with our isolated tracer provider
            if Instruments.LANGCHAIN in enabled_instruments:
                try:
                    if is_package_installed("langchain") or is_package_installed("langgraph"):
                        from opentelemetry.instrumentation.langchain import LangchainInstrumentor

                        LangchainInstrumentor().instrument(tracer_provider=self._tracer_provider)
                        logger.info("Instrumented LangChain")
                except Exception as e:
                    logger.warning(f"Failed to instrument LangChain: {e}")

            # Instrument Google Generative AI with our isolated tracer provider
            if Instruments.GOOGLE_GENERATIVEAI in enabled_instruments:
                try:
                    if is_package_installed("google-generativeai") or is_package_installed(
                        "google-genai"
                    ):
                        from opentelemetry.instrumentation.google_generativeai import (
                            GoogleGenerativeAiInstrumentor,
                        )

                        GoogleGenerativeAiInstrumentor().instrument(
                            tracer_provider=self._tracer_provider
                        )
                        logger.info("Instrumented Google Generative AI")
                except Exception as e:
                    logger.warning(f"Failed to instrument Google Generative AI: {e}")

            # Register cleanup handlers
            self._register_cleanup()

            self._initialized = True
            logger.info(f"Docent tracing initialized for {self.collection_name}")

        except Exception as e:
            logger.error(f"Failed to initialize Docent tracing: {e}")
            self._disabled = True
            raise

    def cleanup(self):
        """
        Clean up Docent tracing resources.

        Flushes all pending spans to exporters and shuts down the tracer provider.
        This method is automatically called during application shutdown via atexit
        handlers, but can also be called manually for explicit cleanup.

        The cleanup process:
        1. Flushes all span processors to ensure data is exported
        2. Shuts down the tracer provider and releases resources
        """
        if self.is_disabled():
            return

        try:
            self.flush()

            if self._tracer_provider:
                self._tracer_provider.shutdown()
                self._tracer_provider = None
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def close(self):
        """Explicitly close the Docent tracing manager."""
        if self.is_disabled():
            return

        try:
            self.cleanup()
            if self._cleanup_registered:
                atexit.unregister(self.cleanup)
                self._cleanup_registered = False
        except Exception as e:
            logger.error(f"Error during close: {e}")

    def flush(self) -> None:
        """Force flush all spans to exporters."""
        if self.is_disabled():
            return

        try:
            logger.debug(f"Flushing {len(self._spans_processors)} span processors")
            for i, processor in enumerate(self._spans_processors):
                if hasattr(processor, "force_flush"):
                    logger.debug(f"Flushing span processor {i}")
                    processor.force_flush(timeout_millis=50)
            logger.debug("Span flush completed")
        except Exception as e:
            logger.error(f"Error during flush: {e}")

    def is_disabled(self) -> bool:
        """Check if tracing is disabled."""
        return _global_tracing_disabled or self._disabled

    def set_disabled(self, disabled: bool) -> None:
        """Enable or disable tracing."""
        self._disabled = disabled
        if disabled and self._initialized:
            self.cleanup()

    def is_initialized(self) -> bool:
        """Verify if the manager is properly initialized."""
        return self._initialized

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
            metadata: Optional nested dictionary of metadata to send to backend
            **attributes: Additional attributes to add to the context

        Yields:
            Tuple of (agent_run_id, transcript_id)
        """
        if self.is_disabled():
            agent_run_id = _get_disabled_agent_run_id(agent_run_id)
            transcript_id = _get_disabled_transcript_id(transcript_id)
            yield agent_run_id, transcript_id
            return

        if not self._initialized:
            self.initialize()

        if agent_run_id is not None and (not isinstance(agent_run_id, str) or not agent_run_id):
            logger.error("Invalid agent_run_id for agent_run_context; generating a new ID.")
            agent_run_id = str(uuid.uuid4())
        elif agent_run_id is None:
            agent_run_id = str(uuid.uuid4())

        if transcript_id is not None and (not isinstance(transcript_id, str) or not transcript_id):
            logger.error(
                "Invalid transcript_id for agent_run_context; generating a new transcript ID."
            )
            transcript_id = str(uuid.uuid4())
        elif transcript_id is None:
            transcript_id = str(uuid.uuid4())

        # Set context variables for this execution context
        agent_run_id_token: Token[str] = self._agent_run_id_var.set(agent_run_id)
        transcript_id_token: Token[str] = self._transcript_id_var.set(transcript_id)
        attributes_token: Token[dict[str, Any]] = self._attributes_var.set(attributes)

        try:
            # Send metadata directly to backend if provided
            if metadata:
                try:
                    self.send_agent_run_metadata(agent_run_id, metadata)
                except Exception as e:
                    logger.error(f"Failed sending agent run metadata: {e}")

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
            metadata: Optional nested dictionary of metadata to send to backend
            **attributes: Additional attributes to add to the context

        Yields:
            Tuple of (agent_run_id, transcript_id)
        """
        if self.is_disabled():
            agent_run_id = _get_disabled_agent_run_id(agent_run_id)
            transcript_id = _get_disabled_transcript_id(transcript_id)
            yield agent_run_id, transcript_id
            return

        if not self._initialized:
            self.initialize()

        if agent_run_id is not None and (not isinstance(agent_run_id, str) or not agent_run_id):
            logger.error("Invalid agent_run_id for async_agent_run_context; generating a new ID.")
            agent_run_id = str(uuid.uuid4())
        elif agent_run_id is None:
            agent_run_id = str(uuid.uuid4())

        if transcript_id is not None and (not isinstance(transcript_id, str) or not transcript_id):
            logger.error(
                "Invalid transcript_id for async_agent_run_context; generating a new transcript ID."
            )
            transcript_id = str(uuid.uuid4())
        elif transcript_id is None:
            transcript_id = str(uuid.uuid4())

        # Set context variables for this execution context
        agent_run_id_token: Token[str] = self._agent_run_id_var.set(agent_run_id)
        transcript_id_token: Token[str] = self._transcript_id_var.set(transcript_id)
        attributes_token: Token[dict[str, Any]] = self._attributes_var.set(attributes)

        try:
            # Send metadata directly to backend if provided
            if metadata:
                try:
                    self.send_agent_run_metadata(agent_run_id, metadata)
                except Exception as e:
                    logger.warning(f"Failed sending agent run metadata: {e}")

            yield agent_run_id, transcript_id
        finally:
            self._agent_run_id_var.reset(agent_run_id_token)
            self._transcript_id_var.reset(transcript_id_token)
            self._attributes_var.reset(attributes_token)

    def _api_headers(self) -> Dict[str, str]:
        """
        Get the API headers for HTTP requests.

        Returns:
            Headers including content type and any custom entries configured on the tracer
        """
        # Copy configured headers so we don't mutate the original dict
        headers = dict(self.headers)
        # Ensure JSON payloads always advertise the correct content type
        headers.setdefault("Content-Type", "application/json")
        return headers

    def _ensure_json_serializable_metadata(
        self, metadata: Dict[str, Any], context: str
    ) -> Optional[Dict[str, Any]]:
        """
        Validate that metadata can be serialized to JSON before sending it to the backend.
        Returns a sanitized shallow copy so subsequent code never mutates the caller's object.
        Any validation failure is logged and results in None so callers can skip sending metadata.
        """
        if not isinstance(metadata, dict):
            logger.error(
                "%s metadata must be provided as a dict (got %s: %r). Skipping metadata payload.",
                context,
                type(metadata).__name__,
                metadata,
            )
            return None

        metadata_copy: Dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str):
                logger.error(
                    "%s metadata keys must be strings; skipping key %r (type %s).",
                    context,
                    key,
                    type(key).__name__,
                )
                continue
            metadata_copy[key] = value

        try:
            json.dumps(metadata_copy)
        except (TypeError, ValueError) as exc:
            logger.error(
                "%s metadata must be JSON serializable (%s). Skipping metadata payload: %r",
                context,
                exc,
                metadata,
            )
            return None
        offending_path = self._find_null_character_path(metadata_copy)
        if offending_path is not None:
            logger.error(
                "%s metadata cannot contain null characters (found at %s). "
                "Skipping metadata payload.",
                context,
                offending_path,
            )
            return None
        return metadata_copy

    def _post_json(self, path: str, data: Dict[str, Any]) -> None:
        self._post_json_sync(path, data)

    def _post_json_sync(self, path: str, data: Dict[str, Any]) -> None:
        if not self._api_endpoint_base:
            message = "API endpoint base is not configured"
            logger.error(message)
            raise RuntimeError(message)
        url = f"{self._api_endpoint_base}{path}"
        try:
            resp = requests.post(url, json=data, headers=self._api_headers(), timeout=(10, 60))
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            message = self._format_request_exception(url, exc)
            raise DocentTelemetryRequestError(message) from exc

    def _format_request_exception(self, url: str, exc: requests.exceptions.RequestException) -> str:
        response: Optional[Response] = getattr(exc, "response", None)
        message_parts: List[str] = [f"Failed POST {url}"]
        suggestion: Optional[str]

        if response is not None:
            status_phrase = f"HTTP {response.status_code}"
            if response.reason:
                status_phrase = f"{status_phrase} {response.reason}"
            message_parts.append(f"({status_phrase})")

            detail = self._extract_response_detail(response)
            if detail:
                message_parts.append(f"- Backend detail: {detail}")

            request_id = response.headers.get("x-request-id")
            if request_id:
                message_parts.append(f"(request-id: {request_id})")

            suggestion = self._suggest_fix_for_status(response.status_code)
        else:
            message_parts.append(f"- {exc}")
            suggestion = self._suggest_fix_for_status(None)

        if suggestion:
            message_parts.append(suggestion)

        return " ".join(part for part in message_parts if part)

    def _extract_response_detail(self, response: Response) -> Optional[str]:
        try:
            body = response.json()
        except ValueError:
            text = response.text.strip()
            if not text:
                return None
            normalized = " ".join(text.split())
            return self._truncate_error_message(normalized)

        if isinstance(body, dict):
            typed_body = cast(Dict[str, Any], body)
            structured_message = self._structured_detail_message(typed_body)
            if structured_message:
                return self._truncate_error_message(structured_message)
            return self._truncate_error_message(self._normalize_error_value(typed_body))

        return self._truncate_error_message(self._normalize_error_value(body))

    def _structured_detail_message(self, data: Dict[str, Any]) -> Optional[str]:
        for key in ("detail", "message", "error"):
            if key in data:
                structured_value = self._structured_detail_value(data[key])
                if structured_value:
                    return structured_value
        return self._structured_detail_value(data)

    def _structured_detail_value(self, value: Any) -> Optional[str]:
        if isinstance(value, Mapping):
            mapping_value = cast(Mapping[str, Any], value)
            message = mapping_value.get("message")
            hint = mapping_value.get("hint")
            error_code = mapping_value.get("error_code")
            request_id = mapping_value.get("request_id")
            fallback_detail = mapping_value.get("detail")

            parts: List[str] = []
            if isinstance(message, str) and message.strip():
                parts.append(message.strip())
            elif isinstance(fallback_detail, str) and fallback_detail.strip():
                parts.append(fallback_detail.strip())

            if isinstance(hint, str) and hint.strip():
                parts.append(f"(hint: {hint.strip()})")
            if isinstance(error_code, str) and error_code.strip():
                parts.append(f"[code: {error_code.strip()}]")
            if isinstance(request_id, str) and request_id.strip():
                parts.append(f"(request-id: {request_id.strip()})")

            return " ".join(parts) if parts else None

        if isinstance(value, str) and value.strip():
            return value.strip()

        return None

    def _normalize_error_value(self, value: Any) -> str:
        if isinstance(value, str):
            return " ".join(value.split())

        try:
            serialized = json.dumps(value)
        except (TypeError, ValueError):
            serialized = str(value)

        return " ".join(serialized.split())

    def _truncate_error_message(self, message: str) -> str:
        message = message.strip()
        if len(message) <= ERROR_DETAIL_MAX_CHARS:
            return message
        return f"{message[:ERROR_DETAIL_MAX_CHARS]}..."

    def _suggest_fix_for_status(self, status_code: Optional[int]) -> Optional[str]:
        if status_code in (401, 403):
            return (
                "Verify that the Authorization header or DOCENT_API_KEY grants write access to the "
                "target collection."
            )
        if status_code == 404:
            return (
                "Ensure the tracing endpoint passed to initialize_tracing matches the Docent server's "
                "/rest/telemetry route."
            )
        if status_code in (400, 422):
            return (
                "Confirm the payload includes collection_id, agent_run_id, metadata, and timestamp in "
                "the expected format."
            )
        if status_code and status_code >= 500:
            return "Inspect the Docent backend logs for the referenced request."
        if status_code is None:
            return "Confirm the Docent telemetry endpoint is reachable from this process."
        return None

    def _find_null_character_path(self, value: Any, path: str = "") -> Optional[str]:
        """Backend rejects NUL bytes, so detect them before we send metadata to the backend."""
        if isinstance(value, str):
            if "\x00" in value or "\\u0000" in value or "\\x00" in value:
                return path or "<root>"
            return None

        if isinstance(value, dict):
            typed_dict: Mapping[str, Any] = cast(Mapping[str, Any], value)
            for key, item in typed_dict.items():
                key_str = str(key)
                next_path = f"{path}.{key_str}" if path else key_str
                result = self._find_null_character_path(item, next_path)
                if result:
                    return result
            return None

        if isinstance(value, (list, tuple)):
            typed_sequence: Sequence[Any] = cast(Sequence[Any], value)
            for index, item in enumerate(typed_sequence):
                next_path = f"{path}[{index}]" if path else f"[{index}]"
                result = self._find_null_character_path(item, next_path)
                if result:
                    return result
            return None

        return None

    def send_agent_run_score(
        self,
        agent_run_id: str,
        name: str,
        score: float,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a score to the backend for a specific agent run.

        Args:
            agent_run_id: The agent run ID
            name: Name of the score metric
            score: Numeric score value
            attributes: Optional additional attributes
        """
        if self.is_disabled():
            return

        collection_id = self.collection_id
        if not isinstance(agent_run_id, str) or not agent_run_id:
            logger.error("Cannot send agent run score without a valid agent_run_id.")
            return

        if not isinstance(name, str) or not name:
            logger.error("Cannot send agent run score without a valid score name.")
            return

        payload: Dict[str, Any] = {
            "collection_id": collection_id,
            "agent_run_id": agent_run_id,
            "score_name": name,
            "score_value": score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if attributes is not None:
            if not isinstance(attributes, dict):
                logger.error(
                    "Score attributes must be provided as a dict (got %s: %r). Skipping attributes.",
                    type(attributes).__name__,
                    attributes,
                )
            else:
                sanitized_attributes: Dict[str, Any] = {}
                for attr_key, attr_value in attributes.items():
                    if not isinstance(attr_key, str):
                        logger.error(
                            "Score attribute keys must be strings; skipping key %r of type %s.",
                            attr_key,
                            type(attr_key).__name__,
                        )
                        continue
                    sanitized_attributes[attr_key] = attr_value
                payload.update(sanitized_attributes)
        self._post_json("/v1/scores", payload)

    def send_agent_run_metadata(self, agent_run_id: str, metadata: Dict[str, Any]) -> None:
        if self.is_disabled():
            return

        if not isinstance(agent_run_id, str) or not agent_run_id:
            logger.error("Cannot send agent run metadata without a valid agent_run_id.")
            return

        metadata_payload = self._ensure_json_serializable_metadata(metadata, "Agent run")
        if metadata_payload is None:
            logger.error(
                "Skipping agent run metadata send for %s due to invalid metadata payload.",
                agent_run_id,
            )
            return

        collection_id = self.collection_id
        payload: Dict[str, Any] = {
            "collection_id": collection_id,
            "agent_run_id": agent_run_id,
            "metadata": metadata_payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._post_json("/v1/agent-run-metadata", payload)

    def send_transcript_metadata(
        self,
        transcript_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        transcript_group_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send transcript data to the backend.

        Args:
            transcript_id: The transcript ID
            name: Optional transcript name
            description: Optional transcript description
            transcript_group_id: Optional transcript group ID
            metadata: Optional metadata to send
        """
        if self.is_disabled():
            return

        if not isinstance(transcript_id, str) or not transcript_id:
            logger.error("Cannot send transcript metadata without a valid transcript_id.")
            return

        collection_id = self.collection_id
        payload: Dict[str, Any] = {
            "collection_id": collection_id,
            "transcript_id": transcript_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Only add fields that are provided
        if name is not None:
            if isinstance(name, str):
                payload["name"] = name
            else:
                logger.error("Transcript name must be a string; ignoring value %r.", name)
        if description is not None:
            if isinstance(description, str):
                payload["description"] = description
            else:
                logger.error(
                    "Transcript description must be a string; ignoring value %r.", description
                )
        if transcript_group_id is not None:
            if isinstance(transcript_group_id, str) and transcript_group_id:
                payload["transcript_group_id"] = transcript_group_id
            else:
                logger.error(
                    "transcript_group_id must be a non-empty string; ignoring value %r.",
                    transcript_group_id,
                )
        if metadata is not None:
            metadata_payload = self._ensure_json_serializable_metadata(metadata, "Transcript")
            if metadata_payload is None:
                logger.error(
                    "Transcript %s metadata payload invalid; sending transcript data without metadata.",
                    transcript_id,
                )
            else:
                payload["metadata"] = metadata_payload

        self._post_json("/v1/transcript-metadata", payload)

    def get_current_transcript_id(self) -> Optional[str]:
        """
        Get the current transcript ID from context.

        Returns:
            The current transcript ID if available, None otherwise
        """
        try:
            return self._transcript_id_var.get()
        except LookupError:
            return None

    def get_current_transcript_group_id(self) -> Optional[str]:
        """
        Get the current transcript group ID from context.

        Returns:
            The current transcript group ID if available, None otherwise
        """
        try:
            return self._transcript_group_id_var.get()
        except LookupError:
            return None

    @contextmanager
    def transcript_context(
        self,
        name: Optional[str] = None,
        transcript_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        transcript_group_id: Optional[str] = None,
    ) -> Iterator[str]:
        """
        Context manager for setting up a transcript context.

        Args:
            name: Optional transcript name
            transcript_id: Optional transcript ID (auto-generated if not provided)
            description: Optional transcript description
            metadata: Optional metadata to send to backend
            transcript_group_id: Optional transcript group ID

        Yields:
            The transcript ID
        """
        if self.is_disabled():
            transcript_id = _get_disabled_transcript_id(transcript_id)
            yield transcript_id
            return

        if not self._initialized:
            message = "Tracer is not initialized. Call initialize_tracing() before using transcript context."
            logger.error(message)
            raise RuntimeError(message)

        if transcript_id is not None and (not isinstance(transcript_id, str) or not transcript_id):
            logger.error(
                "Invalid transcript_id for transcript_context; generating a new transcript ID."
            )
            transcript_id = str(uuid.uuid4())
        elif transcript_id is None:
            transcript_id = str(uuid.uuid4())

        # Determine transcript group ID before setting new context
        if transcript_group_id is None:
            try:
                transcript_group_id = self._transcript_group_id_var.get()
            except LookupError:
                # No current transcript group context, this transcript has no group
                transcript_group_id = None
        else:
            if isinstance(transcript_group_id, str) and transcript_group_id:
                pass
            else:
                logger.error(
                    "Invalid transcript_group_id for transcript_context; ignoring value %r.",
                    transcript_group_id,
                )
                transcript_group_id = None

        # Set context variable for this execution context
        transcript_id_token: Token[str] = self._transcript_id_var.set(transcript_id)

        try:
            # Send transcript data and metadata to backend
            try:
                self.send_transcript_metadata(
                    transcript_id, name, description, transcript_group_id, metadata
                )
            except Exception as e:
                logger.error(f"Failed sending transcript data: {e}")

            yield transcript_id
        finally:
            # Reset context variable to previous state
            self._transcript_id_var.reset(transcript_id_token)

    @asynccontextmanager
    async def async_transcript_context(
        self,
        name: Optional[str] = None,
        transcript_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        transcript_group_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Async context manager for setting up a transcript context.

        Args:
            name: Optional transcript name
            transcript_id: Optional transcript ID (auto-generated if not provided)
            description: Optional transcript description
            metadata: Optional metadata to send to backend
            transcript_group_id: Optional transcript group ID

        Yields:
            The transcript ID
        """
        if self.is_disabled():
            transcript_id = _get_disabled_transcript_id(transcript_id)
            yield transcript_id
            return

        if not self._initialized:
            message = "Tracer is not initialized. Call initialize_tracing() before using transcript context."
            logger.error(message)
            raise RuntimeError(message)

        if transcript_id is not None and (not isinstance(transcript_id, str) or not transcript_id):
            logger.error(
                "Invalid transcript_id for async_transcript_context; generating a new transcript ID."
            )
            transcript_id = str(uuid.uuid4())
        elif transcript_id is None:
            transcript_id = str(uuid.uuid4())

        # Determine transcript group ID before setting new context
        if transcript_group_id is None:
            try:
                transcript_group_id = self._transcript_group_id_var.get()
            except LookupError:
                # No current transcript group context, this transcript has no group
                transcript_group_id = None
        else:
            if isinstance(transcript_group_id, str) and transcript_group_id:
                pass
            else:
                logger.error(
                    "Invalid transcript_group_id for async_transcript_context; ignoring value %r.",
                    transcript_group_id,
                )
                transcript_group_id = None

        # Set context variable for this execution context
        transcript_id_token: Token[str] = self._transcript_id_var.set(transcript_id)

        try:
            # Send transcript data and metadata to backend
            try:
                self.send_transcript_metadata(
                    transcript_id, name, description, transcript_group_id, metadata
                )
            except Exception as e:
                logger.error(f"Failed sending transcript data: {e}")

            yield transcript_id
        finally:
            # Reset context variable to previous state
            self._transcript_id_var.reset(transcript_id_token)

    def send_transcript_group_metadata(
        self,
        transcript_group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parent_transcript_group_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send transcript group data to the backend.

        Args:
            transcript_group_id: The transcript group ID
            name: Optional transcript group name
            description: Optional transcript group description
            parent_transcript_group_id: Optional parent transcript group ID
            metadata: Optional metadata to send
        """
        if self.is_disabled():
            return

        if not isinstance(transcript_group_id, str) or not transcript_group_id:
            logger.error(
                "Cannot send transcript group metadata without a valid transcript_group_id."
            )
            return

        collection_id = self.collection_id

        # Get agent_run_id from current context
        agent_run_id = self.get_current_agent_run_id()
        if not agent_run_id:
            logger.error(
                f"Cannot send transcript group metadata for {transcript_group_id} - no agent_run_id in context"
            )
            return

        with self._transcript_group_state_lock:
            state: dict[str, Optional[str]] = self._transcript_group_states.setdefault(
                transcript_group_id, {}
            )
            if name is not None:
                if isinstance(name, str):
                    final_name = name
                else:
                    logger.error(
                        "Transcript group name must be a string; ignoring value %r.",
                        name,
                    )
                    final_name = state.get("name")
            else:
                final_name = state.get("name")

            if description is not None:
                if isinstance(description, str):
                    final_description = description
                else:
                    logger.error(
                        "Transcript group description must be a string; ignoring value %r.",
                        description,
                    )
                    final_description = state.get("description")
            else:
                final_description = state.get("description")

            if parent_transcript_group_id is not None:
                if isinstance(parent_transcript_group_id, str) and parent_transcript_group_id:
                    final_parent_transcript_group_id = parent_transcript_group_id
                else:
                    logger.error(
                        "parent_transcript_group_id must be a non-empty string; ignoring value %r.",
                        parent_transcript_group_id,
                    )
                    final_parent_transcript_group_id = state.get("parent_transcript_group_id")
            else:
                final_parent_transcript_group_id = state.get("parent_transcript_group_id")

            if final_name is not None:
                state["name"] = final_name
            if final_description is not None:
                state["description"] = final_description
            if final_parent_transcript_group_id is not None:
                state["parent_transcript_group_id"] = final_parent_transcript_group_id

        payload: Dict[str, Any] = {
            "collection_id": collection_id,
            "transcript_group_id": transcript_group_id,
            "agent_run_id": agent_run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if final_name is not None:
            payload["name"] = final_name
        if final_description is not None:
            payload["description"] = final_description
        if final_parent_transcript_group_id is not None:
            payload["parent_transcript_group_id"] = final_parent_transcript_group_id
            if metadata is not None:
                metadata_payload = self._ensure_json_serializable_metadata(
                    metadata, "Transcript group"
                )
                if metadata_payload is None:
                    logger.error(
                        "Transcript group %s metadata payload invalid; sending group data without metadata.",
                        transcript_group_id,
                    )
                else:
                    payload["metadata"] = metadata_payload

        self._post_json("/v1/transcript-group-metadata", payload)

    @contextmanager
    def transcript_group_context(
        self,
        name: Optional[str] = None,
        transcript_group_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_transcript_group_id: Optional[str] = None,
    ) -> Iterator[str]:
        """
        Context manager for setting up a transcript group context.

        Args:
            name: Optional transcript group name
            transcript_group_id: Optional transcript group ID (auto-generated if not provided)
            description: Optional transcript group description
            metadata: Optional metadata to send to backend
            parent_transcript_group_id: Optional parent transcript group ID

        Yields:
            The transcript group ID
        """
        if self.is_disabled():
            transcript_group_id = _get_disabled_transcript_group_id(transcript_group_id)
            yield transcript_group_id
            return

        if not self._initialized:
            message = "Tracer is not initialized. Call initialize_tracing() before using transcript group context."
            logger.error(message)
            raise RuntimeError(message)

        if transcript_group_id is not None and (
            not isinstance(transcript_group_id, str) or not transcript_group_id
        ):
            logger.error(
                "Invalid transcript_group_id for transcript_group_context; generating a new ID."
            )
            transcript_group_id = str(uuid.uuid4())
        elif transcript_group_id is None:
            transcript_group_id = str(uuid.uuid4())

        # Determine parent transcript group ID before setting new context
        if parent_transcript_group_id is None:
            try:
                parent_transcript_group_id = self._transcript_group_id_var.get()
            except LookupError:
                # No current transcript group context, this becomes a root group
                parent_transcript_group_id = None
        else:
            if isinstance(parent_transcript_group_id, str) and parent_transcript_group_id:
                pass
            else:
                logger.error(
                    "Invalid parent_transcript_group_id for transcript_group_context; ignoring value %r.",
                    parent_transcript_group_id,
                )
                parent_transcript_group_id = None

        # Set context variable for this execution context
        transcript_group_id_token: Token[str] = self._transcript_group_id_var.set(
            transcript_group_id
        )

        try:
            # Send transcript group data and metadata to backend
            try:
                self.send_transcript_group_metadata(
                    transcript_group_id, name, description, parent_transcript_group_id, metadata
                )
            except Exception as e:
                logger.error(f"Failed sending transcript group data: {e}")

            yield transcript_group_id
        finally:
            # Reset context variable to previous state
            self._transcript_group_id_var.reset(transcript_group_id_token)

    @asynccontextmanager
    async def async_transcript_group_context(
        self,
        name: Optional[str] = None,
        transcript_group_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_transcript_group_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Async context manager for setting up a transcript group context.

        Args:
            name: Optional transcript group name
            transcript_group_id: Optional transcript group ID (auto-generated if not provided)
            description: Optional transcript group description
            metadata: Optional metadata to send to backend
            parent_transcript_group_id: Optional parent transcript group ID

        Yields:
            The transcript group ID
        """
        if self.is_disabled():
            transcript_group_id = _get_disabled_transcript_group_id(transcript_group_id)
            yield transcript_group_id
            return

        if not self._initialized:
            message = "Tracer is not initialized. Call initialize_tracing() before using transcript group context."
            logger.error(message)
            raise RuntimeError(message)

        if transcript_group_id is not None and (
            not isinstance(transcript_group_id, str) or not transcript_group_id
        ):
            logger.error(
                "Invalid transcript_group_id for async_transcript_group_context; generating a new ID."
            )
            transcript_group_id = str(uuid.uuid4())
        elif transcript_group_id is None:
            transcript_group_id = str(uuid.uuid4())

        # Determine parent transcript group ID before setting new context
        if parent_transcript_group_id is None:
            try:
                parent_transcript_group_id = self._transcript_group_id_var.get()
            except LookupError:
                # No current transcript group context, this becomes a root group
                parent_transcript_group_id = None
        else:
            if isinstance(parent_transcript_group_id, str) and parent_transcript_group_id:
                pass
            else:
                logger.error(
                    "Invalid parent_transcript_group_id for async_transcript_group_context; ignoring value %r.",
                    parent_transcript_group_id,
                )
                parent_transcript_group_id = None

        # Set context variable for this execution context
        transcript_group_id_token: Token[str] = self._transcript_group_id_var.set(
            transcript_group_id
        )

        try:
            # Send transcript group data and metadata to backend
            try:
                self.send_transcript_group_metadata(
                    transcript_group_id, name, description, parent_transcript_group_id, metadata
                )
            except Exception as e:
                logger.error(f"Failed sending transcript group data: {e}")

            yield transcript_group_id
        finally:
            # Reset context variable to previous state
            self._transcript_group_id_var.reset(transcript_group_id_token)

    def _send_trace_done(self) -> None:
        if self.is_disabled():
            return

        collection_id = self.collection_id
        payload: Dict[str, Any] = {
            "collection_id": collection_id,
            "status": "completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._post_json("/v1/trace-done", payload)
        except Exception as exc:
            logger.error(f"Failed to send trace completion signal: {exc}")


_global_tracer: Optional[DocentTracer] = None
_global_tracing_disabled: bool = os.environ.get("DOCENT_DISABLE_TRACING", "").lower() == "true"


def initialize_tracing(
    collection_name: str = DEFAULT_COLLECTION_NAME,
    collection_id: Optional[str] = None,
    endpoint: Union[str, List[str]] = DEFAULT_ENDPOINT,
    headers: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None,
    enable_console_export: bool = False,
    enable_otlp_export: bool = True,
    disable_batch: bool = False,
    instruments: Optional[Set[Instruments]] = None,
    block_instruments: Optional[Set[Instruments]] = None,
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
        api_key: Optional API key for bearer token authentication (takes precedence
                over DOCENT_API_KEY environment variable)
        enable_console_export: Whether to export spans to console for debugging
        enable_otlp_export: Whether to export spans to OTLP endpoint
        disable_batch: Whether to disable batch processing (use SimpleSpanProcessor)
        instruments: Set of instruments to enable (None = all instruments).
        block_instruments: Set of instruments to explicitly disable.

    Returns:
        The initialized Docent tracer

    Example:
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
            instruments=instruments,
            block_instruments=block_instruments,
        )
        _global_tracer.initialize()

    return _global_tracer


def _get_package_name(dist: Distribution) -> str | None:
    try:
        return dist.name.lower()
    except (KeyError, AttributeError):
        return None


installed_packages = {
    name for dist in distributions() if (name := _get_package_name(dist)) is not None
}


def is_package_installed(package_name: str) -> bool:
    return package_name.lower() in installed_packages


def get_tracer(caller: str = "get_tracer()") -> Optional[DocentTracer]:
    """
    Get the global Docent tracer if it has been initialized.

    Args:
        caller: Human-readable name of the API being invoked. Used for log output.

    Returns:
        The global Docent tracer, or None if tracing has not been initialized.
    """
    tracer = _global_tracer
    if tracer is None:
        logger.error(
            f"{caller} requires initialize_tracing() to be called before use. "
            "You can also disable tracing by calling set_disabled(True) or by setting "
            "the DOCENT_DISABLE_TRACING environment variable to 'true'."
        )
        return None

    if not tracer.is_initialized():
        logger.error(
            f"{caller} cannot proceed because initialize_tracing() did not complete successfully. "
            "You can also disable tracing by calling set_disabled(True) or by setting "
            "the DOCENT_DISABLE_TRACING environment variable to 'true'."
        )
        return None

    return tracer


def close_tracing() -> None:
    """Close the global Docent tracer."""
    global _global_tracer
    if _global_tracer:
        _global_tracer.close()
        _global_tracer = None


def flush_tracing() -> None:
    """Force flush all spans to exporters."""
    if _global_tracer:
        logger.debug("Flushing Docent tracer")
        _global_tracer.flush()
    else:
        logger.debug("No global tracer available to flush")


def is_initialized() -> bool:
    """Verify if the global Docent tracer is properly initialized."""
    if _global_tracer is None:
        return False
    return _global_tracer.is_initialized()


def is_disabled(context_name: str = "Docent tracing") -> bool:
    """
    Check if global tracing is disabled for the given context.

    Args:
        context_name: Human-readable identifier for the caller used in error reporting.

    Returns:
        True when tracing is disabled globally, when no initialized tracer exists,
        or when the active tracer reports being disabled.
    """
    if _global_tracing_disabled:
        return True
    tracer = get_tracer(context_name)
    if tracer is None:
        return True
    return tracer.is_disabled()


def set_disabled(disabled: bool) -> None:
    """Enable or disable global tracing."""
    global _global_tracing_disabled
    _global_tracing_disabled = disabled
    if _global_tracer:
        _global_tracer.set_disabled(disabled)


def agent_run_score(name: str, score: float, attributes: Optional[Dict[str, Any]] = None) -> None:
    """
    Send a score to the backend for the current agent run.

    Args:
        name: Name of the score metric
        score: Numeric score value
        attributes: Optional additional attributes for the score event
    """
    if is_disabled("agent_run_score()"):
        return

    tracer = get_tracer("agent_run_score()")
    if tracer is None:
        logger.error("Docent tracer unavailable; score will not be sent.")
        return

    agent_run_id = tracer.get_current_agent_run_id()
    if not agent_run_id:
        logger.warning("No active agent run context. Score will not be sent.")
        return

    try:
        tracer.send_agent_run_score(agent_run_id, name, score, attributes)
    except Exception as e:
        logger.error(f"Failed to send score: {e}")


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


def agent_run_metadata(metadata: Dict[str, Any]) -> None:
    """
    Send metadata directly to the backend for the current agent run.

    Args:
        metadata: Dictionary of metadata to attach to the current span (can be nested)

    Example:
        agent_run_metadata({"user": "John", "id": 123, "flagged": True})
        agent_run_metadata({"user": {"id": "123", "name": "John"}, "config": {"model": "gpt-4"}})
    """
    if is_disabled("agent_run_metadata()"):
        return

    tracer = get_tracer("agent_run_metadata()")
    if tracer is None:
        logger.error("Docent tracer unavailable; agent run metadata will not be sent.")
        return

    agent_run_id = tracer.get_current_agent_run_id()
    if not agent_run_id:
        logger.warning("No active agent run context. Metadata will not be sent.")
        return

    try:
        tracer.send_agent_run_metadata(agent_run_id, metadata)
    except Exception as e:
        logger.error(f"Failed to send agent run metadata: {e}")


def transcript_metadata(
    metadata: Dict[str, Any],
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    transcript_group_id: Optional[str] = None,
) -> None:
    """
    Send transcript metadata directly to the backend for the current transcript.

    Args:
        metadata: Dictionary of metadata to attach to the current transcript (required)
        name: Optional transcript name
        description: Optional transcript description
        transcript_group_id: Optional transcript group ID to associate with

    Example:
        transcript_metadata({"user": "John", "model": "gpt-4"})
        transcript_metadata({"env": "prod"}, name="data_processing")
        transcript_metadata(
            {"team": "search"},
            name="validation",
            transcript_group_id="group-123",
        )
    """
    if is_disabled("transcript_metadata()"):
        return

    tracer = get_tracer("transcript_metadata()")
    if tracer is None:
        logger.error("Docent tracer unavailable; transcript metadata will not be sent.")
        return

    transcript_id = tracer.get_current_transcript_id()
    if not transcript_id:
        logger.warning("No active transcript context. Metadata will not be sent.")
        return

    try:
        tracer.send_transcript_metadata(
            transcript_id, name, description, transcript_group_id, metadata
        )
    except Exception as e:
        logger.error(f"Failed to send transcript metadata: {e}")


def transcript_group_metadata(
    metadata: Dict[str, Any],
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    parent_transcript_group_id: Optional[str] = None,
) -> None:
    """
    Send transcript group metadata directly to the backend for the current transcript group.

    Args:
        metadata: Dictionary of metadata to attach to the current transcript group (required)
        name: Optional transcript group name
        description: Optional transcript group description
        parent_transcript_group_id: Optional parent transcript group ID

    Example:
        transcript_group_metadata({"team": "search", "env": "prod"})
        transcript_group_metadata({"env": "prod"}, name="pipeline")
        transcript_group_metadata(
            {"team": "search"},
            name="pipeline",
            parent_transcript_group_id="root-group",
        )
    """
    if is_disabled("transcript_group_metadata()"):
        return

    tracer = get_tracer("transcript_group_metadata()")
    if tracer is None:
        logger.error("Docent tracer unavailable; transcript group metadata will not be sent.")
        return

    transcript_group_id = tracer.get_current_transcript_group_id()
    if not transcript_group_id:
        logger.warning("No active transcript group context. Metadata will not be sent.")
        return

    try:
        tracer.send_transcript_group_metadata(
            transcript_group_id, name, description, parent_transcript_group_id, metadata
        )
    except Exception as e:
        logger.error(f"Failed to send transcript group metadata: {e}")


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
        if is_disabled("agent_run_context"):
            self.agent_run_id = _get_disabled_agent_run_id(self.agent_run_id)
            self.transcript_id = _get_disabled_transcript_id(self.transcript_id)
            return self.agent_run_id, self.transcript_id

        tracer = get_tracer("agent_run_context")
        if tracer is None:
            logger.error("Cannot enter agent_run_context because tracing is not initialized.")
            self.agent_run_id = _get_disabled_agent_run_id(self.agent_run_id)
            self.transcript_id = _get_disabled_transcript_id(self.transcript_id)
            return self.agent_run_id, self.transcript_id
        self._sync_context = tracer.agent_run_context(
            self.agent_run_id, self.transcript_id, metadata=self.metadata, **self.attributes
        )
        return self._sync_context.__enter__()

    def __exit__(self, exc_type: type[BaseException], exc_val: Any, exc_tb: Any) -> None:
        """Sync context manager exit."""
        if self._sync_context:
            self._sync_context.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> tuple[str, str]:
        """Async context manager entry."""
        if is_disabled("agent_run_context"):
            self.agent_run_id = _get_disabled_agent_run_id(self.agent_run_id)
            self.transcript_id = _get_disabled_transcript_id(self.transcript_id)
            return self.agent_run_id, self.transcript_id

        tracer = get_tracer("agent_run_context")
        if tracer is None:
            logger.error("Cannot enter agent_run_context because tracing is not initialized.")
            self.agent_run_id = _get_disabled_agent_run_id(self.agent_run_id)
            self.transcript_id = _get_disabled_transcript_id(self.transcript_id)
            return self.agent_run_id, self.transcript_id
        self._async_context = tracer.async_agent_run_context(
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


class TranscriptContext:
    """Context manager for creating and managing transcripts."""

    def __init__(
        self,
        name: Optional[str] = None,
        transcript_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        transcript_group_id: Optional[str] = None,
    ):
        self.name = name
        self.transcript_id = transcript_id
        self.description = description
        self.metadata = metadata
        self.transcript_group_id = transcript_group_id
        self._sync_context: Optional[Any] = None
        self._async_context: Optional[Any] = None

    def __enter__(self) -> str:
        """Sync context manager entry."""
        if is_disabled("transcript_context"):
            self.transcript_id = _get_disabled_transcript_id(self.transcript_id)
            return self.transcript_id

        tracer = get_tracer("transcript_context")
        if tracer is None:
            logger.error("Cannot enter transcript_context because tracing is not initialized.")
            self.transcript_id = _get_disabled_transcript_id(self.transcript_id)
            return self.transcript_id
        self._sync_context = tracer.transcript_context(
            name=self.name,
            transcript_id=self.transcript_id,
            description=self.description,
            metadata=self.metadata,
            transcript_group_id=self.transcript_group_id,
        )
        return self._sync_context.__enter__()

    def __exit__(self, exc_type: type[BaseException], exc_val: Any, exc_tb: Any) -> None:
        """Sync context manager exit."""
        if self._sync_context:
            self._sync_context.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> str:
        """Async context manager entry."""
        if is_disabled("transcript_context"):
            self.transcript_id = _get_disabled_transcript_id(self.transcript_id)
            return self.transcript_id

        tracer = get_tracer("transcript_context")
        if tracer is None:
            logger.error("Cannot enter transcript_context because tracing is not initialized.")
            self.transcript_id = _get_disabled_transcript_id(self.transcript_id)
            return self.transcript_id
        self._async_context = tracer.async_transcript_context(
            name=self.name,
            transcript_id=self.transcript_id,
            description=self.description,
            metadata=self.metadata,
            transcript_group_id=self.transcript_group_id,
        )
        return await self._async_context.__aenter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._async_context:
            await self._async_context.__aexit__(exc_type, exc_val, exc_tb)


def transcript(
    func: Optional[Callable[..., Any]] = None,
    *,
    name: Optional[str] = None,
    transcript_id: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    transcript_group_id: Optional[str] = None,
):
    """
    Decorator to wrap a function in a transcript context.
    Injects transcript_id as a function attribute.

    Example:
        @transcript
        def my_func(x, y):
            print(my_func.docent.transcript_id)

        @transcript(name="data_processing", description="Process user data")
        def my_func_with_name(x, y):
            print(my_func_with_name.docent.transcript_id)

        @transcript(metadata={"user": "John", "model": "gpt-4"})
        async def my_async_func(z):
            print(my_async_func.docent.transcript_id)
    """
    import functools
    import inspect

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(f):

            @functools.wraps(f)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                async with TranscriptContext(
                    name=name,
                    transcript_id=transcript_id,
                    description=description,
                    metadata=metadata,
                    transcript_group_id=transcript_group_id,
                ) as transcript_id_result:
                    # Store docent data as function attributes
                    setattr(
                        async_wrapper,
                        "docent",
                        type(
                            "DocentData",
                            (),
                            {
                                "transcript_id": transcript_id_result,
                            },
                        )(),
                    )
                    return await f(*args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(f)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with TranscriptContext(
                    name=name,
                    transcript_id=transcript_id,
                    description=description,
                    metadata=metadata,
                    transcript_group_id=transcript_group_id,
                ) as transcript_id_result:
                    # Store docent data as function attributes
                    setattr(
                        sync_wrapper,
                        "docent",
                        type(
                            "DocentData",
                            (),
                            {
                                "transcript_id": transcript_id_result,
                            },
                        )(),
                    )
                    return f(*args, **kwargs)

            return sync_wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)


def transcript_context(
    name: Optional[str] = None,
    transcript_id: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    transcript_group_id: Optional[str] = None,
) -> TranscriptContext:
    """
    Create a transcript context for tracing.

    Args:
        name: Optional transcript name
        transcript_id: Optional transcript ID (auto-generated if not provided)
        description: Optional transcript description
        metadata: Optional metadata to attach to the transcript
        parent_transcript_id: Optional parent transcript ID

    Returns:
        A context manager that can be used with both 'with' and 'async with'

    Example:
        # Sync usage
        with transcript_context(name="data_processing") as transcript_id:
            pass

        # Async usage
        async with transcript_context(description="Process user data") as transcript_id:
            pass

        # With metadata
        with transcript_context(metadata={"user": "John", "model": "gpt-4"}) as transcript_id:
            pass
    """
    return TranscriptContext(name, transcript_id, description, metadata, transcript_group_id)


class TranscriptGroupContext:
    """Context manager for creating and managing transcript groups."""

    def __init__(
        self,
        name: Optional[str] = None,
        transcript_group_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_transcript_group_id: Optional[str] = None,
    ):
        self.name = name
        self.transcript_group_id = transcript_group_id
        self.description = description
        self.metadata = metadata
        self.parent_transcript_group_id = parent_transcript_group_id
        self._sync_context: Optional[Any] = None
        self._async_context: Optional[Any] = None

    def __enter__(self) -> str:
        """Sync context manager entry."""
        if is_disabled("transcript_group_context"):
            self.transcript_group_id = _get_disabled_transcript_group_id(self.transcript_group_id)
            return self.transcript_group_id

        tracer = get_tracer("transcript_group_context")
        if tracer is None:
            logger.error(
                "Cannot enter transcript_group_context because tracing is not initialized."
            )
            self.transcript_group_id = _get_disabled_transcript_group_id(self.transcript_group_id)
            return self.transcript_group_id
        self._sync_context = tracer.transcript_group_context(
            name=self.name,
            transcript_group_id=self.transcript_group_id,
            description=self.description,
            metadata=self.metadata,
            parent_transcript_group_id=self.parent_transcript_group_id,
        )
        return self._sync_context.__enter__()

    def __exit__(self, exc_type: type[BaseException], exc_val: Any, exc_tb: Any) -> None:
        """Sync context manager exit."""
        if self._sync_context:
            self._sync_context.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> str:
        """Async context manager entry."""
        if is_disabled("transcript_group_context"):
            self.transcript_group_id = _get_disabled_transcript_group_id(self.transcript_group_id)
            return self.transcript_group_id

        tracer = get_tracer("transcript_group_context")
        if tracer is None:
            logger.error(
                "Cannot enter transcript_group_context because tracing is not initialized."
            )
            self.transcript_group_id = _get_disabled_transcript_group_id(self.transcript_group_id)
            return self.transcript_group_id
        self._async_context = tracer.async_transcript_group_context(
            name=self.name,
            transcript_group_id=self.transcript_group_id,
            description=self.description,
            metadata=self.metadata,
            parent_transcript_group_id=self.parent_transcript_group_id,
        )
        return await self._async_context.__aenter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._async_context:
            await self._async_context.__aexit__(exc_type, exc_val, exc_tb)


def transcript_group(
    func: Optional[Callable[..., Any]] = None,
    *,
    name: Optional[str] = None,
    transcript_group_id: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    parent_transcript_group_id: Optional[str] = None,
):
    """
    Decorator to wrap a function in a transcript group context.
    Injects transcript_group_id as a function attribute.

    Example:
        @transcript_group
        def my_func(x, y):
            print(my_func.docent.transcript_group_id)

        @transcript_group(name="data_processing", description="Process user data")
        def my_func_with_name(x, y):
            print(my_func_with_name.docent.transcript_group_id)

        @transcript_group(metadata={"user": "John", "model": "gpt-4"})
        async def my_async_func(z):
            print(my_async_func.docent.transcript_group_id)
    """
    import functools
    import inspect

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(f):

            @functools.wraps(f)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                async with TranscriptGroupContext(
                    name=name,
                    transcript_group_id=transcript_group_id,
                    description=description,
                    metadata=metadata,
                    parent_transcript_group_id=parent_transcript_group_id,
                ) as transcript_group_id_result:
                    # Store docent data as function attributes
                    setattr(
                        async_wrapper,
                        "docent",
                        type(
                            "DocentData",
                            (),
                            {
                                "transcript_group_id": transcript_group_id_result,
                            },
                        )(),
                    )
                    return await f(*args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(f)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with TranscriptGroupContext(
                    name=name,
                    transcript_group_id=transcript_group_id,
                    description=description,
                    metadata=metadata,
                    parent_transcript_group_id=parent_transcript_group_id,
                ) as transcript_group_id_result:
                    # Store docent data as function attributes
                    setattr(
                        sync_wrapper,
                        "docent",
                        type(
                            "DocentData",
                            (),
                            {
                                "transcript_group_id": transcript_group_id_result,
                            },
                        )(),
                    )
                    return f(*args, **kwargs)

            return sync_wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)


def transcript_group_context(
    name: Optional[str] = None,
    transcript_group_id: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    parent_transcript_group_id: Optional[str] = None,
) -> TranscriptGroupContext:
    """
    Create a transcript group context for tracing.

    Args:
        name: Optional transcript group name
        transcript_group_id: Optional transcript group ID (auto-generated if not provided)
        description: Optional transcript group description
        metadata: Optional metadata to attach to the transcript group
        parent_transcript_group_id: Optional parent transcript group ID

    Returns:
        A context manager that can be used with both 'with' and 'async with'

    Example:
        # Sync usage
        with transcript_group_context(name="data_processing") as transcript_group_id:
            pass

        # Async usage
        async with transcript_group_context(description="Process user data") as transcript_group_id:
            pass

        # With metadata
        with transcript_group_context(metadata={"user": "John", "model": "gpt-4"}) as transcript_group_id:
            pass
    """
    return TranscriptGroupContext(
        name, transcript_group_id, description, metadata, parent_transcript_group_id
    )


def _is_notebook() -> bool:
    """Check if we're running in a Jupyter notebook."""
    try:
        return "ipykernel" in sys.modules
    except Exception:
        return False
