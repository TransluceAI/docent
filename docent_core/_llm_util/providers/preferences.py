"""Provides configurable preferences for Docent LLM calls."""

from functools import cached_property
from typing import Literal, cast

from pydantic import BaseModel

from docent._log_util import get_logger
from docent_core._env_util import ENV

logger = get_logger(__name__)

DEEPSEEK_PROVIDER = "deepseek"
CUSTOM_PROVIDER = "custom"
DEEPSEEK_FLASH_MODEL = "deepseek-v4-flash"
DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"
DEFAULT_CONTEXT_WINDOW = 1_000_000

# Global mapping of model names to their context window sizes (in tokens).
MODEL_CONTEXT_WINDOWS = {
    DEEPSEEK_FLASH_MODEL: 1_000_000,
    DEEPSEEK_PRO_MODEL: 1_000_000,
}


class ModelOption(BaseModel):
    """Configuration for a specific model from a provider."""

    provider: str
    model_name: str
    reasoning_effort: Literal["low", "medium", "high"] | None = None


class ModelOptionWithContext(BaseModel):
    """Enhanced model option that includes context window information for frontend use."""

    provider: str
    model_name: str
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    context_window: int
    uses_byok: bool

    @classmethod
    def from_model_option(
        cls, model_option: ModelOption, uses_byok: bool = False
    ) -> "ModelOptionWithContext":
        context_window = get_context_window(model_option.model_name)

        return cls(
            provider=model_option.provider,
            model_name=model_option.model_name,
            reasoning_effort=model_option.reasoning_effort,
            context_window=context_window,
            uses_byok=uses_byok,
        )


def _env_value(name: str, default: str | None = None) -> str | None:
    value = ENV.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_reasoning_effort(
    name: str,
    default: Literal["low", "medium", "high"] | None,
) -> Literal["low", "medium", "high"] | None:
    value = _env_value(name)
    if value is None:
        return default
    if value not in {"low", "medium", "high"}:
        logger.warning(
            "Ignoring invalid %s=%s. Expected one of: low, medium, high.",
            name,
            value,
        )
        return default
    return cast(Literal["low", "medium", "high"], value)


def get_configured_llm_provider() -> str:
    provider = _env_value("DOCENT_LLM_PROVIDER", DEEPSEEK_PROVIDER)
    assert provider is not None
    return provider


def get_supported_model_api_key_providers() -> list[str]:
    return sorted({DEEPSEEK_PROVIDER, CUSTOM_PROVIDER, get_configured_llm_provider()})


def get_flash_model() -> str:
    model = _env_value("DOCENT_LLM_FLASH_MODEL", DEEPSEEK_FLASH_MODEL)
    assert model is not None
    return model


def get_pro_model() -> str:
    model = _env_value("DOCENT_LLM_PRO_MODEL", DEEPSEEK_PRO_MODEL)
    assert model is not None
    return model


def get_context_window(model_name: str) -> int:
    for prefix, context_window in MODEL_CONTEXT_WINDOWS.items():
        if model_name.startswith(prefix):
            return context_window

    raw_context_window = _env_value("DOCENT_LLM_CONTEXT_WINDOW", str(DEFAULT_CONTEXT_WINDOW))
    assert raw_context_window is not None
    try:
        return int(raw_context_window)
    except ValueError:
        logger.warning(
            "Ignoring invalid DOCENT_LLM_CONTEXT_WINDOW=%s. Using %s.",
            raw_context_window,
            DEFAULT_CONTEXT_WINDOW,
        )
        return DEFAULT_CONTEXT_WINDOW


def _model_option(
    model_env: str,
    default_model: str,
    default_reasoning_effort: Literal["low", "medium", "high"] | None,
) -> ModelOption:
    model_name = _env_value(model_env, default_model)
    assert model_name is not None
    return ModelOption(
        provider=get_configured_llm_provider(),
        model_name=model_name,
        reasoning_effort=_env_reasoning_effort(
            f"{model_env}_REASONING_EFFORT", default_reasoning_effort
        ),
    )


