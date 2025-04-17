import asyncio
import re
from copy import deepcopy
from pathlib import Path
from shutil import copy
from subprocess import CalledProcessError
from typing import NamedTuple

import aiorwlock
import yaml
from aioshutil import copytree
from git import Reference, Repo
from inspect_ai.util import ExecResult

from inspect_evals.vas.src.config import CP_ROOT, CRS_SCRATCH_SPACE

from inspect_evals.vas.src.api.fs import RunException, run_command

Sanitizer = NamedTuple("Sanitizer", [("name", str), ("error_code", str)])
Harness = NamedTuple("Harness", [("name", str), ("file_path", Path)])
Source = NamedTuple("Source", [("repo", Repo), ("ref", Reference)])


class ProjectBuildException(RunException):
    message = "Build failed"


class ChallengeProjectReadOnly:
    def __init__(self, path: Path, input_path: Path):
        self.path = path
        self.input_path = input_path
        self.__config = self._read_project_yaml()
        self.name = self.__config["cp_name"]
        self.language = self.__config["language"].title()

        self.sources = list(self.__config["cp_sources"].keys())
        self.repo = Repo(self.path)
        self.repos = {
            source: Source(
                repo,
                repo.references[self.__config["cp_sources"][source]["ref"]],
            )
            for source in self.sources
            if (repo := Repo(self.path / "src" / source))
        }

        self.artifacts = {
            source: [self.path / artifact for artifact in self.__config["cp_sources"][source]["artifacts"]]
            for source in self.sources
        }

        self.sanitizers = {
            key: Sanitizer(*(x.strip() for x in value.split(":"))) for key, value in self.__config["sanitizers"].items()
        }

        self.harnesses = {
            key: Harness(value["name"], self.path / value["source"])
            for key, value in self.__config["harnesses"].items()
        }

    @property
    def config(self):
        return deepcopy(self.__config)

    @property
    def sanitizer_str(self):
        return deepcopy(self.__config["sanitizers"])

    def _read_project_yaml(self):
        project_yaml_path = self.path / "project.yaml"
        return yaml.safe_load(project_yaml_path.read_text())

    def open_project_source_file(self, source: str, file_path: Path) -> str:
        """Opens a file path in the CP.
        source must be one of `self.sources`
        file_path must be relative to source folder (can be obtained from git history)
        """
        return (self.path / "src" / source / file_path).read_text()

    async def make_writeable_copy(self, name_extra: str, other_patches: list[tuple[str, Path]]) -> "ChallengeProject":
        destination_path = CRS_SCRATCH_SPACE / CP_ROOT.name / f"{self.path.name}_{name_extra}"
        if not destination_path.exists():
            await copytree(self.path, destination_path, copy_function=copy, dirs_exist_ok=True)
            project = ChallengeProject(destination_path, self.input_path)
            project.apply_patches(other_patches)
            await project.build_project()
            return project
        return ChallengeProject(
            destination_path,
            self.input_path,
        )

    def get_cpv_info(self):
        cpv_dir = self.path / ".internal_only"
        if not cpv_dir.exists():
            cpv_dir = self.path / "exemplar_only"
        if not cpv_dir.exists():
            raise Exception("Vulnerabilities not defined")

        patches = []
        for cpv in cpv_dir.iterdir():
            patches_dir = cpv / "patches"
            for other_source in self.sources:
                patch_path = patches_dir / other_source / "good_patch.diff"
                if patch_path.exists():
                    patches.append((other_source, str(patch_path.resolve())))
                    break

        cpv_info = []
        for cpv in cpv_dir.iterdir():
            info_file = cpv / "pov_pou_info"
            if info_file.exists():
                pov_harness, sanitizer = info_file.read_text().strip().split(",")
                sanitizer_id = list(self.sanitizer_str.keys())[
                    list(self.sanitizer_str.values()).index(sanitizer.strip())
                ]

                harness_index = [harness["name"] for harness in self.config["harnesses"].values()].index(
                    pov_harness.strip()
                )
                harness_id = list(self.config["harnesses"].keys())[harness_index]
            else:
                if len(self.sanitizers) == 1:
                    sanitizer_id = next(iter(self.sanitizers))
                elif "1" in cpv.name:
                    sanitizer_id = "id_1"
                elif "2" in cpv.name:
                    sanitizer_id = "id_2"
                else:
                    raise Exception("sanitizer_id not determined")

                if len(self.harnesses) == 1:
                    harness_id = next(iter(self.harnesses))
                else:
                    raise Exception("harness_id not determined")

            files = []
            patches_dir = cpv_dir / cpv / "patches"
            cp_source = ""
            for source in self.sources:
                patch_path = patches_dir / source / "good_patch.diff"
                if patch_path.exists():
                    patch = patch_path.read_text()
                    files.extend(re.findall("(?<=\\+\\+\\+ b/).*(?=\n)", patch))
                    cp_source = source
                    break

            other_patches = [(cp_source, patch_path) for cp_source, patch_path in patches if cpv.name not in patch_path]
            cpv_info.append((cpv.name, cp_source, harness_id, sanitizer_id, files, other_patches))
        return cpv_info


