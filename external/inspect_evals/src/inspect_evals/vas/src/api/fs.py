from datetime import datetime
from pathlib import Path
from shutil import rmtree
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

from inspect_ai.util import ExecResult, subprocess

from inspect_evals.vas.src.config import CP_ROOT, OUTPUT_PATH, PROJECT_PATH

if TYPE_CHECKING:
    from inspect_evals.vas.src.api.cp import ChallengeProject


class RunException(Exception):
    message = ""

    def __init__(self, stderr):
        super().__init__(self.message)
        self.stderr = stderr

    def __str__(self):
        return f"{super().__str__()}\n{self.stderr}"


async def run_command(args: str | list[str], **kwargs) -> ExecResult[str]:
    # logger.debug(f"Running {' '.join((str(arg) for arg in args))}")
    result = await subprocess(args, **kwargs, capture_output=True)

    # logger.debug(
    #     "\n".join([
    #         f"Output of running {' '.join((str(arg) for arg in args))}:",
    #         result.stdout,
    #         result.stderr,
    #     ])
    # )
    if result.returncode:
        raise CalledProcessError(result.returncode, args, result.stdout, result.stderr)
    return result


def get_project(challenge_project) -> Path:
    for item in CP_ROOT.iterdir():
        if item.is_dir() and item.name == challenge_project:
            return item
    raise Exception(f"Could not find project {challenge_project}")


def empty_scratch():
    if PROJECT_PATH.exists():
        rmtree(PROJECT_PATH)


def write_file_to_scratch(filename, content):
    OUTPUT_PATH.mkdir(exist_ok=True)
    file_path = OUTPUT_PATH / filename
    if isinstance(content, (bytes, bytearray)):
        file_path.write_bytes(content)
    else:
        file_path.write_text(content)
    return file_path


def write_harness_input_to_disk(
    project: "ChallengeProject",
    harness_input: str,
    i: int,
    cpv: int | str,
    model_name: str,
):
    model_name = model_name.replace("/", "_")
    return write_file_to_scratch(
        project.input_path
        / f"input_{datetime.today().isoformat()}_{cpv}_{model_name}_{i}_hash{str(hash(harness_input))[:6]}.blob",
        harness_input,
    )
