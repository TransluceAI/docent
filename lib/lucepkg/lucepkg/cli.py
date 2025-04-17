"""CLI tool for managing Python environments and code synchronization.
Main entry point for the luce command.

NOTE FOR CLAUDE / AI ASSISTANTS: This CLI tool should already be in the PATH as `luce`. If you add
a command and want to try running it, you can just run `luce <command>`.
"""

import itertools
import os
import pathlib
import shlex
import subprocess
import sys
import time
from typing import Annotated, Any, Optional

import tomlkit
import typer
from luce_lib import config_lib, monorepo_util
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import cli_context, sync_lib
from .commands import artifact, config, get, irun, marimo, nb, node, preview, run, setup, uv

# Initialize rich console
console = Console()
error_console = Console(stderr=True)

app = typer.Typer(help="CLI tool for managing Python environments and code synchronization")

# Add command groups
app.add_typer(config.app, name="config")
app.add_typer(nb.app, name="nb")
app.add_typer(node.app, name="node")
app.add_typer(uv.app, name="uv")
app.add_typer(artifact.app, name="artifact")
app.add_typer(setup.app, name="setup")
app.add_typer(preview.app, name="preview")
app.add_typer(get.app, name="get")
app.add_typer(marimo.app, name="marimo")
app.add_typer(run.app)
app.add_typer(irun.app)


@app.callback()
def setup_context(
    ctx: typer.Context,
    internal_output_shell_commands_to: Annotated[
        Optional[str],
        typer.Option(hidden=True, help="Implementation detail: file to write shell commands to"),
    ] = None,
    internal_restore_virtual_env: Annotated[
        Optional[str],
        typer.Option(hidden=True, help="Implementation detail: env var to set as VIRTUAL_ENV"),
    ] = None,
) -> None:
    """Setup the Luce context object"""
    assert ctx.obj is None
    ctx.obj = cli_context.LuceContextObject(
        output_shell_commands_to=internal_output_shell_commands_to,
    )
    # Restore virtual env if specified. We need this to silence a UV warning if this script itself
    # is run with VIRTUAL_ENV set.
    if internal_restore_virtual_env is not None:
        os.environ["VIRTUAL_ENV"] = internal_restore_virtual_env


def _install_or_activate(
    ctx: typer.Context,
    environment_name: str | None,
    install: bool,
    cd: bool,
    activate: bool,
    with_dependencies: list[str],
    with_all: bool,
    exact: bool,
    rebuild: bool,
):
    """Helper to install or activate a virtual environment.

    Args:
        ctx: typer context object
        environment_name: Name of the environment to install or activate
        install: Whether to install the environment's dependencies
        cd: Whether to change to the environment's directory after activation
        activate: Whether to activate the environment
        with_dependencies: List of dependency groups to install
        with_all: Whether to install all dependency groups
        exact: Whether to sync to only include the specified packages, uninstalling other packages
        rebuild: Whether to clear the virtual environment before installing
    """
    monorepo_root = monorepo_util.find_monorepo_root()

    if environment_name is None or environment_name == "base":
        env_dir = monorepo_root
    else:
        env_dir = monorepo_root / "envs" / environment_name

    if not env_dir.is_dir():
        print(f"Error: Environment '{environment_name}' not found at {env_dir}.", file=sys.stderr)
        raise typer.Exit(1)

    env_activate = env_dir / ".venv/bin/activate"
    if rebuild or not env_activate.is_file():
        print("Creating fresh virtual environment")
        subprocess.run(["uv", "venv"], cwd=env_dir, check=True)

    if exact and not (install or with_dependencies):
        print("Error: --exact requires --install or --with", file=sys.stderr)
        raise typer.Exit(1)

    # Parse the pyproject.toml file
    with open(env_dir / "pyproject.toml") as f:
        pyproject = tomlkit.load(f)
    dependency_groups: Any = pyproject.get(  # pyright: ignore[reportUnknownMemberType]
        "dependency-groups", {}
    )

    def run_or_fail(command: list[str]) -> None:
        quoted_command = " ".join(shlex.quote(arg) for arg in command)
        print(f"Running: {quoted_command}")
        result = subprocess.run(command, cwd=env_dir)
        if result.returncode != 0:
            print(
                "Failed to install requested dependencies for "
                f"environment {repr(environment_name)}",
                file=sys.stderr,
            )
            raise typer.Exit(result.returncode)

    if install or with_dependencies or with_all or exact or rebuild:
        uv_command = ["uv", "sync"]
        if rebuild:
            # Also invalidate uv's cache for this install.
            uv_command.append("--refresh")

        # Check if this package needs a special install order.
        if "late_dependencies_1" in dependency_groups:
            print("Detected late dependencies for this environment; setting them up in order!")
            run_or_fail(uv_command + ["--inexact"])
            for i in itertools.count(1):
                group_name = f"late_dependencies_{i}"
                if group_name not in dependency_groups:
                    break
                uv_command.append("--group")
                uv_command.append(group_name)
                run_or_fail(uv_command + ["--inexact"])

        if with_all:
            uv_command.append("--all-groups")
        for groupstr in with_dependencies:
            for group in groupstr.split(","):
                uv_command.append("--group")
                uv_command.append(group)
        if exact or rebuild:
            uv_command.append("--exact")
        else:
            uv_command.append("--inexact")
        run_or_fail(uv_command)

    if activate:
        ctx.obj.enqueue_shell_command(f"source {shlex.quote(str(env_activate))}")
    if cd:
        ctx.obj.enqueue_shell_command(f"cd {shlex.quote(str(env_dir))}")