class ChallengeProject(ChallengeProjectReadOnly):
    def __init__(
        self,
        path: Path,
        input_path: Path,
        initial_build: bool = False,
    ):
        super().__init__(path, input_path)
        self._build_lock = aiorwlock.RWLock()
        self.writeable_copy_async = asyncio.create_task(self._return_self())
        if initial_build:
            # logger.info(f"Building {self.name}")
            self.initial_build = asyncio.create_task(self.build_project())
        else:
            self.initial_build = self.writeable_copy_async

    @property
    def build_lock(self):
        return self._build_lock.writer_lock

    @property
    def run_lock(self):
        return self._build_lock.reader_lock

    async def _return_self(self) -> "ChallengeProject":
        return self

    async def _run_cp_run_sh(self, *command: str, **kwargs) -> ExecResult[str]:
        """
        Copied from run.sh:
        A helper script for CP interactions.

        Usage: build|run_pov|run_test|custom

        Subcommands:
            build [<patch_file> <source>]       Build the CP (an optional patch file for a given source repo can be supplied)
            run_pov <blob_file> <harness_name>  Run the binary data blob against specified harness
            run_tests                           Run functionality tests
            custom <arbitrary cmd ...>          Run an arbitrary command in the docker container
        """

        async with self.run_lock:
            return await run_command([str(self.path / "run.sh"), *command], **kwargs)

    def reset_source_repo(self, source):
        git_repo, ref = self.repos[source]
        git_repo.git.restore(".")
        git_repo.git.switch("--detach", ref)

    async def _build(self, *args):
        async with self.build_lock:
            try:
                result = await self._run_cp_run_sh("build", *args)
                if result.stderr:
                    raise ProjectBuildException(stderr=result.stderr)
                return result
            except CalledProcessError as err:
                raise ProjectBuildException(stderr=err.stderr) from err

    async def build_project(self):
        """Build a project.
        Raises ProjectBuildException, check ProjectBuildException.stderr for output
        """
        # logger.info("Building project")
        return await self._build()

    def apply_patches(self, patches: list[tuple[str, Path]]):
        # logger.info("Applying patches")
        for cp_source, patch_path in patches:
            git_repo, _ = self.repos[cp_source]
            git_repo.git.execute(["git", "apply", patch_path])

    async def run_harness(self, harness_input_file, harness_id) -> ExecResult[str]:
        """Runs a specified project test harness and returns the output of the process.
        Check result.stderr for sanitizer output if it exists.
        Can time out when input does not terminate programme.
        Raises:
            asyncio.TimeoutError: if harness does not finish in set time
        """
        return await self._run_cp_run_sh(
            "run_pov",
            str(harness_input_file),
            self.harnesses[harness_id].name,
        )

    async def run_harness_and_check_sanitizer(
        self, harness_input_file, harness_id, sanitizer_id, timeout=False
    ) -> tuple[bool, str]:
        """Runs a specified project test harness and returns whether sanitizer is triggered.
        Can time out when input does not terminate programme.
        Raises:
            asyncio.TimeoutError: if harness does not finish in set time
        """
        result = await self.run_harness(harness_input_file, harness_id)
        stderr = result.stderr
        sanitizer, error_code = self.sanitizers[sanitizer_id]
        return sanitizer in stderr and error_code in stderr, stderr

    async def run_tests(self):
        """Runs a specified project test suite and returns the output of the process.
        Check stderr for failed test output if it exists.
        """
        return await self._run_cp_run_sh("run_tests")
