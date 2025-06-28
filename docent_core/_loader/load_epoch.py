from typing import Any

from docent.data_models.agent_run import AgentRun
from docent_core._loader.load_inspect import load_inspect_eval

LOG_DIR_PREFIX = "/home/ubuntu/artifacts/vincent/epoch"

AIME_DIR_PREFIX = f"{LOG_DIR_PREFIX}/mock-aime"

SWE_DIR_PREFIX = f"{LOG_DIR_PREFIX}/swe-bench-verified"

MOCK_AIME_LOGS: dict[str, str | tuple[str, dict[str, Any]]] = {
    "DeepSeek-R1": f"{AIME_DIR_PREFIX}/DeepSeek-R1.eval",
    "DeepSeek-V3-0324": f"{AIME_DIR_PREFIX}/DeepSeek-V3-0324.eval",
    "DeepSeek-V3": f"{AIME_DIR_PREFIX}/DeepSeek-V3.eval",
    "Llama-3.1-405B-Instruct": f"{AIME_DIR_PREFIX}/Llama-3.1-405B-Instruct.eval",
    "Llama-4-Maverick-17B-128E-Instruct-FP8": f"{AIME_DIR_PREFIX}/Llama-4-Maverick-17B-128E-Instruct-FP8.eval",
    "claude-3-5-sonnet-20240620": f"{AIME_DIR_PREFIX}/claude-3-5-sonnet-20240620.eval",
    "claude-3-5-sonnet-20241022": f"{AIME_DIR_PREFIX}/claude-3-5-sonnet-20241022.eval",
    "claude-3-7-sonnet-20250219_16K": f"{AIME_DIR_PREFIX}/claude-3-7-sonnet-20250219_16K.eval",
    "claude-3-7-sonnet-20250219_32K": f"{AIME_DIR_PREFIX}/claude-3-7-sonnet-20250219_32K.eval",
    "claude-3-opus-20240229": f"{AIME_DIR_PREFIX}/claude-3-opus-20240229.eval",
    "gemini-1.5-pro-002": f"{AIME_DIR_PREFIX}/gemini-1.5-pro-002.eval",
    "gemini-2.0-flash-thinking-exp-01-21": f"{AIME_DIR_PREFIX}/gemini-2.0-flash-thinking-exp-01-21.eval",
    "gemma-3-27b-it": f"{AIME_DIR_PREFIX}/gemma-3-27b-it.eval",
    "gpt-4.5-preview-2025-02-27": f"{AIME_DIR_PREFIX}/gpt-4.5-preview-2025-02-27.eval",
    "grok-3-mini-beta_high": f"{AIME_DIR_PREFIX}/grok-3-mini-beta_high.eval",
    "grok-3-mini-beta_low": f"{AIME_DIR_PREFIX}/grok-3-mini-beta_low.eval",
    "o4-mini-2025-04-16_high": f"{AIME_DIR_PREFIX}/o4-mini-2025-04-16_high.eval",
    "phi-4": f"{AIME_DIR_PREFIX}/phi-4.eval",
    "qwen-max-2025-01-25": f"{AIME_DIR_PREFIX}/qwen-max-2025-01-25.eval",
}

SWE_BENCH_LOGS: dict[str, str | tuple[str, dict[str, Any]]] = {
    "gpt-4o-2024-11-20": f"{SWE_DIR_PREFIX}/gpt-4o-2024-11-20.eval",
    "o3-mini-medium": f"{SWE_DIR_PREFIX}/o3-mini-medium.eval",
    "sonnet-3.6": f"{SWE_DIR_PREFIX}/sonnet-3.6.eval",
    "sonnet-3.7_16K": f"{SWE_DIR_PREFIX}/sonnet-3.7_16K.eval",
    "sonnet-3.7_32K": f"{SWE_DIR_PREFIX}/sonnet-3.7_32K.eval",
}


def load_epoch_aime() -> list[AgentRun]:
    """Loads AIME benchmark transcripts.

    Returns:
        A list of AgentRun objects.
    """
    return load_inspect_eval(MOCK_AIME_LOGS)


def load_epoch_swebench() -> list[AgentRun]:
    """Loads SWE-Bench transcripts.

    Returns:
        A list of AgentRun objects.
    """
    return load_inspect_eval(SWE_BENCH_LOGS)
