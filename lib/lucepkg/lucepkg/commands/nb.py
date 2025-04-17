import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from luce_lib import monorepo_util

app = typer.Typer(help="Jupyter notebook commands")


@app.command()
def start(
    port: Annotated[int, typer.Option("--port", "-p", help="Port for Jupyter server")],
    working_dir: Annotated[
        Optional[str],
        typer.Option(
            "--cwd", "-c", help="Working directory for Jupyter server (defaults to monorepo root)"
        ),
    ] = None,
    use_sudo: Annotated[
        bool,
        typer.Option("--sudo", help="Start Jupyter server with sudo privileges", is_flag=True),
    ] = False,
):
    """Start a Jupyter notebook server"""
    monorepo_root = monorepo_util.find_monorepo_root()
    start_script = monorepo_root / "lib/lucepkg/scripts/commands/start_notebook.sh"

    # If working_dir is provided, resolve it relative to current directory, else use monorepo root
    if working_dir:
        working_dir = str(Path(working_dir).resolve())
    else:
        working_dir = str(monorepo_root)

    cmd = [
        "sh",
        str(start_script),
        str(port),
        working_dir,
        str(use_sudo).lower(),
        str(monorepo_root),
    ]
    if use_sudo:
        cmd = ["sudo"] + cmd

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(e.stderr, file=sys.stderr)
        raise


@app.command()
def register(
    environment_name: Annotated[
        Optional[str],
        typer.Argument(
            help="Environment to register. If omitted, registers the base monorepo environment"
        ),
    ] = None,
    kernel_name: Annotated[
        Optional[str],
        typer.Option(
            "--kernel-name",
            "-k",
            help="Name for the Jupyter kernel. Defaults to 'base' or package name",
        ),
    ] = None,
    use_sudo: Annotated[
        bool,
        typer.Option("--sudo", help="Register kernel with sudo privileges", is_flag=True),
    ] = False,
):
    """Register a Jupyter kernel.

    If environment_name is provided, registers that environment as a kernel.
    If environment_name is omitted, registers the base monorepo environment as a kernel.
    """
    monorepo_root = monorepo_util.find_monorepo_root()

    if environment_name is None:
        venv_python = monorepo_root / ".venv/bin/python"
        display_name = "Luce Remote: base"
        default_kernel_name = "base"
    else:
        venv_python = monorepo_root / f"envs/{environment_name}/.venv/bin/python"
        display_name = f"Luce Remote: {environment_name}"
        default_kernel_name = environment_name

    # Use provided kernel_name if specified, otherwise use default
    kernel_name = kernel_name or default_kernel_name

    # Add (sudo) to display name if using sudo privileges
    if use_sudo:
        display_name += " (sudo)"

    if not venv_python.exists():
        print(
            f"Error: No virtual environment found for {environment_name}. "
            f"Did you run `luce install{' ' + environment_name if environment_name else ''}`?",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    cmd = [
        str(venv_python),
        "-m",
        "ipykernel",
        "install",
        "--user",
        f"--name={kernel_name}",
        f"--display-name={display_name}",
    ]
    if use_sudo:
        cmd = ["sudo"] + cmd

    try:
        result = subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(e.stderr, file=sys.stderr)
        if "No module named ipykernel" in e.stderr:
            print(
                "Error: The environment needs to have 'ipykernel' as a dependency in order to "
                "register a notebook kernel. Please add it and reinstall your environment "
                f"dependencies (`luce activate {environment_name} --install`).",
                file=sys.stderr,
            )
            raise typer.Exit(1)
        else:
            raise
    print(f"Kernel for {kernel_name} registered successfully.")