def _flash_option(
    model_env: str,
    default_reasoning_effort: Literal["low", "medium", "high"] | None = "low",
) -> ModelOption:
    return _model_option(model_env, get_flash_model(), default_reasoning_effort)


def _pro_option(
    model_env: str,
    default_reasoning_effort: Literal["low", "medium", "high"] | None = "medium",
) -> ModelOption:
    return _model_option(model_env, get_pro_model(), default_reasoning_effort)


class ProviderPreferences(BaseModel):
    """Manages provider/model preferences for Docent LLM capabilities."""

    @cached_property
    def default_chat_models(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_CHAT_MODEL", "medium")]

    @cached_property
    def byok_chat_models(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_CHAT_MODEL", "medium")]

    @cached_property
    def generate_new_queries(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_GENERATE_QUERIES_MODEL", "medium")]

    @cached_property
    def summarize_intended_solution(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_SUMMARIZE_INTENDED_SOLUTION_MODEL", "medium")]

    @cached_property
    def summarize_agent_actions(self) -> list[ModelOption]:
        return [_flash_option("DOCENT_LLM_SUMMARIZE_AGENT_ACTIONS_MODEL", "low")]

    @cached_property
    def hodoscope_action_summaries(self) -> list[ModelOption]:
        return [_flash_option("DOCENT_LLM_HODOSCOPE_ACTION_SUMMARY_MODEL", "low")]

    @cached_property
    def group_actions_into_high_level_steps(self) -> list[ModelOption]:
        return [_flash_option("DOCENT_LLM_GROUP_ACTIONS_MODEL", "low")]

    @cached_property
    def interesting_agent_observations(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_OBSERVATIONS_MODEL", "medium")]

    @cached_property
    def propose_clusters(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_CLUSTER_MODEL", "medium")]

    @cached_property
    def refine_agent(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_REFINE_MODEL", "medium")]

    @cached_property
    def execute_search(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_SEARCH_MODEL", "medium")]

    @cached_property
    def cluster_assign_o3_mini(self) -> list[ModelOption]:
        return [_flash_option("DOCENT_LLM_CLUSTER_ASSIGN_MODEL", "medium")]

    @cached_property
    def cluster_assign_o4_mini(self) -> list[ModelOption]:
        return [_flash_option("DOCENT_LLM_CLUSTER_ASSIGN_MODEL", "medium")]

    @cached_property
    def cluster_assign_sonnet_4_thinking(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_CLUSTER_ASSIGN_STRONG_MODEL", "medium")]

    @cached_property
    def cluster_assign_gemini_flash(self) -> list[ModelOption]:
        return [_flash_option("DOCENT_LLM_CLUSTER_ASSIGN_MODEL", "medium")]

    @cached_property
    def handle_refinement_message(self) -> list[ModelOption]:
        return [_pro_option("DOCENT_LLM_REFINEMENT_MESSAGE_MODEL", "medium")]

    @cached_property
    def default_judge_models(self) -> list[ModelOption]:
        return [
            _pro_option("DOCENT_LLM_JUDGE_MODEL", "medium"),
            _flash_option("DOCENT_LLM_JUDGE_FALLBACK_MODEL", "medium"),
        ]

    @cached_property
    def byok_judge_models(self) -> list[ModelOption]:
        return [
            _pro_option("DOCENT_LLM_JUDGE_MODEL", "medium"),
            _flash_option("DOCENT_LLM_JUDGE_FALLBACK_MODEL", "medium"),
        ]


PROVIDER_PREFERENCES = ProviderPreferences()


def merge_models_with_byok(
    defaults: list[ModelOption],
    byok: list[ModelOption],
    api_keys: dict[str, str] | None,
) -> list[ModelOptionWithContext]:
    user_keys = api_keys or {}

    merged: dict[tuple[str, str, str | None], ModelOption] = {}
    for model in [*defaults, *[m for m in byok if m.provider in user_keys]]:
        merged[(model.provider, model.model_name, model.reasoning_effort)] = model

    return [
        ModelOptionWithContext.from_model_option(model, model.provider in user_keys)
        for model in merged.values()
    ]