@app.command()
def activate(
    ctx: typer.Context,
    environment_name: Annotated[
        Optional[str],
        typer.Argument(
            help="Environment to activate. If not specified, activates base environment"
        ),
    ] = None,
    cd: Annotated[
        bool, typer.Option("--cd", "-c", help="Change to environment directory after activation")
    ] = False,
    install: Annotated[
        bool,
        typer.Option(
            "--install",
            "-i",
            help="Install the environment's dependencies before activating",
        ),
    ] = False,
    with_dependencies: Annotated[
        list[str],
        typer.Option(
            "--with",
            "-w",
            help=(
                "Install a dependency group into the environment; implies --install. "
                "Multiple groups can be specified with comma separation or by repeating the option."
            ),
        ),
    ] = [],
    with_all: Annotated[
        bool,
        typer.Option(
            "--with-all",
            help="Install all dependency groups",
        ),
    ] = False,
    exact: Annotated[
        bool,
        typer.Option(
            "--exact",
            "-e",
            help="Also sync to only include the specified packages, uninstalling other packages.",
        ),
    ] = False,
    rebuild: Annotated[
        bool,
        typer.Option(
            "--rebuild",
            "-r",
            help="Rebuild the virtual environment from scratch.",
        ),
    ] = False,
):
    """Activate a virtual environment, either the base environment or one under `envs/`"""
    _install_or_activate(
        ctx=ctx,
        environment_name=environment_name,
        install=install,
        cd=cd,
        activate=True,
        with_dependencies=with_dependencies,
        with_all=with_all,
        exact=exact,
        rebuild=rebuild,
    )


