from __future__ import annotations

from functools import cached_property
from typing import Any, AsyncContextManager, Callable, Literal, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from docent._llm_util.data_models.exceptions import DocentUsageLimitException
from docent._llm_util.data_models.llm_output import (
    AsyncLLMOutputStreamingCallback,
    LLMOutput,
    TokenType,
)
from docent._llm_util.llm_svc import (
    DEFAULT_SVC_MAX_CONCURRENCY,
    BaseLLMService,
    MessagesInput,
)
from docent._llm_util.model_registry import estimate_cost_cents
from docent._llm_util.providers.preference_types import ModelOption, PublicProviderPreferences
from docent._log_util import get_logger
from docent.data_models.chat import ToolInfo
from docent.data_models.chat.response_format import ResponseFormat
from docent_core._env_util import ENV
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import SQLAModelApiKey
from docent_core.docent.services.usage import UsageService, check_spend_within_limit

logger = get_logger(__name__)


class LLMService(BaseLLMService):
    def __init__(
        self,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        user: User,
        usage_service: UsageService,
        max_concurrency: int = DEFAULT_SVC_MAX_CONCURRENCY,
    ):
        """The LLM service manages its own sessions"""

        super().__init__(max_concurrency)

        # Ensure environment variables are loaded before we get completions
        # This is only required because the backend relies on envvars to specify keys
        _ = ENV

        self.session_cm_factory = session_cm_factory
        self.user = user
        self.usage_service = usage_service

    async def _load_byok_keys(self) -> tuple[dict[str, str], dict[str, str]]:
        """Load user's saved BYOK keys from the database.

        Returns:
            A tuple of (api_key_overrides, saved_byok_ids) where:
            - api_key_overrides: provider -> api_key mapping for LLM client
            - saved_byok_ids: provider -> key_id mapping for usage attribution
        """
        async with self.session_cm_factory() as session:
            result = await session.execute(
                SQLAModelApiKey.__table__.select().where(SQLAModelApiKey.user_id == self.user.id)
            )
            rows = result.fetchall()

        provider_to_saved: dict[str, tuple[str, str]] = {}
        for r in rows:
            # Keep the first encountered key per provider
            if r.provider not in provider_to_saved:
                provider_to_saved[r.provider] = (r.id, r.api_key)

        # Build overrides for the LLM client and lookup for usage attribution
        api_key_overrides: dict[str, str] = {p: key for p, (_, key) in provider_to_saved.items()}
        saved_byok_ids: dict[str, str] = {p: id for p, (id, _) in provider_to_saved.items()}

        return api_key_overrides, saved_byok_ids

    def _create_usage_recording_callback(
        self,
        completion_callback: AsyncLLMOutputStreamingCallback | None,
        saved_byok_ids: dict[str, str],
        model_options: list[ModelOption],
        pending_usage_data: list[dict[str, Any]],
        pending_usage_cents_state: dict[str, float],
        initial_usage_cents: float,
    ) -> AsyncLLMOutputStreamingCallback:
        """Create a callback that collects usage data for deferred recording."""
        recorded_indices: set[int] = set()
        user_id = self.user.id

        async def usage_recording_callback(batch_index: int, llm_output: LLMOutput) -> None:
            try:
                if completion_callback is not None:
                    await completion_callback(batch_index, llm_output)
            finally:
                # Prevent double-counting: on partial failures the manager retries (model rotation)
                # and re-invokes the completion callback for every index on each iteration
                if batch_index in recorded_indices:
                    return
                recorded_indices.add(batch_index)

                # Skip cache hits for spend accounting
                if llm_output.from_cache:
                    return

                # Determine provider for this output by matching model_name
                provider_for_output: str | None = None
                for opt in model_options:
                    # Do `in` rather than `==` because llm_output.model might include a specific version
                    if opt.model_name in llm_output.model:
                        provider_for_output = opt.provider
                        break

                api_key_id: str | None = None
                if provider_for_output is not None:
                    api_key_id = saved_byok_ids.get(provider_for_output, None)

                # Collect usage data for deferred recording instead of immediate recording
                metrics_raw = llm_output.usage.to_dict()
                if metrics_raw:
                    metrics: dict[TokenType, int] = {k: int(v) for k, v in metrics_raw.items()}

                    # Track usage cost for real-time monitoring (only platform spend)
                    if api_key_id is None:
                        for metric_name, value in metrics.items():
                            cents = estimate_cost_cents(llm_output.model, value, metric_name)
                            pending_usage_cents_state["pending_usage_cents"] = (
                                pending_usage_cents_state.get("pending_usage_cents", 0.0) + cents
                            )

                    # Check usage limits in real-time
                    current_usage = initial_usage_cents + pending_usage_cents_state.get(
                        "pending_usage_cents", 0.0
                    )

                    usage_data = {
                        "user_id": user_id,
                        "api_key_id": api_key_id,
                        "model": {"model_name": llm_output.model, "provider": provider_for_output},
                        "metrics": metrics,
                    }
                    pending_usage_data.append(usage_data)

                    if not check_spend_within_limit(current_usage):
                        raise DocentUsageLimitException("Usage limit exceeded during operation")

        return usage_recording_callback

    async def _record_pending_usage(self, pending_usage_data: list[dict[str, Any]]) -> None:
        """Record all collected usage data after LLM processing completes."""
        try:
            for usage_data in pending_usage_data:
                await self.usage_service.upsert_usage(
                    user_id=usage_data["user_id"],
                    api_key_id=usage_data["api_key_id"],
                    model=usage_data["model"],
                    when=None,
                    metrics=usage_data["metrics"],
                )
            logger.info(f"Recorded {len(pending_usage_data)} usage records")
        except Exception as e:
            logger.error(f"Failed to record pending usage data: {e}")

    async def get_completions(
        self,
        *,
        inputs: Sequence[MessagesInput],
        model_options: list[ModelOption],
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        max_new_tokens: int = 1024,
        temperature: float = 1.0,
        logprobs: bool = False,
        top_logprobs: int | None = None,
        timeout: float = 120.0,
        streaming_callback: AsyncLLMOutputStreamingCallback | None = None,
        validation_callback: AsyncLLMOutputStreamingCallback | None = None,
        completion_callback: AsyncLLMOutputStreamingCallback | None = None,
        use_cache: bool = False,
        response_format: ResponseFormat | None = None,
        _api_key_overrides: dict[str, str] = dict(),
    ) -> list[LLMOutput]:
        if _api_key_overrides:
            raise ValueError(
                "api_key_overrides should not be provided to the LLMService.get_completions "
                "method, as they are computed in this function."
            )

        # Load user's saved BYOK keys
        _api_key_overrides, saved_byok_ids = await self._load_byok_keys()

        # Decide rate-limit gating and model option ordering
        providers_in_options = {opt.provider for opt in model_options}
        byok_providers = {p for p in providers_in_options if p in _api_key_overrides}
        platform_providers = providers_in_options - byok_providers

        # If we could end up using platform keys at all, enforce usage limits.
        # Per-call accumulators
        pending_usage_data: list[dict[str, Any]] = []
        pending_usage_cents_state: dict[str, float] = {"pending_usage_cents": 0.0}
        initial_usage_cents: float = 0.0

        if platform_providers:
            initial_usage_cents = await self.usage_service.get_free_spend_cents(self.user.id)
            if not check_spend_within_limit(initial_usage_cents):
                logger.error(f"Blocked request for user {self.user.email} due to usage limit")
                return [
                    LLMOutput(
                        model=model_options[0].model_name,
                        completions=[],
                        errors=[DocentUsageLimitException()],
                    )
                    for _ in inputs
                ]

        # Create usage recording callback
        usage_recording_callback = self._create_usage_recording_callback(
            completion_callback,
            saved_byok_ids,
            model_options,
            pending_usage_data,
            pending_usage_cents_state,
            initial_usage_cents,
        )

        outputs = await super().get_completions(
            inputs=inputs,
            model_options=model_options,
            tools=tools,
            tool_choice=tool_choice,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            logprobs=logprobs,
            top_logprobs=top_logprobs,
            timeout=timeout,
            streaming_callback=streaming_callback,
            validation_callback=validation_callback,
            completion_callback=usage_recording_callback,
            use_cache=use_cache,
            response_format=response_format,
            _api_key_overrides=_api_key_overrides,
        )

        # Record all collected usage data after LLM processing completes
        await self._record_pending_usage(pending_usage_data)

        return outputs


