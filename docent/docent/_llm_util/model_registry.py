from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from docent._llm_util.data_models.llm_output import TokenType
from docent._log_util import get_logger

logger = get_logger(__name__)


"""
Values are USD per million tokens
"""
ModelRate = dict[TokenType, float]


@dataclass(frozen=True)
class ModelInfo:
    """
    Information about a model, including its rate and context window. Not to be confused with ModelOption.
    """

    # Values are per 1,000,000 tokens
    rate: Optional[ModelRate]
    # Total context window tokens
    context_window: int


# Note: some providers charge extra for long prompts/outputs. We don't account for this yet.
_REGISTRY: list[tuple[str, ModelInfo]] = [
    (
        "gpt-5-nano",
        ModelInfo(rate={"input": 0.05, "output": 0.40}, context_window=400_000),
    ),
    (
        "gpt-5-mini",
        ModelInfo(rate={"input": 0.25, "output": 2.0}, context_window=400_000),
    ),
    (
        "gpt-5",
        ModelInfo(rate={"input": 1.25, "output": 10.0}, context_window=400_000),
    ),
    (
        "gpt-4o",
        ModelInfo(rate={"input": 2.50, "output": 10.00}, context_window=100_000),
    ),
    (
        "o4-mini",
        ModelInfo(rate={"input": 1.10, "output": 4.40}, context_window=100_000),
    ),
    (
        "claude-sonnet-4",
        ModelInfo(rate={"input": 3.0, "output": 15.0}, context_window=200_000),
    ),
    (
        "claude-haiku-4-5",
        ModelInfo(rate={"input": 1.0, "output": 5.0}, context_window=200_000),
    ),
    (
        "gemini-2.5-flash-lite",
        ModelInfo(
            rate={"input": 0.10, "output": 0.40},
            context_window=1_000_000,
        ),
    ),
    (
        "gemini-2.5-flash",
        ModelInfo(
            rate={"input": 0.30, "output": 2.50},
            context_window=1_000_000,
        ),
    ),
    (
        "gemini-2.5-pro",
        ModelInfo(
            rate={"input": 1.25, "output": 10.00},
            context_window=1_000_000,
        ),
    ),
    (
        "grok-4-fast",
        ModelInfo(
            rate={"input": 0.20, "output": 0.50},
            context_window=2_000_000,
        ),
    ),
    (
        "grok-4",
        ModelInfo(
            rate={"input": 3.0, "output": 15.0},
            context_window=256_000,
        ),
    ),
]


@lru_cache(maxsize=None)
def get_model_info(model_name: str) -> Optional[ModelInfo]:
    for registry_model_name, info in _REGISTRY:
        if registry_model_name in model_name:
            return info
    return None


def get_context_window(model_name: str) -> int:
    info = get_model_info(model_name)
    if info is None:
        logger.warning(f"No context window found for model {model_name}")
        return 100_000
    return info.context_window


def get_rates_for_model_name(model_name: str) -> Optional[ModelRate]:
    info = get_model_info(model_name)
    return info.rate if info is not None else None


def estimate_cost_cents(model_name: str, token_count: int, token_type: TokenType) -> float:
    rate = get_rates_for_model_name(model_name)
    if rate is None:
        logger.warning(f"No rate found for model {model_name}")
        return 0.0
    usd_per_mtok = rate.get(token_type)
    if usd_per_mtok is None:
        logger.warning(f"No rate found for model {model_name} token type {token_type}")
        return 0.0
    cents_per_token = usd_per_mtok * 100 / 1_000_000.0
    return token_count * cents_per_token
