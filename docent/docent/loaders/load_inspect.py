import json
from pathlib import Path
from typing import Any, BinaryIO, Generator, Tuple
from zipfile import ZipFile

from inspect_ai.log import EvalLog
from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, PARTIAL, Score

from docent._log_util.logger import get_logger
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message

logger = get_logger(__name__)


def _normalize_inspect_score(score: Score | dict[str, Any]) -> Any:
    """
    Normalize an inspect score to a float. Logic mirrors inspect_ai.scorer._metric.value_to_float.

    Args:
        score: The inspect score to normalize.

    Returns:
        The normalized score as a float, or None if the score is not a valid value.
    """

    def _leaf_normalize(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, int | float | bool):
            return float(value)
        if value == CORRECT:
            return 1.0
        if value == PARTIAL:
            return 0.5
        if value in [INCORRECT, NOANSWER]:
            return 0
        value = str(value).lower()
        if value in ["yes", "true"]:
            return 1.0
        if value in ["no", "false"]:
            return 0.0
        if value.replace(".", "").isnumeric():
            return float(value)
        return value

    if isinstance(score, dict):
        value = score["value"]
    else:
        value = score.value

    if isinstance(value, int | float | bool | str):
        return _leaf_normalize(value)
    if isinstance(value, list):
        return [_leaf_normalize(v) for v in value]  # type: ignore
    assert isinstance(value, dict), "Inspect score must be leaf value, list, or dict"
    return {k: _leaf_normalize(v) for k, v in value.items()}  # type: ignore


def load_inspect_log(log: EvalLog) -> list[AgentRun]:
    if log.samples is None:
        return []

    # TODO(vincent): fix this
    agent_runs: list[AgentRun] = []

    for s in log.samples:
        sample_id = s.id
        epoch_id = s.epoch

        if s.scores is None:
            sample_scores = {}
        else:
            sample_scores = {k: _normalize_inspect_score(v) for k, v in s.scores.items()}

        metadata = {
            "task_id": log.eval.task,
            "sample_id": str(sample_id),
            "epoch_id": epoch_id,
            "model": log.eval.model,
            "additional_metadata": s.metadata,
            "scores": sample_scores,
            # Scores could have answers, explanations, and other metadata besides the values we extract
            "scoring_metadata": s.scores,
        }

        agent_runs.append(
            AgentRun(
                transcripts={
                    "main": Transcript(
                        messages=[parse_chat_message(m.model_dump()) for m in s.messages],
                        metadata={},
                    )
                },
                metadata=metadata,
            )
        )

    return agent_runs


def _read_sample_as_run(data: dict[str, Any], header_metadata: dict[str, Any] = {}) -> AgentRun:
    if "scores" in data:
        normalized_scores = {k: _normalize_inspect_score(v) for k, v in data["scores"].items()}
    else:
        normalized_scores = {}

    if "metadata" in data:
        sample_metadata = data["metadata"]
    else:
        sample_metadata = {}

    run_metadata: dict[str, Any] = {
        "sample_id": data.get("id"),
        "epoch": data.get("epoch"),
        "target": data.get("target"),
        # Scores could have answers, explanations, and other metadata besides the values we extract
        "scoring_metadata": data.get("scores"),
        "scores": normalized_scores,
        # If a key exists in header and sample, sample takes precedence
        **header_metadata,
        **sample_metadata,
    }

    run = AgentRun(
        transcripts={
            "main": Transcript(
                messages=[parse_chat_message(m) for m in data["messages"]], metadata={}
            ),
        },
        metadata=run_metadata,
    )
    return run


def _run_metadata_from_header(header: dict[str, Any]) -> dict[str, Any]:
    """
    Inspect logs often have a lot of metadata.
    This function tries to get the most important stuff without adding clutter.
    """
    m: dict[str, Any] = {}
    if e := header.get("eval"):
        m["task"] = e["task"]
        m["model"] = e["model"]
    return m


def get_total_samples(file_path: Path, format: str = "json") -> int:
    """Return the total number of samples in the provided file."""
    with open(file_path, "rb") as f:
        if format == "json":
            data = json.load(f)
            return len(data.get("samples", []))
        elif format == "eval":
            z = ZipFile(f, mode="r")
            try:
                return sum(
                    1
                    for name in z.namelist()
                    if name.startswith("samples/") and name.endswith(".json")
                )
            finally:
                z.close()
        else:
            raise ValueError(f"Format must be 'json' or 'eval': {format}")


def _runs_from_eval_file(
    file: BinaryIO,
) -> Tuple[dict[str, Any], Generator[AgentRun, None, None]]:
    zip = ZipFile(file, mode="r")
    try:
        header: dict[str, Any] = json.load(zip.open("header.json", "r"))
        header_metadata = _run_metadata_from_header(header)
    except KeyError:
        logger.warning(f"No header found in {file.name} file")
        header_metadata = {}

    def _iter_runs() -> Generator[AgentRun, None, None]:
        try:
            for sample_file in zip.namelist():
                if not (sample_file.startswith("samples/") and sample_file.endswith(".json")):
                    continue
                with zip.open(sample_file, "r") as f:
                    data = json.load(f)
                run: AgentRun = _read_sample_as_run(data, header_metadata)
                yield run
        finally:
            zip.close()

    return header_metadata, _iter_runs()


def _runs_from_json_file(
    file: BinaryIO,
) -> Tuple[dict[str, Any], Generator[AgentRun, None, None]]:
    data = json.load(file)
    header_metadata = _run_metadata_from_header(data)

    def _iter_runs() -> Generator[AgentRun, None, None]:
        for sample in data["samples"]:
            run: AgentRun = _read_sample_as_run(sample, header_metadata)
            yield run

    return header_metadata, _iter_runs()


def runs_from_file(
    file: BinaryIO, format: str = "json"
) -> Tuple[dict[str, Any], Generator[AgentRun, None, None]]:
    if format == "json":
        result = _runs_from_json_file(file)
    elif format == "eval":
        result = _runs_from_eval_file(file)
    else:
        raise ValueError(f"Format must be 'json' or 'eval': {format}")
    return result
