"""Helpers for running judges across stored agent runs and persisting results."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from docent._llm_util.data_models.simple_svc import BaseLLMService
from docent.data_models.agent_run import AgentRun
from docent.judges import BaseJudge
from docent_core.docent.ai_tools.rubric.rubric import (
    JudgeSweepRow,
    evaluate_rubrics,
    evaluate_rubrics_to_file,
)


def _extract_shared_llm_service(judges: Sequence[BaseJudge]) -> BaseLLMService:
    if not judges:
        raise ValueError("judges must be a non-empty sequence")

    first_llm_svc = judges[0].llm_svc
    for judge in judges[1:]:
        if judge.llm_svc is not first_llm_svc:
            raise ValueError("all judges must share the same llm service instance")
    return first_llm_svc


async def run_judges(
    judges: Sequence[BaseJudge],
    agent_runs: Sequence[AgentRun],
    *,
    max_concurrent_llm_calls: int = 100,
    max_parallel_judges: int | None = None,
    show_judge_progress: bool = True,
    show_agent_progress: bool = False,
) -> list[JudgeSweepRow]:
    """Thin wrapper that delegates to the consolidated rubric utilities."""

    llm_svc = _extract_shared_llm_service(judges)
    rubrics = [judge.cfg for judge in judges]

    return await evaluate_rubrics(
        rubrics,
        agent_runs,
        llm_svc,
        max_concurrent_llm_calls=max_concurrent_llm_calls,
        max_parallel_rubrics=max_parallel_judges,
        show_rubric_progress=show_judge_progress,
        show_agent_progress=show_agent_progress,
    )


async def run_judges_to_file(
    judges: Sequence[BaseJudge],
    agent_runs: Sequence[AgentRun],
    output_path: Path,
    *,
    max_concurrent_llm_calls: int = 100,
    max_parallel_judges: int | None = None,
    show_judge_progress: bool = True,
    show_agent_progress: bool = False,
) -> list[JudgeSweepRow]:
    """Run judges and persist the flattened results to JSON via rubric helpers."""

    llm_svc = _extract_shared_llm_service(judges)
    rubrics = [judge.cfg for judge in judges]

    return await evaluate_rubrics_to_file(
        rubrics,
        agent_runs,
        llm_svc,
        output_path,
        max_concurrent_llm_calls=max_concurrent_llm_calls,
        max_parallel_rubrics=max_parallel_judges,
        show_rubric_progress=show_judge_progress,
        show_agent_progress=show_agent_progress,
    )


__all__ = [
    "JudgeSweepRow",
    "run_judges",
    "run_judges_to_file",
]
