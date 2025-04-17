from typing import Any, TypedDict

from inspect_evals.agentharm.agentharm import AgentHarmTaskArgs
from inspect_evals.cybench.cybench import CybenchTaskArgs
from inspect_evals.gdm_capabilities.in_house_ctf.task import InHouseCtfTaskArgs
from inspect_evals.gdm_capabilities.luce_intercode_ctf.task import (  # LuceIntercodeCtfTaskArgs,
    NewLuceIntercodeCtfTaskArgs,
)
from inspect_evals.luce_util import LuceTaskArgs

# from inspect_evals.vas import CreateExploitTaskArgs
from pydantic import BaseModel

TaskArgs = LuceTaskArgs

TASK_ARGS_DICT: dict[str, type[LuceTaskArgs]] = {
    "inspect_evals/cybench": CybenchTaskArgs,
    # "inspect_evals/luce_intercode_ctf": LuceIntercodeCtfTaskArgs,
    "inspect_evals/luce_intercode_ctf": NewLuceIntercodeCtfTaskArgs,
    "inspect_evals/gdm_in_house_ctf": InHouseCtfTaskArgs,
    # "create_exploit_task": CreateExploitTaskArgs,
    "inspect_evals/agentharm": AgentHarmTaskArgs,
}


class RunnerArgs(BaseModel):
    task_id: str
    task_args_dict: dict[str, Any]
    model: str
    sample_ids: list[str | int] | None
    epochs: int
    max_connections: int
    log_dir: str
    event_stream_dir: str | None
    result_path: str


class ExperimentResult(TypedDict):
    results: list[str]
    captured_stdout: str
    captured_stderr: str
