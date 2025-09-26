from __future__ import annotations

from typing import Any, AsyncContextManager, Callable, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models.chat import ToolInfo
from docent_core._llm_util.data_models.exceptions import DocentUsageLimitException
from docent_core._llm_util.data_models.llm_output import (
    AsyncLLMOutputStreamingCallback,
    LLMOutput,
    TokenType,
)
from docent_core._llm_util.model_registry import estimate_cost_cents
from docent_core._llm_util.prod_llms import MessagesInput, get_llm_completions_async
from docent_core._llm_util.providers.preferences import ModelOption
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import SQLAModelApiKey
from docent_core.docent.services.usage import (
    UsageService,
    check_spend_within_limit,
)

logger = get_logger(__name__)


class LLMService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        user: User,
        usage_service: UsageService,
    ):
        self.session = session
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
        result = await self.session.execute(
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
            if completion_callback is not None:
                await completion_callback(batch_index, llm_output)

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
        inputs: list[MessagesInput],
        model_options: list[ModelOption],
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        max_new_tokens: int = 1024,
        temperature: float = 1.0,
        logprobs: bool = False,
        top_logprobs: int | None = None,
        max_concurrency: int = 100,
        timeout: float = 120.0,
        streaming_callback: AsyncLLMOutputStreamingCallback | None = None,
        completion_callback: AsyncLLMOutputStreamingCallback | None = None,
        use_cache: bool = False,
    ) -> list[LLMOutput]:
        # Load user's saved BYOK keys
        api_key_overrides, saved_byok_ids = await self._load_byok_keys()

        # Decide rate-limit gating and model option ordering
        providers_in_options = {opt.provider for opt in model_options}
        byok_providers = {p for p in providers_in_options if p in api_key_overrides}
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

        outputs = await get_llm_completions_async(
            inputs=inputs,
            model_options=model_options,
            tools=tools,
            tool_choice=tool_choice,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            logprobs=logprobs,
            top_logprobs=top_logprobs,
            max_concurrency=max_concurrency,
            timeout=timeout,
            streaming_callback=streaming_callback,
            completion_callback=usage_recording_callback,
            use_cache=use_cache,
            api_key_overrides=api_key_overrides,
        )

        # Record all collected usage data after LLM processing completes
        await self._record_pending_usage(pending_usage_data)

        return outputs
