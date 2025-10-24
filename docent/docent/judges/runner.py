import anyio
from tqdm.auto import tqdm

from docent._llm_util.llm_svc import BaseLLMService
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.judges import (
    JudgeResult,
    JudgeResultCompletionCallback,
    Rubric,
)
from docent.judges.impl import build_judge

logger = get_logger(__name__)


async def run_rubric(
    agent_runs: list[AgentRun],
    rubric: Rubric,
    llm_svc: BaseLLMService,
    callback: JudgeResultCompletionCallback | None = None,
    *,
    show_progress: bool = True,
) -> list[JudgeResult | None]:
    if not agent_runs:
        raise ValueError("agent_runs must be a non-empty sequence")
    if rubric.n_rollouts_per_input <= 0:
        raise ValueError("rubric.n_rollouts_per_input must be greater than 0")

    judge = build_judge(rubric, llm_svc)

    logger.info(
        "Running rubric %s version %s against %d agent runs",
        rubric.id,
        rubric.version,
        len(agent_runs),
    )

    agent_results: list[JudgeResult | None] = [None for _ in agent_runs]
    progress_bar = tqdm(
        total=len(agent_runs), desc=f"Rubric {rubric.id}", disable=not show_progress
    )

    async def _run_single_judge(index: int, agent_run: AgentRun):
        agent_results[index] = result = await judge(agent_run)

        if callback is not None:
            await callback(index, [result] if result is not None else None)
        progress_bar.update()

    try:
        async with anyio.create_task_group() as tg:
            for index, agent_run in enumerate(agent_runs):
                tg.start_soon(_run_single_judge, index, agent_run)
    finally:
        progress_bar.close()

    successful = sum(result is not None for result in agent_results)
    logger.info(
        "Finished rubric %s: produced %d/%d judge results",
        rubric.id,
        successful,
        len(agent_results),
    )

    return agent_results