@app.command()
def install(
    ctx: typer.Context,
    groups: Annotated[
        list[str] | None,
        typer.Argument(help="Dependency groups to install."),
    ] = None,
    into: Annotated[
        Optional[str],
        typer.Option(
            "--into",
            help=(
                "Install into a specific environment. If not specified, installs into the active "
                "environment, or base if no active environment is found."
            ),
        ),
    ] = None,
    all: Annotated[bool, typer.Option("--all", help="Install all dependency groups")] = False,
    activate: Annotated[
        bool,
        typer.Option(
            "--activate",
            "-a",
            help="Activate the environment after installation",
        ),
    ] = False,
    cd: Annotated[
        bool,
        typer.Option(
            "--cd",
            "-c",
            help="Change to the environment directory after installation",
        ),
    ] = False,
    exact: Annotated[
        bool,
        typer.Option(
            "--exact",
            "-e",
            help="Also sync to only include the specified packages, uninstalling other packages.",
        ),
    ] = False,
    rebuild: Annotated[
        bool,
        typer.Option(
            "--rebuild",
            "-r",
            help="Rebuild the virtual environment from scratch.",
        ),
    ] = False,
):
    """Install dependencies into Python environments. Optionally sets up pre-commit hooks.

    Will install into the active environment if no environment is specified with --into, or into
    the base environment if no active environment is found.

    Will install dependency groups provided, or all dependency groups if --all is specified.

    If run with no arguments, and if the base environment or no environment is active, will also
    install pre-commit hooks in the base environment.
    """
    monorepo_root = monorepo_util.find_monorepo_root()

    if groups is None:
        groups = []

    # Check for an active virtual environment
    if into:
        environment_name = into
    elif os.environ.get("VIRTUAL_ENV"):
        env_dir = pathlib.Path(os.environ["VIRTUAL_ENV"])
        if env_dir.absolute() == (monorepo_root / ".venv").absolute():
            environment_name = "base"
        elif env_dir.parent.parent == monorepo_root / "envs":
            environment_name = env_dir.parent.name
            expected_path = monorepo_root / "envs" / environment_name / ".venv"
            if not expected_path.absolute() == env_dir.absolute():
                print(
                    f"Error: Virtual environment {env_dir} is not recognized",
                    file=sys.stderr,
                )
                raise typer.Exit(1)
        else:
            print(
                f"Error: Virtual environment {env_dir} is not in the monorepo",
                file=sys.stderr,
            )
            raise typer.Exit(1)

    else:
        environment_name = "base"

    _install_or_activate(
        ctx=ctx,
        environment_name=environment_name,
        install=True,
        cd=cd,
        activate=activate,
        with_dependencies=groups,
        with_all=all,
        exact=exact,
        rebuild=rebuild,
    )

    if environment_name == "base":
        # Install pre-commit hooks if this is a git repo
        git_dir = monorepo_root / ".git"
        if not git_dir.is_dir():
            print("Warning: Not a git repository, skipping pre-commit hook installation")
        else:
            print("Installing pre-commit hooks")
            subprocess.run(
                [str(monorepo_root / ".venv/bin/python"), "-m", "pre_commit", "install"],
                cwd=monorepo_root,
                check=True,
            )


