from typing import Any

from inspect_ai.log import read_eval_log

from docent._frames.transcript import Transcript, TranscriptMetadata
from docent._log_util import get_logger

logger = get_logger(__name__)

LOG_DIR_PREFIX = "/Users/mengk/Code/luce-artifacts/mengk/inspect_logs"

PICOCTF_LOGS_4o: dict[str, str | tuple[str, dict[str, Any]]] = {
    "improved_scaffold": f"{LOG_DIR_PREFIX}/intercode-4o-improved-scaffold.eval",
    "default_scaffold": f"{LOG_DIR_PREFIX}/intercode-4o-default-scaffold.eval",
    # PicoCTF interventions
    "picoctf-55": (
        f"{LOG_DIR_PREFIX}/picoctf-55.eval",
        {
            "intervention_index": 8,
            "intervention_description": "Provide numbers from the image",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
    "picoctf-69": (
        f"{LOG_DIR_PREFIX}/picoctf-69-math.eval",
        {
            "intervention_index": 8,
            "intervention_description": "Ask agent to think harder about the RSA equation",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
    "picoctf-71": (
        f"{LOG_DIR_PREFIX}/picoctf-71-look-at-hidden.eval",
        {
            "intervention_index": 6,
            "intervention_description": "Ask agent to look at the hidden file",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
    "picoctf-70-mount": (
        f"{LOG_DIR_PREFIX}/picoctf-77-mount.eval",
        {
            "intervention_index": 8,
            "intervention_description": "Tell agent to mount with `fls`",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
    "picoctf-70-slack": (
        f"{LOG_DIR_PREFIX}/picoctf-77-slack.eval",
        {
            "intervention_index": 13,
            "intervention_description": "Hint about slack space in a disk",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
    "picoctf-47-encoding": (
        f"{LOG_DIR_PREFIX}/picoctf-47-encoding.eval",
        {
            "intervention_index": 0,
            "intervention_description": "Encourage agent to consider different possible encodings",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
    "picoctf-79-1": (
        f"{LOG_DIR_PREFIX}/picoctf-79-1.eval",
        {
            "intervention_index": 6,
            "intervention_description": "Print `pairs_gcd` which the agent forgot to print",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
    "picoctf-79-2": (
        f"{LOG_DIR_PREFIX}/picoctf-79-2.eval",
        {
            "intervention_index": 8,
            "intervention_description": "Add variables that the agent dropped",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
    "picoctf-79-3": (
        f"{LOG_DIR_PREFIX}/picoctf-79-3.eval",
        {
            "intervention_index": 10,
            "intervention_description": "Add variables that the agent dropped",
            "intervention_timestamp": "2025-03-22T16:00:00Z",
        },
    ),
}
PICOCTF_LOGS_36: dict[str, str | tuple[str, dict[str, Any]]] = {
    "intercode_sonnet": f"{LOG_DIR_PREFIX}/2025-03-17T01-22-21+00-00_luce-intercode-ctf_96JiiMbkhiX9ELHCgCxj3v.eval",
    "intercode_sonnet_new": f"{LOG_DIR_PREFIX}/sonnet-36-pico.eval",
}
AGENTHARM_LOGS: dict[str, str | tuple[str, dict[str, Any]]] = {
    "agentharm_sonnet35": f"{LOG_DIR_PREFIX}/2025-03-17T01-22-50+00-00_agentharm_ZBeMFNAyBaXovmmrXUmyDD.eval",
}
CYBENCH_LOGS: dict[str, str | tuple[str, dict[str, Any]]] = {
    "ctf_cybench_full": f"{LOG_DIR_PREFIX}/2025-02-19T09-52-46+00-00_cybench_RF6ADFv3MANhLzyumkmwj9.eval",
    "modified": f"{LOG_DIR_PREFIX}/../../vincent/inspect/2025-03-05T18-44-51+00-00_cybench_aYxifNsGgP32WnRxNGpJ6X.eval",
}
K8S_LOGS: dict[str, str | tuple[str, dict[str, Any]]] = {
    "k8s": f"{LOG_DIR_PREFIX}/2025-03-16T18-58-16+00-00_k8s-infra-sabotage-simple_4B4d47GQ6DGuuaDSXyavNZ.eval"
}

FRONTIER_MATH_LOGS: dict[str, str | tuple[str, dict[str, Any]]] = {
    "frontier-math-o3-mini-high": f"{LOG_DIR_PREFIX}/JJqAHUs8LTLCKhnTWQUVTi.eval",
    "frontier-math-sonnet-3-7": f"{LOG_DIR_PREFIX}/Rfy7A5TbRK343mTyQkeGt7.eval",
}

SWE_BENCH_LOGS: dict[str, str | tuple[str, dict[str, Any]]] = {
    # "swebench-sonnet37-old": f"/home/ubuntu/artifacts/vincent/swe_bench_logs/2025-04-09T21-09-59+00-00_swe-bench_8AcW4AHxbhgtoqEbe5FQcT.eval",
    # "swebench-sonnet37-new": f"/home/ubuntu/artifacts/vincent/swe_bench_logs/2025-04-10T21-39-15+00-00_swe-bench_TZrCQjagGBxzuSrXnE3fqj.eval",
    "swebench-sonnet37-tools": "/home/ubuntu/clarity/logs/2025-04-15T00-09-38+00-00_swe-bench_NzHKupvJR28drNXGB63DEM.eval",
}


def load_inspect_experiment(
    experiment_id: str,
    fpath: str,
    only_epoch_1: bool = False,
    only_epoch_1_5: bool = False,
    _custom_metadata: dict[str, Any] | None = None,
) -> list[Transcript]:
    """Loads transcripts from Inspect AI evaluation logs.

    Args:
        experiment_id: The ID of the experiment.
        fpath: The path to the evaluation log file.
        only_epoch_1: If True, only load transcripts from epoch 1.
        only_epoch_1_5: If True, only load transcripts from epochs 1-5.
        _custom_metadata: Optional dictionary containing custom metadata like
            intervention details.

    Returns:
        A list of Transcript objects.
    """
    logger.info("Loading %s from %s", experiment_id, fpath)

    logs = read_eval_log(fpath)
    if logs.samples is None:
        return []

    transcripts: list[Transcript] = []

    for s in logs.samples:
        # Extract sample_id from the sample ID
        sample_id = s.id
        epoch_id = s.epoch

        # Skip conditions
        if only_epoch_1 and epoch_id != 1:
            continue
        if only_epoch_1_5 and not 1 <= epoch_id <= 5:
            continue

        # Gather scores
        scores: dict[str, int | float | bool] = {}
        default_score_key: str | None = None

        # Evaluate correctness (CTF)
        if s.scores and "includes" in s.scores:
            scores["correct"] = s.scores["includes"].value == "C"
            default_score_key = "correct"
        # Evaluate harmfulness (AgentHarm)
        if s.scores and "combined_scorer" in s.scores:
            scores["harmfulness"] = round(float(s.scores["combined_scorer"].value["score"]), 3)  # type: ignore
            scores["refusal"] = round(float(s.scores["combined_scorer"].value["refusal"]), 3)  # type: ignore
            default_score_key = "harmfulness"
        # Evaluate verification code (Frontier Math)
        if s.scores and "verification_code" in s.scores:
            scores["correct"] = s.scores["verification_code"].value == "C"
            default_score_key = "correct"
        # SWE-Bench scoring
        if s.scores and "swe_bench_scorer" in s.scores:
            scores["correct"] = s.scores["swe_bench_scorer"].value == 1.0
            default_score_key = "correct"
        #  Mock AIME scoring
        if s.scores and "model_graded" in s.scores:
            scores["correct"] = s.scores["model_graded"].value == "C"
            default_score_key = "correct"
        # Set metadata
        metadata = TranscriptMetadata(
            task_id=logs.eval.task,
            sample_id=str(sample_id),
            original_sample_id_type="str" if isinstance(sample_id, str) else "int",
            epoch_id=epoch_id,
            experiment_id=experiment_id,
            intervention_description=(_custom_metadata or {}).get("intervention_description"),
            intervention_timestamp=(_custom_metadata or {}).get("intervention_timestamp"),
            intervention_index=(_custom_metadata or {}).get("intervention_index"),
            model=logs.eval.model,
            task_args=logs.eval.task_args,
            is_loading_messages=False,
            scores=scores,
            default_score_key=default_score_key,
            additional_metadata=s.metadata,
            scoring_metadata=s.scores,
        )

        # Create transcript
        transcript = Transcript(
            messages=s.messages,
            metadata=metadata,
        )

        transcripts.append(transcript)

    return transcripts


def load_inspect_eval(logs: dict[str, str | tuple[str, dict[str, Any]]]) -> list[Transcript]:
    result: list[Transcript] = []

    for experiments_id, extra_metadata in logs.items():
        # Parse arguments in the dict
        if isinstance(extra_metadata, tuple):
            fpath, intervention_metadata = extra_metadata
        else:
            fpath = extra_metadata
            intervention_metadata = None

        result.extend(
            load_inspect_experiment(
                experiments_id,
                fpath,
                _custom_metadata=intervention_metadata,
            )
        )

    return result


def load_picoctf_4o() -> list[Transcript]:
    return load_inspect_eval(PICOCTF_LOGS_4o)


def load_picoctf_36() -> list[Transcript]:
    return load_inspect_eval(PICOCTF_LOGS_36)


def load_agentharm() -> list[Transcript]:
    return load_inspect_eval(AGENTHARM_LOGS)


def load_cybench() -> list[Transcript]:
    return load_inspect_eval(CYBENCH_LOGS)


def load_k8s() -> list[Transcript]:
    return load_inspect_eval(K8S_LOGS)


def load_swebench() -> list[Transcript]:
    return load_inspect_eval(SWE_BENCH_LOGS)


def load_frontier_math() -> list[Transcript]:
    return load_inspect_eval(FRONTIER_MATH_LOGS)