class ProviderPreferences(PublicProviderPreferences):
    """Manages model preferences for different docent functions.

    This class provides access to configured model options for each
    function that requires LLM capabilities in the docent system.
    """

    @cached_property
    def default_chat_models(self) -> list[ModelOption]:
        """Models that can be used for chat if the user does not provide their own API key."""
        return [
            ModelOption(
                provider="openai",
                model_name="gpt-5",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="openai",
                model_name="gpt-5",
                reasoning_effort="low",
            ),
            ModelOption(
                provider="openai",
                model_name="gpt-5",
                reasoning_effort="high",
            ),
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-5",
            ),
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-5",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-3-pro-preview",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-3-pro-preview",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-3-flash-preview",
            ),
            ModelOption(
                provider="google",
                model_name="gemini-3-flash-preview",
                reasoning_effort="medium",
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
            ModelOption(provider="openrouter", model_name="openai/gpt-5", reasoning_effort="low"),
            ModelOption(
                provider="openrouter", model_name="openai/gpt-5", reasoning_effort="medium"
            ),
            ModelOption(provider="openrouter", model_name="openai/gpt-5", reasoning_effort="high"),
            ModelOption(provider="openrouter", model_name="anthropic/claude-sonnet-4-5"),
            ModelOption(
                provider="openrouter",
                model_name="anthropic/claude-sonnet-4-5",
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
    def byok_judge_models(self) -> list[ModelOption]:
        """Judge models that require a user to provide their own API key, e.g. because they're
        expensive, or our rate limits are low"""

        return [
            ModelOption(
                provider="google",
                model_name="gemini-2.5-flash",
                reasoning_effort="medium",
            ),
            ModelOption(provider="openrouter", model_name="openai/gpt-5", reasoning_effort="low"),
            ModelOption(
                provider="openrouter", model_name="openai/gpt-5", reasoning_effort="medium"
            ),
            ModelOption(provider="openrouter", model_name="openai/gpt-5", reasoning_effort="high"),
            ModelOption(
                provider="openrouter",
                model_name="openai/gpt-5-mini",
                reasoning_effort="low",
            ),
            ModelOption(
                provider="openrouter",
                model_name="openai/gpt-5-mini",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="openrouter",
                model_name="openai/gpt-5-mini",
                reasoning_effort="high",
            ),
            ModelOption(
                provider="openrouter",
                model_name="anthropic/claude-sonnet-4-5",
                reasoning_effort="medium",
            ),
            ModelOption(
                provider="openrouter",
                model_name="minimax/minimax-m2",
            ),
            ModelOption(
                provider="openrouter",
                model_name="minimax/minimax-m2.1",
            ),
        ]

    @cached_property
    def judge_reflection(self) -> list[ModelOption]:
        """Get model options for the reflection agent
        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(provider="openai", model_name="gpt-5", reasoning_effort="low"),
            ModelOption(
                provider="google", model_name="gemini-3-flash-preview", reasoning_effort="low"
            ),
            ModelOption(
                provider="anthropic", model_name="claude-haiku-4-5", reasoning_effort="low"
            ),
        ]

    @cached_property
    def rubric_rewrite(self) -> list[ModelOption]:
        """Get model options for the rubric rewrite tool in the refinement agent.
        Returns:
            List of configured model options for this function.
        """
        return [
            ModelOption(provider="openai", model_name="gpt-5.1", reasoning_effort="low"),
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
                model_name="gpt-5.1",
                reasoning_effort="low",
            ),
        ]

    @cached_property
    def default_analysis_models(self) -> list[ModelOption]:
        return [
            ModelOption(provider="openai", model_name="gpt-5-mini", reasoning_effort="low"),
            ModelOption(
                provider="google",
                model_name="gemini-3-flash-preview",
            ),
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-5",
                reasoning_effort="medium",
            ),
        ]


# Initialize the singleton preferences object
PROVIDER_PREFERENCES = ProviderPreferences()
