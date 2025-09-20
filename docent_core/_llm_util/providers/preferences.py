"""Provides preferences of which LLM models to use for different Docent functions."""

from functools import cached_property
from typing import Literal

from pydantic import BaseModel

from docent._log_util import get_logger

logger = get_logger(__name__)

# Global mapping of model names to their context window sizes (in tokens)
# More specific names should come first, because we take the first one that matches a prefix
MODEL_CONTEXT_WINDOWS = {
    # OpenAI
    "gpt-5": 400_000,
    # Anthropic
    "claude-sonnet-4": 200_000,
    # Google
    "gemini-2.5-flash-lite": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.5-pro": 1_000_000,
}


class ModelOption(BaseModel):
    """Configuration for a specific model from a provider.

    Attributes:
        provider: The name of the LLM provider (e.g., "openai", "anthropic").
        model_name: The specific model to use from the provider.
        reasoning_effort: Optional indication of computational effort to use.
    """

    provider: str
    model_name: str
    reasoning_effort: Literal["low", "medium", "high"] | None = None


class ModelOptionWithContext(BaseModel):
    """Enhanced model option that includes context window information for frontend use.

    Attributes:
        provider: The name of the LLM provider (e.g., "openai", "anthropic").
        model_name: The specific model to use from the provider.
        reasoning_effort: Optional indication of computational effort to use.
        context_window: The context window size in tokens.
        uses_byok: Whether this model would use the user's own API key.
    """

    provider: str
    model_name: str
    reasoning_effort: Literal["low", "medium", "high"] | None = None
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
        for k, v in MODEL_CONTEXT_WINDOWS.items():
            if model_option.model_name.startswith(k):
                context_window = v
                break
        else:
            logger.warning(f"No context window found for model {model_option.model_name}")
            context_window = 100_000

        return cls(
            provider=model_option.provider,
            model_name=model_option.model_name,
            reasoning_effort=model_option.reasoning_effort,
            context_window=context_window,
            uses_byok=uses_byok,
        )


class ProviderPreferences(BaseModel):
    """Manages model preferences for different docent functions.

    This class provides access to configured model options for each
    function that requires LLM capabilities in the docent system.
    """

    @cached_property
    def default_chat_models(self) -> list[ModelOption]:
        """Models that can be used for chat if the user does not provide their own API key."""
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
            ),
            ModelOption(
                provider="openai",
                model_name="gpt-5",
                reasoning_effort="low",
            ),
        ]

    @cached_property
    def byok_chat_models(self) -> list[ModelOption]:
        """Models that can be used for chat if the user provides their own API key."""
        return [
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-lite",
                reasoning_effort="low",
            ),
        ]

    @cached_property
    def generate_new_queries(self) -> list[ModelOption]:
        """Get model options for the generate_new_queries function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="openai",
                model_name="o1",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def summarize_intended_solution(self) -> list[ModelOption]:
        """Get model options for the summarize_intended_solution function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
            ),
            ModelOption(
                provider="openai",
                model_name="gpt-4o-2024-08-06",
            ),
        ]

    @cached_property
    def summarize_agent_actions(self) -> list[ModelOption]:
        """Get model options for the summarize_agent_actions function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort="low",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
                reasoning_effort="low",
            ),
            ModelOption(
                provider="openai",
                model_name="o1",
                reasoning_effort="low",
            ),
        ]

    @cached_property
    def group_actions_into_high_level_steps(self) -> list[ModelOption]:
        """Get model options for the group_actions_into_high_level_steps function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort="low",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
                reasoning_effort="low",
            ),
            ModelOption(
                provider="openai",
                model_name="o1",
                reasoning_effort="low",
            ),
        ]

    @cached_property
    def interesting_agent_observations(self) -> list[ModelOption]:
        """Get model options for the interesting_agent_observations function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="openai",
                model_name="o1",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def propose_clusters(self) -> list[ModelOption]:
        """Get model options for the propose_clusters function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
            ),
            ModelOption(
                provider="openai",
                model_name="gpt-4o-2024-08-06",
            ),
        ]

    @cached_property
    def refine_agent(self) -> list[ModelOption]:
        """Get model options for the refinement agent

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="openai",
                model_name="gpt-5",
                reasoning_effort="low",
            ),
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def execute_search(self) -> list[ModelOption]:
        """Get model options for the execute_search function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort=None,
            ),
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="openai",
                model_name="o1",
                reasoning_effort="low",
            ),
        ]

    @cached_property
    def cluster_assign_o3_mini(self) -> list[ModelOption]:
        """Get model options for the cluster_assign_o3-mini function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="openai",
                model_name="o3-mini",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def cluster_assign_o4_mini(self) -> list[ModelOption]:
        """Get model options for the cluster_assign_o4-mini function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="openai",
                model_name="o4-mini",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def cluster_assign_sonnet_4_thinking(self) -> list[ModelOption]:
        """Get model options for the cluster_assign_sonnet_4_thinking function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def cluster_assign_gemini_flash(self) -> list[ModelOption]:
        """Get model options for the cluster_assign_gemini_flash function.

        Returns:
                List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def handle_refinement_message(self) -> list[ModelOption]:
        """Get model options for the handle_refinement_message function.
        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="openai",
                model_name="gpt-5",
                reasoning_effort="low",
            ),
            # ModelOption(
            #     provider="openai",
            #     model_name="gpt-4.1",
            # ),
            # ModelOption(
            #     provider="anthropic",
            #     model_name="claude-sonnet-4-20250514",
            # ),
        ]

    @cached_property
    def default_judge_models(self) -> list[ModelOption]:
        """Judge models that any user can access without providing their own API key"""

        return [
            ModelOption(provider="openai", model_name="gpt-5", reasoning_effort="medium"),
            ModelOption(provider="openai", model_name="gpt-5", reasoning_effort="low"),
            ModelOption(provider="openai", model_name="gpt-5-mini", reasoning_effort="medium"),
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def byok_judge_models(self) -> list[ModelOption]:
        """Judge models that require a user to provide their own API key, e.g. because they're
        expensive, or our rate limits are low"""

        return [
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash",
                reasoning_effort="medium",
            ),
        ]


# Initialize the singleton preferences object
PROVIDER_PREFERENCES = ProviderPreferences()


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