@app.command()
def remove(
    environment_name: Annotated[str, typer.Argument(help="Name of environment to remove")],
):
    """Remove a virtual environment"""
    # Get package path
    monorepo_root = monorepo_util.find_monorepo_root()
    if environment_name == "base":
        env_dir = monorepo_root
    else:
        env_dir = monorepo_root / "envs" / environment_name
    venv_path = env_dir / ".venv"

    if not venv_path.exists():
        print(f"No virtual environment found for {environment_name}.")
        return

    try:
        import shutil

        shutil.rmtree(venv_path)
        print(f"Virtual environment for {environment_name} removed successfully.")
    except Exception as e:
        print(f"Error: Failed to remove virtual environment: {e}", file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def push(
    server_name: Annotated[
        Optional[str],
        typer.Argument(
            help="Server name or --all",
            autocompletion=config_lib.complete_server_names,
        ),
    ] = None,
    all: Annotated[bool, typer.Option("--all", "-a", help="Push to all servers")] = False,
):
    """Push current changes to specified server or all servers"""
    if all:
        assert server_name is None
        sync_lib.push_all_or_one("--all")
    else:
        assert server_name is not None
        sync_lib.push_all_or_one(server_name)


@app.command()
def sync(
    server_name: Annotated[
        Optional[str],
        typer.Argument(
            help="Server name (optional if using --all)",
            autocompletion=config_lib.complete_server_names,
        ),
    ] = None,
    all: Annotated[bool, typer.Option("--all", "-a", help="Sync all servers")] = False,
    legacy: Annotated[
        bool, typer.Option("--legacy", help="Use legacy sync behavior (separate rsync calls)")
    ] = False,
):
    """Sync changes to server(s) as they happen"""
    if all:
        assert server_name is None
        sync_lib.watch_and_sync("--all", legacy=legacy)
    else:
        assert server_name is not None
        sync_lib.watch_and_sync(server_name, legacy=legacy)


@app.command()
def rsync(
    file: Annotated[str, typer.Option("--file", "-f", help="Local file to sync")],
    dest: Annotated[str, typer.Option("--dest", "-d", help="Destination (user@host:path)")],
    ssh_key: Annotated[
        str, typer.Option("--ssh", help="SSH key to use")
    ] = "~/.ssh/clarity-ssh.pem",
):
    """Sync files to remote host"""
    # Expand ~ in ssh key path
    ssh_key = os.path.expanduser(ssh_key)

    # Validate SSH key exists
    if not os.path.isfile(ssh_key):
        print(f"Error: SSH key not found at {ssh_key}", file=sys.stderr)
        raise typer.Exit(1)

    # Construct and execute rsync command
    subprocess.run(
        [
            "rsync",
            "-avzP",
            "-e",
            f"ssh -i {shlex.quote(ssh_key)}",
            shlex.quote(file),
            shlex.quote(dest),
        ],
        check=True,
    )


@app.command()
def ssh(
    server_name: Annotated[
        Optional[str],
        typer.Argument(
            help="Server to connect to. If not specified, connects to the first server in config",
            autocompletion=config_lib.complete_server_names,
        ),
    ] = None,
):
    """SSH into the specified server or first server in config"""
    if server_name is None:
        server_name, config = sync_lib.get_default_server()
    else:
        servers = config_lib.get_server_configs()
        if server_name not in servers:
            error_console.print(f"[bold red]Error:[/] Server '{server_name}' not found in config")
            raise typer.Exit(1)
        config = servers[server_name]

    # Build ssh command
    ssh_cmd = ["ssh"]
    if config.identity_file:
        ssh_cmd.extend(["-i", config.identity_file])
    host_str = f"{config.user}@{config.hostname}" if config.user else config.hostname
    ssh_cmd.append(host_str)

    console.print(
        f"[bold green]Connecting[/] to [bold cyan]{host_str}[/]"
        + (f" using key [bold yellow]{config.identity_file}[/]" if config.identity_file else "")
        + "..."
    )
    subprocess.run(ssh_cmd, check=True)


@app.command()
def mosh(
    server_name: Annotated[
        Optional[str],
        typer.Argument(
            help="Server to connect to. If not specified, connects to the first server in config",
            autocompletion=config_lib.complete_server_names,
        ),
    ] = None,
):
    """Connect to server with mosh for a more resilient SSH connection"""
    # Check if mosh is installed locally
    try:
        subprocess.run(
            ["mosh", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        error_console.print(
            Panel(
                "[bold red]Error:[/] mosh is not installed locally\n\n"
                "Please install mosh first using your package manager:\n"
                "  • [bold]macOS:[/] [cyan]brew install mosh[/]\n"
                "  • [bold]Ubuntu/Debian:[/] [cyan]sudo apt install mosh[/]\n"
                "  • [bold]CentOS/RHEL:[/] [cyan]sudo yum install mosh[/]",
                title="Installation Required",
                border_style="red",
            ),
        )
        raise typer.Exit(1)

    if server_name is None:
        server_name, config = sync_lib.get_default_server()
    else:
        servers = config_lib.get_server_configs()
        if server_name not in servers:
            error_console.print(f"[bold red]Error:[/] Server '{server_name}' not found in config")
            raise typer.Exit(1)
        config = servers[server_name]

    # Build ssh command for checking/installing dependencies on the remote
    host_str = f"{config.user}@{config.hostname}" if config.user else config.hostname
    ssh_cmd = ["ssh"]
    if config.identity_file:
        ssh_cmd.extend(["-i", config.identity_file])
    ssh_cmd.append(host_str)

    # Check if mosh is installed on the remote, install if needed
    console.print(f"[bold]Checking[/] if [cyan]mosh[/] is installed on [bold cyan]{host_str}[/]...")

    with console.status("[bold cyan]Checking remote dependencies...[/]", spinner="dots"):
        install_cmd = (
            "if ! command -v mosh > /dev/null; then "
            "echo 'INSTALL_NEEDED'; "
            "if command -v apt-get > /dev/null; then "
            "sudo apt-get update && sudo apt-get install -y mosh; "
            "elif command -v yum > /dev/null; then "
            "sudo yum install -y mosh; "
            "elif command -v brew > /dev/null; then "
            "brew install mosh; "
            "else echo 'UNKNOWN_PKG_MANAGER'; exit 1; "
            "fi; "
            "echo 'INSTALL_COMPLETE'; "
            "fi"
        )

        result = subprocess.run([*ssh_cmd, install_cmd], capture_output=True, text=True)

        if "UNKNOWN_PKG_MANAGER" in result.stdout:
            error_console.print(
                "[bold red]Error:[/] Could not determine package manager on remote server to install mosh"
            )
            raise typer.Exit(1)

        if "INSTALL_NEEDED" in result.stdout:
            console.print("[bold green]✓[/] Successfully installed missing dependencies")
        else:
            console.print("[bold green]✓[/] All dependencies already installed")

    # Build mosh command
    mosh_cmd = ["mosh"]
    if config.identity_file:
        mosh_cmd.extend(["--ssh", f"ssh -i {shlex.quote(config.identity_file)}"])
    mosh_cmd.append(host_str)

    connection_text = Text()
    connection_text.append("Connecting to ", style="bold")
    connection_text.append(host_str, style="bold cyan")
    connection_text.append(" with ", style="")
    connection_text.append("mosh", style="bold magenta")

    if config.identity_file:
        connection_text.append(" using key ", style="")
        connection_text.append(config.identity_file, style="bold green")

    console.print(
        Panel(connection_text, title="Starting Persistent Connection", border_style="green")
    )

    subprocess.run(mosh_cmd, check=True)


@app.command()
def imux(
    server_name: Annotated[
        Optional[str],
        typer.Argument(
            help="Server to connect to. If not specified, connects to the default server",
            autocompletion=config_lib.complete_server_names,
        ),
    ] = None,
    session_name: Annotated[
        Optional[str], typer.Argument(help="Name of tmux session to attach to")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output")] = False,
):
    """
    Connect to server with mosh + tmux. Installs both if needed, then creates/attaches
    to a tmux session named 'main'.
    """

    # 1) Check local mosh
    try:
        subprocess.run(
            ["mosh", "--version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        error_console.print(
            Panel(
                "[bold red]Error:[/] mosh is not installed locally\n\n"
                "Please install mosh first using your package manager:\n"
                "  • [bold]macOS:[/] [cyan]brew install mosh[/]\n"
                "  • [bold]Ubuntu/Debian:[/] [cyan]sudo apt install mosh[/]\n"
                "  • [bold]CentOS/RHEL:[/] [cyan]sudo yum install mosh[/]",
                title="Installation Required",
                border_style="red",
            ),
        )
        raise typer.Exit(1)

    # 2) Resolve server config
    if server_name is None:
        server_name, config = sync_lib.get_default_server()
    else:
        servers = config_lib.get_server_configs()
        if server_name not in servers:
            error_console.print(f"[bold red]Error:[/] Server '{server_name}' not found in config")
            raise typer.Exit(1)
        config = servers[server_name]

    host_str = f"{config.user}@{config.hostname}" if config.user else config.hostname
    ssh_cmd = ["ssh"]
    if config.identity_file:
        ssh_cmd.extend(["-i", config.identity_file])
    ssh_cmd.append(host_str)

    # 3) Check/install mosh & tmux remotely
    if verbose:
        console.print(
            f"[bold]Checking[/] if [cyan]mosh[/] and [cyan]tmux[/] are installed on [bold cyan]{host_str}[/]..."
        )
    with console.status("[bold cyan]Checking remote dependencies...[/]", spinner="dots"):
        install_cmd = (
            "NEED_INSTALL=false; "
            "if ! command -v mosh >/dev/null; then "
            "  echo 'MISSING_MOSH'; NEED_INSTALL=true; "
            "fi; "
            "if ! command -v tmux >/dev/null; then "
            "  echo 'MISSING_TMUX'; NEED_INSTALL=true; "
            "fi; "
            "if $NEED_INSTALL; then "
            "  if command -v apt-get >/dev/null; then "
            "    sudo apt-get update && sudo apt-get install -y mosh tmux; "
            "  elif command -v yum >/dev/null; then "
            "    sudo yum install -y mosh tmux; "
            "  elif command -v brew >/dev/null; then "
            "    brew install mosh tmux; "
            "  else "
            "    echo 'UNKNOWN_PKG_MANAGER'; exit 1; "
            "  fi; "
            "  echo 'INSTALL_COMPLETE'; "
            "fi"
        )
        result = subprocess.run([*ssh_cmd, install_cmd], capture_output=True, text=True)

        if "UNKNOWN_PKG_MANAGER" in result.stdout:
            error_console.print(
                "[bold red]Error:[/] Could not determine package manager on remote server"
            )
            raise typer.Exit(1)

        if "MISSING_MOSH" in result.stdout or "MISSING_TMUX" in result.stdout:
            if "INSTALL_COMPLETE" in result.stdout:
                if verbose:
                    console.print("[bold green]✓[/] Successfully installed missing dependencies")
            else:
                error_console.print("[bold red]Error:[/] Failed to install dependencies")
                raise typer.Exit(1)
        else:
            if verbose:
                console.print("[bold green]✓[/] All dependencies already installed")

        # get the name of the most recent tmux session, or print out if none exist
        # Check for existing tmux sessions
        if verbose:
            console.print(
                f"[bold]Checking[/] for existing [cyan]tmux[/] sessions on [bold cyan]{host_str}[/]..."
            )

        tmux_list_cmd = "tmux list-sessions 2>/dev/null || echo 'NO_SESSIONS'"
        result = subprocess.run([*ssh_cmd, tmux_list_cmd], capture_output=True, text=True)

        if session_name is None:
            if "NO_SESSIONS" in result.stdout:
                if verbose:
                    console.print(
                        "[bold yellow]No existing tmux sessions found[/] - will create a new one"
                    )
                session_name = "main"
            else:
                # Parse and display existing sessions
                sessions = result.stdout.strip().split("\n")
                if verbose:
                    console.print(f"[bold green]Found {len(sessions)} existing tmux session(s):[/]")
                    for session in sessions:
                        console.print(f"  • [cyan]{session}[/]")

                # Get the most recent session
                session_name = sessions[-1].split(":")[0]
                if verbose:
                    console.print(f"[bold green]Attaching to[/] [cyan]{session_name}[/]")

    # 4) Build final mosh cmd: "tmux new -As main"
    mosh_cmd = ["mosh"]
    if config.identity_file:
        mosh_cmd.extend(["--ssh", f"ssh -i {shlex.quote(config.identity_file)}"])
    mosh_cmd.append(host_str)
    mosh_cmd.extend(["--", "tmux", "new", "-As", session_name])

    connection_text = Text()
    connection_text.append("Connecting to ", style="bold")
    connection_text.append(host_str, style="bold cyan")
    connection_text.append(" with ", style="")
    connection_text.append("mosh + tmux", style="bold magenta")
    if config.identity_file:
        connection_text.append(" using key ", style="")
        connection_text.append(config.identity_file, style="bold green")

    console.print(
        Panel(
            connection_text,
            title="Starting Persistent Connection",
            border_style="green",
        )
    )

    subprocess.run(mosh_cmd, check=True)


@app.command()
def cd(
    ctx: typer.Context,
    target: Annotated[
        Optional[str],
        typer.Argument(
            help=(
                "Where to cd to. If not provided, changes to monorepo root. "
                "Can be: artifacts, a package name in lib/ or project/, "
                "or a personal directory name (searched in personal/)"
            ),
        ),
    ] = None,
):
    """Change to a directory in the monorepo.

    With no argument, changes to the monorepo root.
    With 'artifacts', changes to the artifact directory.
    Otherwise tries to find a package by that name in lib/ or project/,
    and if not found, tries personal/{name}.
    """
    monorepo_root = monorepo_util.find_monorepo_root()

    if target is None:
        # cd to monorepo root
        ctx.obj.enqueue_shell_command(f"cd {shlex.quote(str(monorepo_root))}")
        return

    if target == "artifacts":
        # cd to artifacts dir
        try:
            data = config_lib.load_config()
            artifact_dir = data["artifact_dir"]
        except (KeyError, typer.Exit):
            print(
                "Error: artifact_dir not set in config. Run `luce config set-artifact-dir` first.",
                file=sys.stderr,
            )
            raise typer.Exit(1)

        artifact_path = pathlib.Path(artifact_dir).expanduser()
        if not artifact_path.exists():
            artifact_path.mkdir(parents=True)
            print(f"Created artifact directory at {artifact_path}")

        ctx.obj.enqueue_shell_command(f"cd {shlex.quote(str(artifact_path))}")
        return

    # Try to find package in lib/ or project/
    try:
        package_path = monorepo_util.get_package_path(target)
        ctx.obj.enqueue_shell_command(f"cd {shlex.quote(str(package_path))}")
        return
    except typer.Exit:
        # Not found as package, try personal directory
        personal_path = monorepo_root / "personal" / target
        if personal_path.exists():
            ctx.obj.enqueue_shell_command(f"cd {shlex.quote(str(personal_path))}")
            return

        print(
            f"Error: Could not find directory matching '{target}'. Valid targets are:\n"
            "  - (no argument): monorepo root\n"
            "  - artifacts: artifact directory\n"
            "  - package names in lib/ or project/\n"
            "  - personal directory names (searched in personal/)",
            file=sys.stderr,
        )
        raise typer.Exit(1)


def _parse_port_mapping(port_str: str) -> tuple[int, int]:
    """Parse a port mapping string into source and destination ports.

    Accepts either a single port number or a mapping in the form "from:to".
    Returns tuple of (source_port, dest_port).
    """
    if ":" in port_str:
        try:
            src, dst = map(int, port_str.split(":"))
            return src, dst
        except ValueError:
            error_console.print(f"[bold red]Error:[/] Invalid port mapping '[bold]{port_str}[/]'")
            raise typer.Exit(1)
    try:
        port = int(port_str)
        return port, port
    except ValueError:
        error_console.print(f"[bold red]Error:[/] Invalid port number '[bold]{port_str}[/]'")
        raise typer.Exit(1)


@app.command()
def tunnel(
    server_name: Annotated[
        str,
        typer.Argument(
            help="Server to tunnel to",
            autocompletion=config_lib.complete_server_names,
        ),
    ],
    ports: Annotated[
        list[str],
        typer.Argument(
            help=(
                "Local ports to forward, specified as port numbers or {from}:{to} pairs (e.g. 8888,"
                " 8889, or 8080:80)"
            )
        ),
    ],
    reverse: Annotated[
        Optional[list[str]],
        typer.Option("--reverse", "-R", help="Ports to reverse tunnel (e.g. 3000 or 8080:80)"),
    ] = None,
    retry: Annotated[
        bool,
        typer.Option(
            "--retry",
            help="Automatically retry connection if it fails",
        ),
    ] = False,
):
    """Create SSH tunnels to/from a remote server.

    Forward ports are accessible on the remote at localhost:<port>.
    Reverse ports are accessible locally at localhost:<port>.

    Ports can be specified as single numbers (e.g. 8888) or mappings (e.g. 8080:80).

    Example: luce tunnel myserver 8888 8080:80 --reverse 3000 --retry
    """
    # Get server config
    try:
        servers = config_lib.get_server_configs()
        if server_name not in servers:
            error_console.print(f"[bold red]Error:[/] Server '{server_name}' not found in config")
            raise typer.Exit(1)
        server = servers[server_name]
    except typer.Exit:
        error_console.print(
            "[bold red]Error:[/] No servers configured. Run [cyan]`luce config add-server`[/] first."
        )
        raise typer.Exit(1)

    # Build SSH command
    ssh_cmd = ["ssh"]

    # Add forward tunnels
    forward_mappings: list[tuple[int, int]] = []
    for port_str in ports:
        src, dst = _parse_port_mapping(port_str)
        ssh_cmd.extend(["-L", f"{src}:localhost:{dst}"])
        forward_mappings.append((src, dst))

    # Add reverse tunnels
    reverse_mappings: list[tuple[int, int]] = []
    if reverse:
        for port_str in reverse:
            src, dst = _parse_port_mapping(port_str)
            ssh_cmd.extend(["-R", f"{src}:localhost:{dst}"])
            reverse_mappings.append((src, dst))

    # Add target and no-shell flag
    if server.user:
        ssh_cmd.append(f"{server.user}@{server.hostname}")
    else:
        ssh_cmd.append(server.hostname)
    ssh_cmd.append("-N")  # Don't execute remote command

    # Print tunnel info
    if forward_mappings:
        mappings = [str(src) if src == dst else f"{src}→{dst}" for src, dst in forward_mappings]
        console.print(
            f"[bold green]Forwarding[/] local ports to [bold cyan]{server_name}[/]: [yellow]{', '.join(mappings)}[/]"
        )
    if reverse_mappings:
        mappings = [str(src) if src == dst else f"{src}→{dst}" for src, dst in reverse_mappings]
        console.print(
            f"[bold magenta]Reverse forwarding[/] ports from [bold cyan]{server_name}[/] to localhost: [yellow]{', '.join(mappings)}[/]"
        )

    while True:
        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            console.print(
                f"\n[[bold cyan]{timestamp}[/]] [bold]Executing[/] {' '.join(shlex.quote(arg) for arg in ssh_cmd)}"
            )

            # Create process with pipe for stderr
            process = subprocess.Popen(ssh_cmd, stderr=subprocess.PIPE, universal_newlines=True)
            assert process.stderr is not None

            # Read stderr in real-time
            stderr_output: list[str] = []
            while True:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    stderr_output.append(line.strip())
                    error_console.print(line, end="", style="yellow")

            # Wait for process to complete
            return_code = process.wait()

            # If process failed
            if return_code != 0:
                if not retry:
                    error_console.print(
                        f"\n[bold red]SSH tunnel failed[/] with return code {return_code}"
                    )
                    raise typer.Exit(1)

                # Check if any stderr line contains "agent refused operation"
                if any("agent refused operation" in line.lower() for line in stderr_output):
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    error_console.print(
                        f"\n[[bold cyan]{timestamp}[/]] [bold yellow]Agent refused operation[/]; waiting for user input."
                    )
                    error_console.print("[bold green]Press Enter to retry...[/]")
                    input("[press enter to resume tunnel]")
                else:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    console.print(
                        f"\n[[bold cyan]{timestamp}[/]] [bold red]Connection failed[/], retrying in 5 seconds..."
                    )
                    time.sleep(5)
                continue

        except KeyboardInterrupt:
            console.print("\n[bold yellow]Interrupted![/]")
            break


def main():
    app(prog_name="luce")


if __name__ == "__main__":
    main()
