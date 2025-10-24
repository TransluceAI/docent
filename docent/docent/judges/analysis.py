import json
from pathlib import Path
from typing import Any

import anyio
from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from tqdm.auto import tqdm

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.judges.impl import BaseJudge
from docent.judges.util.voting import JudgeOutputDistribution

logger = get_logger(__name__)


class MultiReflectRollouts(BaseModel):
    """Object is associated with a single agent run"""

    agent_run_id: str

    first_step_rollouts: list[dict[str, Any]]
    first_step_rollout_metadata: list[dict[str, Any] | None]
    # Each index in second_step_rollouts corresponds to an index in first_step_combinations
    # Step 2 rollouts are computed by passing each step 1 combo into the judge several times
    first_step_combinations: list[list[dict[str, Any]]] | None = None
    second_step_rollouts: list[list[dict[str, Any]]] | None = None
    second_step_rollout_metadata: list[list[dict[str, Any] | None]] | None = None

    distributions: dict[str, JudgeOutputDistribution]


async def collect_judge_pvs(
    judge: BaseJudge,
    agent_runs: list[AgentRun],
    *,
    results_path: Path,
    estimate_output_distrs_kwargs: dict[str, Any],
):
    if results_path.exists():
        raise FileExistsError(f"Results path already exists: {results_path}")
    results_path.parent.mkdir(parents=True, exist_ok=True)

    results = dict[str, MultiReflectRollouts]()
    persist_lock = anyio.Lock()
    pbar = tqdm(total=len(agent_runs), desc="Processing agent runs")

    async def _persist():
        async with persist_lock:
            with open(str(results_path), "w") as f:
                json.dump(to_jsonable_python(results), f, indent=2)

    async def _execute_for_agent_run(agent_run: AgentRun):
        result = await judge.estimate_output_distrs(agent_run, **estimate_output_distrs_kwargs)
        if result is None:
            pbar.update(1)
            return

        distrs, metadata = result
        results[agent_run.id] = MultiReflectRollouts.model_validate(
            {
                "agent_run_id": agent_run.id,
                "distributions": distrs,
                **metadata,
            }
        )
        await _persist()
        pbar.update(1)

    async with anyio.create_task_group() as tg_outer:
        for agent_run in agent_runs:
            tg_outer.start_soon(_execute_for_agent_run, agent_run)

    pbar.close()

    return results
