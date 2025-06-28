"""Provides preferences of which LLM models to use for different Docent functions."""

from functools import cached_property
from typing import Literal

from pydantic import BaseModel


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


class ProviderPreferences(BaseModel):
    """Manages model preferences for different docent functions.

    This class provides access to configured model options for each
    function that requires LLM capabilities in the docent system.
    """

    @cached_property
    def handle_ta_message(self) -> list[ModelOption]:
        """Get model options for the handle_ta_message function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-3-7-sonnet-20250219",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash-preview-05-20",
            ),
            ModelOption(
                provider="openai",
                model_name="o1",
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
                model_name="claude-3-7-sonnet-20250219",
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
                model_name="claude-3-7-sonnet-20250219",
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
                model_name="claude-3-7-sonnet-20250219",
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
                model_name="claude-3-7-sonnet-20250219",
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
                model_name="claude-3-7-sonnet-20250219",
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
                model_name="claude-3-7-sonnet-20250219",
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
    def execute_search(self) -> list[ModelOption]:
        """Get model options for the execute_search function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-3-7-sonnet-20250219",
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
    def execute_search_paired(self) -> list[ModelOption]:
        """Get model options for the execute_search_paired function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="openai",
                model_name="o3",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="anthropic",
                model_name="claude-3-7-sonnet-20250219",
                reasoning_effort="medium",
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
    def cluster_assign_sonnet_37_thinking(self) -> list[ModelOption]:
        """Get model options for the cluster_assign_sonnet-37-thinking function.

        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-3-7-sonnet-20250219",
                reasoning_effort="medium",
            ),
        ]

    @cached_property
    def compare_transcripts(self) -> list[ModelOption]:
        """Get model options for the compare_transcripts function.

        Returns:
                List of configured model options for this function.
        """
        return [
            ModelOption(
                provider="anthropic",
                model_name="claude-3-7-sonnet-20250219",
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


# Initialize the singleton preferences object
PROVIDER_PREFERENCES = ProviderPreferences()
