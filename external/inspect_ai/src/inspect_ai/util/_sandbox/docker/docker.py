import base64
import errno
import json
import os
import tempfile
from logging import getLogger
from pathlib import Path, PurePosixPath
from typing import Literal, Union, overload

from typing_extensions import override
import hashlib

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import ExecResult, subprocess

from ..environment import (
    HostMapping,
    PortMapping,
    SandboxConnection,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from ..limits import (
    SandboxEnvironmentLimits,
    verify_exec_result_size,
    verify_read_file_size,
)
from ..registry import sandboxenv
from .cleanup import (
    cli_cleanup,
    project_cleanup,
    project_cleanup_shutdown,
    project_cleanup_startup,
    project_startup,
)
from .compose import (
    compose_build,
    compose_check_running,
    compose_cleanup_images,
    compose_cp,
    compose_exec,
    compose_ps,
    compose_pull,
    compose_services,
    compose_up,
)
from .config import CONFIG_FILES, DOCKERFILE
from .internal import build_internal_image, is_internal_image
from .prereqs import validate_prereqs
from .util import ComposeProject, is_local_docker, task_project_name
import asyncio

logger = getLogger(__name__)

if not is_local_docker():
    from morphcloud.api import MorphCloudClient, Instance

    client = MorphCloudClient()
    TASK_CONFIG_TO_INSTANCE: dict[str, Instance] = {}

    async def create_instance(snapshot_id: str, project_name: str) -> Instance:
        delay = 1
        for iter in range(5):
            try:
                instance = client.instances.start(snapshot_id=snapshot_id)
                TASK_CONFIG_TO_INSTANCE[project_name] = instance
                return instance
            except Exception as e:
                logger.warning(
                    f"Instance creation failed (attempt {iter + 1}/5), retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise Exception(
            "Failed to set up experiment after 5 attempts - we are out of CPU capacity"
        )


# base 16GB: snapshot_y3o7h1cy

COMMON_HASH_SNAPSHOTS = {
    "50fe0fa7f3112e760d800a169864e63551781f9f44c31c1cac2601b6ddccf74c": "snapshot_yjgb4se5",  # intercode: 8G
    "0e76ec7f3f97d9c56b897af2d7da9c60f192bd1cbe0b8963fe89e19e8ef34a46": "snapshot_sm0n0bm1",  # intercode new: 8G
    "113d544eb164a0b0f3a63c84f923c6f2e4055b9d479fb498bdbfdb9b0e340c92": "snapshot_v1tg2zg0",  # default cybench: 16G
    "b631dd95f372cbcc0e46276f27da8f803f36f7fa2101b00cd3cc533bce68061c": "snapshot_57sotko2",
    "de9ec2e81b6392b20c2ee1b933610bce352effabc991ada051435159746a41b7": "snapshot_zfmp9soe",
    "774b74068832a30266e7a4182ea2a9309a6ec4eed672b5e5d05b00a3a243722b": "snapshot_e77u7o1u",
    "a9bd1ee7106f1c7ceef39b0d5b44af9e9892808ea27c29b534f472500f545190": "snapshot_z9e3abwg",
    "3bb4552d0c24dd2f2e25c23066f98e16ac67b656e204bde8a651fd0efe8bbbe2": "snapshot_83fhs03x",
    "c52234385063906c889eb6714cbbe8efb4874150346594cd38d7ebe12a88d785": "snapshot_0hcflpzr",
    "25e352652ed0594dbe9d0f739e8022666d5608b949ecb707fdfce4b5161c1a1b": "snapshot_h71mey0t",
    "bdbf96fdf6430154716e39ada653fa4fa40609312730d0392f5dc341d91a809e": "snapshot_qzt4chbv",
    "d544c4e58cdcc3f1b3d8bb0810f0d3a61304729e0918b9ac2786e89b049c24b6": "snapshot_cq438nk8",
    "181ca879a3f1cf6f8d084fc75e2ce594bb8b5c50498dacbf4062c6679887a9c5": "snapshot_84c1c1uj",
    "9e74803260a17c2364bb61c44af6ce4c975782f3c1d64a51256b2dbe81ef14ce": "snapshot_0y3enaq5",
    "fd14aae5fec846724483e1abac11090578005fd4f3a2076efbc3ea2c4fafefcd": "snapshot_1ryjudg9",
    "cfcda5968edd0ccfd5a2f7525182d0b666d96ed47e5121cc4d0f4993764e197c": "snapshot_upc3lsut",
    "3d6624c0061acf4f32c85b9bc2461c63f335f91c6a42181102be541e547d04f2": "snapshot_pvmvl0rw",
    "e9ed8f46eb9455da23ad6aa893bd06c5fde3df30fb64ac07fde343f783d88d3e": "snapshot_vv86x0tj",
    "f9a1078a02bc92804ad1150e7264b5f01827e24d91974941fabf6dee375d5ba4": "snapshot_lqkpe97o",
    "9ec2c95b896a0a915f0636b30772e1e3b07a08b98571cf72339acb079191c243": "snapshot_hjr1ljdv",
    "561dadca1127f227cfa26a621d98ff951ccacd13449f479781a612c9419e74ea": "snapshot_os9j8wyy",
    "846dc07f648e7437770792055ea1e384f3d432715ac33944932d968969d94b4f": "snapshot_6elxj4gd",
    "b472b76c20fd9b749f3f79d9cc06e91a6ad4ef10c9363beb8472298c9e530915": "snapshot_74h1djhr",
    "f279dce707bf69b141864699174cc409b2ace5458fd935079c53ddd11a1510ba": "snapshot_58einu9i",
    "72f9740f070bfcd59a1201921d3b04260492160de2243b415c34cf3cb0b77583": "snapshot_60wfanmf",
    "3d76044d97031b591709b5c7749332ff4556cc678827360a29e5312a0c4286ff": "snapshot_2th8j4l3",
    "36c6c64dffed2d3c7058e65e3813ab904328f77316c9605ea715f450419c17ae": "snapshot_uozovu00",  # chunky: 24G
}


@sandboxenv(name="docker")
class DockerSandboxEnvironment(SandboxEnvironment):
    @classmethod
    def config_files(cls) -> list[str]:
        return CONFIG_FILES + [DOCKERFILE]

    @classmethod
    def default_concurrency(cls) -> int | None:
        count = os.cpu_count() or 1
        if not is_local_docker():
            return 64
        return 2 * count

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        # validate prereqs
        await validate_prereqs()

        # intialize project cleanup
        project_cleanup_startup()

        try:
            # create project
            env: dict[str, str] = {}

            if not is_local_docker():
                # compute the hash of the config contents
                config_hash = hashlib.sha256(open(config, "rb").read()).hexdigest()

                if config_hash in COMMON_HASH_SNAPSHOTS:
                    print(f"{config_hash}||{config}||CACHED")
                    return

                print(f"{config_hash}||{config}||UNCACHED")

                instance = client.instances.start(snapshot_id="snapshot_v1tg2zg0")
                env["DOCKER_HOST"] = f"ssh://{instance.id}@ssh.cloud.morph.so"

            project = await ComposeProject.create(
                name=task_project_name(task_name),
                config=config,
                env=env,
            )

            # build containers which are out of date
            await compose_build(project)

            # cleanup images created during build
            await compose_cleanup_images(project, timeout=60)

            services = await compose_services(project)
            for name, service in services.items():
                # if the service has an explicit container_name then
                # error (as this won't work w/ epochs > 1)
                container_name = service.get("container_name", None)
                if container_name:
                    raise PrerequisiteError(
                        f"ERROR: Docker service '{name}' includes an explicitly configured container_name ('{container_name}'). This is not permitted, as container names should be provisioned by Docker compose and an explicit container_name will not work with epochs > 1."
                    )

                # build internal images
                image = service.get("image", None)
                if image and is_internal_image(image):
                    await build_internal_image(image)
                # pull any remote images
                elif (
                    service.get("build", None) is None
                    and service.get("x-local", None) is None
                ):
                    pull_result = await compose_pull(name, project)
                    if not pull_result.success:
                        image = service.get("image", "(unknown)")
                        logger.error(
                            f"Failed to pull docker image '{image}' from remote registry. If this is a locally built image add 'x-local: true' to the the service definition to prevent this error."
                        )

            # provide some space above task display
            print("")
            if not is_local_docker():
                snapshot_id = instance.snapshot().id
                print(f"{config_hash}||{config}||{snapshot_id}")
                COMMON_HASH_SNAPSHOTS[config_hash] = snapshot_id
                instance.stop()
        except BaseException as ex:
            await project_cleanup_shutdown(True)
            raise ex

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        # create environment variables for sample metadata
        env: dict[str, str] = {}
        if isinstance(config, str) and Path(config).exists():
            # read the config file
            with open(config, "r") as f:
                config_text = f.read()

            # only add metadata files if the key is in the file
            for key, value in metadata.items():
                key = f"SAMPLE_METADATA_{key.replace(' ', '_').upper()}"
                if key in config_text:
                    env[key] = str(value)

        project_name = task_project_name(task_name)

        if not is_local_docker():
            config_hash = hashlib.sha256(open(config, "rb").read()).hexdigest()
            instance = await create_instance(
                COMMON_HASH_SNAPSHOTS[config_hash], project_name
            )
            env["DOCKER_HOST"] = f"ssh://{instance.id}@ssh.cloud.morph.so"

        # create project
        from inspect_ai.log._samples import sample_active

        sample = sample_active()
        project = await ComposeProject.create(
            name=project_name,
            config=config,
            sample_id=sample.sample.id if sample is not None else None,
            epoch=sample.epoch if sample is not None else None,
            env=env,
        )

        try:
            # enumerate the services that will be created
            services = await compose_services(project)

            # start the services
            result = await compose_up(project, services)

            # check to ensure that the services are running
            running_services = await compose_check_running(
                list(services.keys()), project=project
            )

            if not running_services:
                raise RuntimeError(
                    f"No services started.\nCompose up stderr: {result.stderr}"
                )

            # note that the project is running
            project_startup(project)

            # create sandbox environments for all running services
            default_service: str | None = None
            environments: dict[str, SandboxEnvironment] = {}
            for service, service_info in services.items():
                if service in running_services:
                    # update the project w/ the working directory
                    working_dir = await container_working_dir(service, project)

                    # create the docker sandbox environemnt
                    docker_env = DockerSandboxEnvironment(service, project, working_dir)

                    # save reference to default service if requested
                    if service_info.get("x-default", False):
                        default_service = service

                    # record service => environment
                    environments[service] = docker_env

            # confirm that we have a 'default' environemnt
            if environments.get("default", None) is None and default_service is None:
                raise RuntimeError(
                    "No 'default' service found in Docker compose file. "
                    + "You should either name a service 'default' or add "
                    + "'x-default: true' to one of your service definitions."
                )

            # ensure that the default service is first in the dictionary
            default_service = default_service or "default"
            default_environment = environments[default_service]
            del environments[default_service]
            environments = {default_service: default_environment} | environments

        except BaseException as ex:
            await project_cleanup(project, True)
            raise ex

        return environments

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        # if we were interrupted then wait unil the end of the task to cleanup
        # (this enables us to show output for the cleanup operation)
        # extract project from first environment
        project = (
            next(iter(environments.values())).as_type(DockerSandboxEnvironment)._project
        )
        if not interrupted:
            # cleanup the project
            try:
                await project_cleanup(project=project, quiet=True)
            except Exception as e:
                logger.warning(f"Failed to cleanup project: {e}")
        if not is_local_docker():
            instance = TASK_CONFIG_TO_INSTANCE[project.name]
            client.instances.stop(instance.id)
            del TASK_CONFIG_TO_INSTANCE[project.name]

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        await project_cleanup_shutdown(cleanup)

    @classmethod
    async def cli_cleanup(cls, id: str | None) -> None:
        await cli_cleanup(id)

    def __init__(self, service: str, project: ComposeProject, working_dir: str) -> None:
        super().__init__()
        self._service = service
        self._project = project
        self._working_dir = working_dir

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
    ) -> ExecResult[str]:
        # additional args
        args = []

        final_cwd = PurePosixPath(self._working_dir if cwd is None else cwd)
        if not final_cwd.is_absolute():
            final_cwd = self._working_dir / final_cwd

        args.append("--workdir")
        args.append(str(final_cwd))

        if user:
            args.append("--user")
            args.append(user)

        # Forward environment commands to docker compose exec so they
        # will be available to the bash command
        if len(env.items()) > 0:
            for key, value in env.items():
                args.append("--env")
                args.append(f"{key}={value}")

        exec_result = await compose_exec(
            args + [self._service] + cmd,
            project=self._project,
            timeout=timeout,
            timeout_retry=timeout_retry,
            input=input,
            output_limit=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE,
        )
        verify_exec_result_size(exec_result)
        if exec_result.returncode == 126 and "permission denied" in exec_result.stdout:
            raise PermissionError(f"Permission denied executing command: {exec_result}")

        return exec_result

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        # defualt timeout for write_file operations
        TIMEOUT = 180

        # resolve relative file paths
        file = self.container_file(file)

        # ensure that the directory exists
        parent = Path(file).parent.as_posix()
        if parent != ".":
            result = await self.exec(["mkdir", "-p", parent])
            if not result.success:
                msg = f"Failed to create container directory {parent}: {result.stderr}"
                raise RuntimeError(msg)

        # write the file
        if isinstance(contents, str):
            result = await self.exec(
                ["sh", "-e", "-c", 'tee -- "$1"', "write_file_script", file],
                input=contents,
                timeout=TIMEOUT,
            )
        else:
            base64_contents = base64.b64encode(contents).decode("US-ASCII")
            result = await self.exec(
                [
                    "sh",
                    "-e",
                    "-c",
                    'base64 -d | tee -- "$1" > /dev/null',
                    "write_file_script",
                    file,
                ],
                input=base64_contents,
                timeout=TIMEOUT,
            )
        if result.returncode != 0:
            if "permission denied" in result.stderr.casefold():
                ls_result = await self.exec(["ls", "-la", "."])
                error_string = f"Permission was denied. Error details: {result.stderr}; ls -la: {ls_result.stdout}"
                raise PermissionError(error_string)
            elif (
                "cannot overwrite directory" in result.stderr.casefold()
                or "is a directory" in result.stderr.casefold()
            ):
                raise IsADirectoryError(
                    f"Failed to write file: {file} because it is a directory already"
                )
            else:
                raise RuntimeError(f"failed to copy during write_file: {result}")

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        # Write the contents to a temp file
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            # resolve relative file paths
            original_file = file
            file = self.container_file(file)

            # copy the file
            dest_file = os.path.join(temp_dir, os.path.basename(file))
            try:
                await compose_cp(
                    src=f"{self._service}:{file}",
                    dest=os.path.basename(dest_file),
                    project=self._project,
                    cwd=os.path.dirname(dest_file),
                    output_limit=SandboxEnvironmentLimits.MAX_READ_FILE_SIZE,
                )
            except RuntimeError as ex:
                # extract the message and normalise case
                message = str(ex).lower()

                # FileNotFoundError
                if "could not find the file" in message:
                    raise FileNotFoundError(
                        errno.ENOENT, "No such file or directory.", original_file
                    )

                # PermissionError
                elif "permission denied" in message:
                    raise PermissionError(
                        errno.EACCES, "Permission denied.", original_file
                    )
                else:
                    raise ex

            verify_read_file_size(dest_file)

            # read and return w/ appropriate encoding
            if text:
                with open(dest_file, "r", newline="", encoding="utf-8") as f:
                    return f.read()
            else:
                with open(dest_file, "rb") as f:
                    return f.read()

    @override
    async def connection(self) -> SandboxConnection:
        # find container for service
        services = await compose_ps(project=self._project)
        container = next(
            (
                service["Name"]
                for service in services
                if service["Service"] == self._service
            ),
            None,
        )

        # return container connection
        if container:
            return SandboxConnection(
                type="docker",
                command=f"docker exec -it {container} bash -l",
                vscode_command=[
                    "remote-containers.attachToRunningContainer",
                    container,
                ],
                ports=await get_ports_info(container, self._project.env),
                container=container,
            )
        # error (not currently running)
        else:
            raise ConnectionError(
                f"Service '{self._service} is not currently running.'"
            )

    def container_file(self, file: str) -> str:
        path = Path(file)
        if not path.is_absolute():
            path = Path(self._working_dir) / path
        return path.as_posix()


