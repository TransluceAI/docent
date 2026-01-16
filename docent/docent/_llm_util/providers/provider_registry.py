"""Registry for LLM providers with their configurations."""

from __future__ import annotations

from typing import Any, Callable, Literal, Protocol, TypedDict

from docent._llm_util.data_models.llm_output import (
    AsyncSingleLLMOutputStreamingCallback,
    LLMOutput,
)
from docent._llm_util.providers import anthropic, google, openai, openrouter
from docent._llm_util.providers.anthropic import (
    get_anthropic_chat_completion_async,
    get_anthropic_chat_completion_streaming_async,
)
from docent._llm_util.providers.google import (
    get_google_chat_completion_async,
    get_google_chat_completion_streaming_async,
)
from docent._llm_util.providers.openai import (
    get_openai_chat_completion_async,
    get_openai_chat_completion_streaming_async,
)
from docent._llm_util.providers.openrouter import (
    get_openrouter_chat_completion_async,
    get_openrouter_chat_completion_streaming_async,
)
from docent.data_models.chat import ChatMessage, ToolInfo
from docent.data_models.chat.response_format import ResponseFormat


class SingleOutputGetter(Protocol):
    """Protocol for getting non-streaming output from an LLM.

    Defines the interface for async functions that retrieve a single
    non-streaming response from an LLM provider.
    """

    async def __call__(
        self,
        client: Any,
        messages: list[ChatMessage],
        model_name: str,
        *,
        tools: list[ToolInfo] | None,
        tool_choice: Literal["auto", "required"] | None,
        max_new_tokens: int,
        temperature: float,
        reasoning_effort: Literal["low", "medium", "high"] | None,
        logprobs: bool,
        top_logprobs: int | None,
        timeout: float,
        response_format: ResponseFormat | None,
    ) -> LLMOutput:
        """Get a single completion from an LLM.

        Args:
            client: The provider-specific client instance.
            messages: The list of messages in the conversation.
            model_name: The name of the model to use.
            tools: Optional list of tools available to the model.
            tool_choice: Optional specification for tool usage.
            max_new_tokens: Maximum number of tokens to generate.
            temperature: Controls randomness in output generation.
            reasoning_effort: Optional control for model reasoning depth.
            logprobs: Whether to return log probabilities.
            top_logprobs: Number of most likely tokens to return probabilities for.
            timeout: Maximum time to wait for a response in seconds.
            response_format: Optional structured output format specification.

        Returns:
            LLMOutput: The model's response.
        """
        ...


class SingleStreamingOutputGetter(Protocol):
    """Protocol for getting streaming output from an LLM.

    Defines the interface for async functions that retrieve streaming
    responses from an LLM provider.
    """

    async def __call__(
        self,
        client: Any,
        streaming_callback: AsyncSingleLLMOutputStreamingCallback | None,
        messages: list[ChatMessage],
        model_name: str,
        *,
        tools: list[ToolInfo] | None,
        tool_choice: Literal["auto", "required"] | None,
        max_new_tokens: int,
        temperature: float,
        reasoning_effort: Literal["low", "medium", "high"] | None,
        logprobs: bool,
        top_logprobs: int | None,
        timeout: float,
        response_format: ResponseFormat | None,
    ) -> LLMOutput:
        """Get a streaming completion from an LLM.

        Args:
            client: The provider-specific client instance.
            streaming_callback: Optional callback for processing streaming chunks.
            messages: The list of messages in the conversation.
            model_name: The name of the model to use.
            tools: Optional list of tools available to the model.
            tool_choice: Optional specification for tool usage.
            max_new_tokens: Maximum number of tokens to generate.
            temperature: Controls randomness in output generation.
            reasoning_effort: Optional control for model reasoning depth.
            logprobs: Whether to return log probabilities.
            top_logprobs: Number of most likely tokens to return probabilities for.
            timeout: Maximum time to wait for a response in seconds.
            response_format: Optional structured output format specification.

        Returns:
            LLMOutput: The complete model response after streaming finishes.
        """
        ...


class ProviderConfig(TypedDict):
    """Configuration for an LLM provider.

    Contains the necessary functions to create clients and interact with
    a specific LLM provider.

    Attributes:
        async_client_getter: Function to get an async client for the provider.
        single_output_getter: Function to get a non-streaming completion.
        single_streaming_output_getter: Function to get a streaming completion.
    """

    async_client_getter: Callable[[str | None], Any]
    single_output_getter: SingleOutputGetter
    single_streaming_output_getter: SingleStreamingOutputGetter


# Registry of supported LLM providers with their respective configurations
PROVIDERS: dict[str, ProviderConfig] = {
    "anthropic": ProviderConfig(
        async_client_getter=anthropic.get_anthropic_client_async,
        single_output_getter=get_anthropic_chat_completion_async,
        single_streaming_output_getter=get_anthropic_chat_completion_streaming_async,
    ),
    "google": ProviderConfig(
        async_client_getter=google.get_google_client_async,
        single_output_getter=get_google_chat_completion_async,
        single_streaming_output_getter=get_google_chat_completion_streaming_async,
    ),
    "openai": ProviderConfig(
        async_client_getter=openai.get_openai_client_async,
        single_output_getter=get_openai_chat_completion_async,
        single_streaming_output_getter=get_openai_chat_completion_streaming_async,
    ),
    "azure_openai": ProviderConfig(
        async_client_getter=openai.get_azure_openai_client_async,
        single_output_getter=get_openai_chat_completion_async,
        single_streaming_output_getter=get_openai_chat_completion_streaming_async,
    ),
    "openrouter": ProviderConfig(
        async_client_getter=openrouter.get_openrouter_client_async,
        single_output_getter=get_openrouter_chat_completion_async,
        single_streaming_output_getter=get_openrouter_chat_completion_streaming_async,
    ),
}
"""Registry of supported LLM providers with their respective configurations."""
