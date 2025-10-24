"""Provides preferences of which LLM models to use for different Docent functions."""

from functools import cached_property
from typing import Literal

from pydantic import BaseModel

from docent._llm_util.model_registry import get_context_window
from docent._log_util import get_logger

logger = get_logger(__name__)


class ModelOption(BaseModel):
    """Configuration for a specific model from a provider. Not to be confused with ModelInfo.

    Attributes:
        provider: The name of the LLM provider (e.g., "openai", "anthropic").
        model_name: The specific model to use from the provider.
        reasoning_effort: Optional indication of computational effort to use.
    """

    provider: str
    model_name: str
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None


class ModelOptionWithContext(BaseModel):
    """Enhanced model option that includes context window information for frontend use.
    Not to be confused with ModelInfo or ModelOption.

    Attributes:
        provider: The name of the LLM provider (e.g., "openai", "anthropic").
        model_name: The specific model to use from the provider.
        reasoning_effort: Optional indication of computational effort to use.
        context_window: The context window size in tokens.
        uses_byok: Whether this model would use the user's own API key.
    """

    provider: str
    model_name: str
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    context_window: int
    uses_byok: bool

    @classmethod
    def from_model_option(
        cls, model_option: ModelOption, uses_byok: bool = False
    ) -> "ModelOptionWithContext":
        """Create a ModelOptionWithContext from a ModelOption.

        Args:
            model_option: The base model option
            uses_byok: Whether this model requires bring-your-own-key

        Returns:
            ModelOptionWithContext with context window looked up from global mapping
        """
        context_window = get_context_window(model_option.model_name)

        return cls(
            provider=model_option.provider,
            model_name=model_option.model_name,
            reasoning_effort=model_option.reasoning_effort,
            context_window=context_window,
            uses_byok=uses_byok,
        )


def merge_models_with_byok(
    defaults: list[ModelOption],
    byok: list[ModelOption],
    api_keys: dict[str, str] | None,
) -> list[ModelOptionWithContext]:
    user_keys = api_keys or {}

    merged: list[ModelOption] = list(defaults)
    if user_keys:
        merged.extend([m for m in byok if m.provider in user_keys])

    return [ModelOptionWithContext.from_model_option(m, m.provider in user_keys) for m in merged]


class PublicProviderPreferences(BaseModel):
    @cached_property
    def default_judge_models(self) -> list[ModelOption]:
        """Judge models that any user can access without providing their own API key"""

        return [
            ModelOption(provider="openai", model_name="gpt-5", reasoning_effort="medium"),
            ModelOption(provider="openai", model_name="gpt-5", reasoning_effort="low"),
            ModelOption(provider="openai", model_name="gpt-5", reasoning_effort="high"),
            ModelOption(provider="openai", model_name="gpt-5-mini", reasoning_effort="low"),
            ModelOption(provider="openai", model_name="gpt-5-mini", reasoning_effort="medium"),
            ModelOption(provider="openai", model_name="gpt-5-mini", reasoning_effort="high"),
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort="medium",
            ),
        ]


PUBLIC_PROVIDER_PREFERENCES = PublicProviderPreferences()