async def container_working_dir(
    service: str, project: ComposeProject, default: str = "/"
) -> str:
    result = await compose_exec(
        [service, "sh", "-c", "pwd"], timeout=60, project=project
    )
    if result.success:
        return result.stdout.strip()
    else:
        logger.warning(
            f"Failed to get working directory for docker container '{service}': "
            + f"{result.stderr}"
        )
        return default


async def get_ports_info(
    container: str, env: dict[str, str]
) -> list[PortMapping] | None:
    try:
        result = await subprocess(
            [
                "docker",
                "inspect",
                container,
                "--format",
                "{{json .NetworkSettings.Ports}}",
            ],
            timeout=60,
            env=env,
        )

        if not result.success:
            raise RuntimeError(result.stderr)

        return parse_docker_inspect_ports(result.stdout)

    # It's currently a policy decision to let docker timeouts to be silent.
    except TimeoutError:
        return None


def parse_docker_inspect_ports(json_str: str) -> list[PortMapping] | None:
    """
    Parses the JSON output from `docker inspect {container_name} --format='{{json .NetworkSettings.Ports}}'` to extract port mappings.

    Args:
        json_str (str): A JSON string representing the `NetworkSettings.Ports` output of `docker inspect`. e.g.
          ```
          {
              "5900/tcp": [{"HostIp": "0.0.0.0", "HostPort": "54023"}],
              "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "54024"}]
          }
          ```

    Returns:
        list[PortMapping] | None: A list of PortMapping objects if any port mappings are found,
                                   otherwise None.
    """
    data = json.loads(json_str)
    port_mappings = []
    for port_protocol, mappings in data.items():
        if mappings is None:
            continue
        container_port, protocol = port_protocol.split("/")
        host_mappings = [
            HostMapping(host_ip=mapping["HostIp"], host_port=int(mapping["HostPort"]))
            for mapping in mappings
        ]
        port_mapping = PortMapping(
            container_port=int(container_port),
            protocol=protocol,
            mappings=host_mappings,
        )
        port_mappings.append(port_mapping)
    return port_mappings if port_mappings else None
