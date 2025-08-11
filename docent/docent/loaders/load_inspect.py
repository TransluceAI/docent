from typing import Any

from inspect_ai.log import EvalLog
from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, PARTIAL, Score

from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message


def _normalize_inspect_score(score: Score) -> Any:
    """
    Normalize an inspect score to a float. This implements the same logic as inspect_ai.scorer._metric.value_to_float, but fails more conspicuously.

    Args:
        score: The inspect score to normalize.

    Returns:
        The normalized score as a float, or None if the score is not a valid value.
    """

    def _leaf_normalize(value: int | float | bool | str | None) -> float | str | None:
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

    if isinstance(score.value, int | float | bool | str):
        return _leaf_normalize(score.value)
    if isinstance(score.value, list):
        return [_leaf_normalize(v) for v in score.value]
    assert isinstance(score.value, dict), "Inspect score must be leaf value, list, or dict"
    return {k: _leaf_normalize(v) for k, v in score.value.items()}


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
