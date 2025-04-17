import difflib
import pathlib
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Optional

import rich
import rich.syntax
import tomlkit
import typer
from luce_lib import config_lib
from rich.panel import Panel

from .. import sync_lib

app = typer.Typer(help="Commands for setting up workstations")


@dataclass
class RemoteSetupConfig:
    """Configuration for remote setup from config.toml."""

    # SSH settings
    ssh_forward_agent: bool
    ssh_tunnel_notebook: bool
    monorepo_path: str

    # Remote luce config settings
    remote_luce_config: dict[str, Any] | None

    # Custom commands to run on remote
    custom_commands: Optional[str]

    @classmethod
    def from_config(cls, config: dict[str, Any], user: str) -> "RemoteSetupConfig":
        """Create from config dict."""
        remote_setup = config.get("remote_setup", {})

        return cls(
            ssh_forward_agent=remote_setup.get("ssh_forward_agent", True),
            ssh_tunnel_notebook=remote_setup.get("ssh_tunnel_notebook", False),
            monorepo_path=remote_setup.get("monorepo_path", f"/home/{user}/clarity"),
            remote_luce_config=remote_setup.get("luce_config", {}),
            custom_commands=remote_setup.get("custom_commands"),
        )


@app.command()
def remote(
    name: Annotated[str, typer.Argument(help="Name to give the remote server")],
    ip_address: Annotated[str, typer.Argument(help="IP address of the remote server")],
    identity_file: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--identity-file",
            "-i",
            help="SSH identity file to use. If not provided, uses SSH agent",
        ),
    ] = None,
    user: Annotated[
        str,
        typer.Option(
            "--user",
            "-u",
            help="Remote user to connect as",
            show_default=True,
        ),
    ] = "ubuntu",
    accept_all: Annotated[
        bool,
        typer.Option(
            "--accept-all",
            "-y",
            help="Automatically accept all prompts (SSH host key, confirmation)",
        ),
    ] = False,
):
    """Set up a remote workstation from scratch.

    This command will:
    1. Configure SSH for easy access to the server
    2. Add the server to Luce config
    3. Push the monorepo to the server
    4. Copy AWS credentials
    5. Set up remote Luce config
    6. Install and configure Luce on the remote server
    7. Run any additional setup commands

    Additional settings like SSH forwarding and paths are configured in
    the [remote_setup] section of ~/.luce/config.toml.
    """
    rich.print(
        Panel(
            f"Setting up remote machine [bold]{name}[/bold] at [bold]{ip_address}[/bold]",
            style="bold blue",
            border_style="blue",
            padding=(0, 2),
            title="Remote Setup Plan",
        )
    )

    if identity_file is not None:
        identity_file = identity_file.expanduser()
        if not identity_file.is_file():
            print(f"Error: Identity file not found: {identity_file}", file=sys.stderr)
            raise typer.Exit(1)

    # Load config
    try:
        config = config_lib.load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        raise typer.Exit(1)

    setup_config = RemoteSetupConfig.from_config(config, user)

    # Build SSH command components for initial test connection
    ssh_target = f"{user}@{ip_address}"
    ssh_cmd = ["ssh"]

    # Add identity file if provided
    if identity_file:
        ssh_cmd.extend(["-i", str(identity_file)])

    # Add auto-accept for new host keys if accept_all is enabled
    if accept_all:
        ssh_cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])

    ssh_cmd.append(ssh_target)

    # Check SSH connectivity and existing setup
    rich.print("\n[blue]Checking connection to server...[/blue]")
    try:
        # Test SSH connection
        print(ssh_cmd)
        subprocess.run([*ssh_cmd, "true"], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        rich.print(
            "[red]Error:[/red] Could not connect to server. SSH command"
            f" failed:\n{e.stderr.decode()}"
        )
        raise typer.Exit(1)

    # Check for existing setup
    result = subprocess.run(
        [*ssh_cmd, "test -d ~/.luce || test -d " + shlex.quote(setup_config.monorepo_path)],
        capture_output=True,
    )
    existing_setup = result.returncode == 0

    # Set default artifact dir if not specified
    if setup_config.remote_luce_config is None:
        setup_config.remote_luce_config = {}
    if "artifact_dir" not in setup_config.remote_luce_config:
        setup_config.remote_luce_config["artifact_dir"] = "~/artifacts"

    # Build remote luce config
    remote_doc = tomlkit.document()
    remote_doc.add(tomlkit.comment("Automatically generated by `luce setup remote`"))
    if "name" not in setup_config.remote_luce_config:
        remote_doc["name"] = config_lib.get_user_name()
    remote_doc.update(setup_config.remote_luce_config)  # pyright: ignore[reportUnknownMemberType]

    # Build our new local config with new server
    local_doc, local_config_path = config_lib.get_or_create_toml_doc()
    if "servers" not in local_doc:
        local_doc["servers"] = tomlkit.table()
    local_doc["servers"][name] = {  # pyright: ignore[reportIndexIssue]
        "hostname": name,
        "remote_path": setup_config.monorepo_path,
    }

    # Build SSH config stanza
    ssh_lines = [
        f"Host {name}",
        f"  HostName {ip_address}",
        f"  User {user}",
    ]

    if setup_config.ssh_forward_agent:
        ssh_lines.append("  ForwardAgent yes")

    if setup_config.ssh_tunnel_notebook:
        ssh_lines.append("  LocalForward 8888 localhost:8888")

    if identity_file:
        ssh_lines.append(f"  IdentityFile {identity_file}")

    ssh_block = "\n".join(ssh_lines)
    # Read or create SSH config
    ssh_config_path = Path.home() / ".ssh/config"
    if ssh_config_path.exists():
        old_config = ssh_config_path.read_text()
    else:
        # Create empty config with correct permissions (600)
        ssh_config_path.parent.mkdir(mode=0o700, exist_ok=True)
        ssh_config_path.touch(mode=0o600)
        old_config = ""

    # Generate new config
    new_config = _update_ssh_config(old_config, name, ssh_block)

    # Check for credentials files for AWS, HuggingFace, wandb, etc.
    config_or_credential_files = [
        Path.home() / ".aws/config",
        Path.home() / ".aws/credentials",
        Path.home() / ".cache/huggingface/token",
        Path.home() / ".netrc",
    ]

    # Build bashrc and profile additions
    activate_script = f"{setup_config.monorepo_path}/lib/lucepkg/scripts/activate_luce.sh"
    bashrc_line = f"# Added by `luce setup remote`\nsource {activate_script}\n"

    profile_lines = "\n".join(
        [
            "# Added by `luce setup remote`",
            f"export PATH=$PATH:{setup_config.monorepo_path}/lib/lucepkg/bin",
        ]
    )

    #### Start printing our plan ####

    # Show SSH config update
    rich.print(
        "\n[bold blue]To set up your remote machine, I'll make this change to your SSH"
        " config:[/bold blue]"
    )
    diff = list(
        difflib.unified_diff(
            old_config.splitlines(keepends=True),
            new_config.splitlines(keepends=True),
            fromfile=str(ssh_config_path),
            tofile=str(ssh_config_path),
        )
    )
    if diff:
        diff_text = "".join(diff)
        syntax = rich.syntax.Syntax(
            diff_text.rstrip(),
            "diff",
            theme="ansi_dark",
            word_wrap=True,
            background_color="default",
        )
        rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))
    else:
        rich.print("[green](no changes needed)[/green]")

    # Show AWS and huggingface files
    rich.print(
        "\n[bold blue]I'll copy these config/credential files to the remote machine:[/bold blue]"
    )
    for file in config_or_credential_files:
        if file.exists():
            rich.print(f"  [green]✓[/green] {file}")
        else:
            rich.print(f"  [yellow]⚠[/yellow] {file} [yellow](not found; skipping)[/yellow]")

    # Show local luce config update
    rich.print(
        "\n[bold blue]I'll update your ~/.luce/config.toml with this server's info:[/bold blue]"
    )
    diff = list(
        difflib.unified_diff(
            local_config_path.read_text().splitlines(keepends=True),
            tomlkit.dumps(local_doc).splitlines(  # pyright: ignore[reportUnknownMemberType]
                keepends=True
            ),
            fromfile=str(local_config_path),
            tofile=str(local_config_path),
        )
    )
    if diff:
        diff_text = "".join(diff)
        syntax = rich.syntax.Syntax(
            diff_text.rstrip(),
            "diff",
            theme="ansi_dark",
            word_wrap=True,
            background_color="default",
        )
        rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))
    else:
        rich.print("[green](no changes needed)[/green]")

    # Show remote luce config
    rich.print(
        "\n[bold blue]I'll create this ~/.luce/config.toml on the remote machine:[/bold blue]"
    )
    syntax = rich.syntax.Syntax(
        tomlkit.dumps(remote_doc).rstrip(),  # pyright: ignore[reportUnknownMemberType]
        "toml",
        theme="ansi_dark",
        word_wrap=True,
        background_color="default",
    )
    rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))

    # Show profile addition
    rich.print("\n[bold blue]I'll add these line to the remote ~/.profile:[/bold blue]")
    syntax = rich.syntax.Syntax(
        profile_lines.rstrip(),
        "bash",
        theme="ansi_dark",
        word_wrap=True,
        background_color="default",
    )
    rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))

    # Show bashrc addition
    rich.print("\n[bold blue]I'll add this line to the remote ~/.bashrc:[/bold blue]")
    syntax = rich.syntax.Syntax(
        bashrc_line.rstrip(),
        "bash",
        theme="ansi_dark",
        word_wrap=True,
        background_color="default",
    )
    rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))

    # Show zshrc addition if zsh is installed
    zsh_path = Path.home() / ".zshrc"
    if zsh_path.exists():
        rich.print("\n[bold blue]I'll add this line to the remote ~/.zshrc:[/bold blue]")
        syntax = rich.syntax.Syntax(
            bashrc_line.rstrip(),
            "bash",
            theme="ansi_dark",
            word_wrap=True,
            background_color="default",
        )
        rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))
    else:
        rich.print("\n[bold blue]Skipping zshrc addition (zsh not installed).[/bold blue]")

    # Show push step
    rich.print("\n[bold blue]I'll copy the monorepo to the server:[/bold blue]")
    syntax = rich.syntax.Syntax(
        f"luce push {name}",
        "bash",
        theme="ansi_dark",
        word_wrap=True,
        background_color="default",
    )
    rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))

    # Show setup commands
    rich.print(
        "\n[bold blue]Then I'll run these commands over ssh to set up the remote machine"
        " environment:[/bold blue]"
    )
    setup_commands = "\n".join(
        [
            "luce uv install",
            "luce install",
            f"mkdir -p {setup_config.remote_luce_config['artifact_dir']}",
        ]
    )
    syntax = rich.syntax.Syntax(
        setup_commands,
        "bash",
        theme="ansi_dark",
        word_wrap=True,
        background_color="default",
    )
    rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))

    # Show custom commands status
    if setup_config.custom_commands:
        rich.print(
            "\n[bold blue]Finally, I'll run these custom commands from ~/.luce/config.toml over"
            " ssh:[/bold blue]"
        )
        syntax = rich.syntax.Syntax(
            setup_config.custom_commands.rstrip(),
            "bash",
            theme="ansi_dark",
            word_wrap=True,
            background_color="default",
        )
        rich.print(Panel(syntax, border_style="dim", padding=(0, 2)))
    else:
        rich.print(
            "\n[bold blue]Finally, I could run custom commands from ~/.luce/config.toml over ssh,"
            " but there are none.[/bold blue]"
        )
        rich.print(
            "[dim]Tip: You can add custom commands to run during setup by adding a"
            r" 'custom_commands' string to the \[remote_setup] section of ~/.luce/config.toml[/dim]"
        )

    if existing_setup:
        rich.print(
            "\n[yellow]⚠ Warning: It looks like this machine has already been set up "
            "(found existing ~/.luce directory or monorepo).[/yellow]"
        )
        rich.print(
            "[yellow]Continuing will overwrite existing configuration and may be"
            " destructive.[/yellow]"
        )

    # Get confirmation (unless accept_all is specified)
    rich.print("\n[bold blue]Ready to proceed with setup![/bold blue]")
    if not accept_all:
        response = input("\nWould you like to proceed? [y/N] ")
        if response.lower() != "y":
            rich.print("[yellow]Setup aborted.[/yellow]")
            raise typer.Exit(0)
    else:
        rich.print("\n[blue]Auto-accepting confirmation with --accept-all...[/blue]")

    rich.print("\n[bold blue]Executing setup plan...[/bold blue]")

    # 1. Update SSH config
    rich.print("\n[blue]Updating SSH config...[/blue]")
    ssh_config_path.write_text(new_config)
    ssh_config_path.chmod(0o600)  # Ensure correct permissions

    # 2. Copy credentials
    rich.print("\n[blue]Copying config and credentials files...[/blue]")
    for file in config_or_credential_files:
        if file.exists():
            file_relative_to_home = file.relative_to(Path.home())
            # Create remote directory if it doesn't exist
            subprocess.run(["ssh", name, f"mkdir -p ~/{file_relative_to_home.parent}/"], check=True)

            # Copy file
            subprocess.run(
                ["scp", str(file), f"{name}:~/{file_relative_to_home.parent}/"], check=True
            )
        else:
            rich.print(f"[yellow]Skipping {file} (not found)[/yellow]")

    # 3. Update local luce config
    rich.print("\n[blue]Updating local luce config...[/blue]")
    local_config_path.parent.mkdir(mode=0o700, exist_ok=True)
    local_config_path.write_text(
        tomlkit.dumps(local_doc)  # pyright: ignore[reportUnknownMemberType]
    )

    # 4. Create remote luce config
    rich.print("\n[blue]Creating remote luce config...[/blue]")
    subprocess.run(["ssh", name, "mkdir -p ~/.luce"], check=True)
    subprocess.run(
        ["ssh", name, "cat > ~/.luce/config.toml"],
        input=tomlkit.dumps(remote_doc).encode(),  # pyright: ignore[reportUnknownMemberType]
        check=True,
    )

    # 5. Update remote bashrc
    rich.print("\n[blue]Updating remote bashrc...[/blue]")
    subprocess.run(["ssh", name, "cat >> ~/.bashrc"], input=bashrc_line.encode(), check=True)

    if zsh_path.exists():
        rich.print("\n[blue]Updating remote zshrc...[/blue]")
        subprocess.run(["ssh", name, "cat >> ~/.zshrc"], input=bashrc_line.encode(), check=True)

    rich.print("\n[blue]Updating remote profile...[/blue]")
    subprocess.run(["ssh", name, "cat >> ~/.profile"], input=profile_lines.encode(), check=True)

    # 6. Push monorepo
    rich.print("\n[blue]Pushing monorepo to server...[/blue]")
    sync_lib.push_to_server(
        name,
        config_lib.ServerConfig(
            hostname=ip_address,
            remote_path=setup_config.monorepo_path,
            user=user,
            identity_file=str(identity_file) if identity_file else None,
        ),
    )

    # 7. Set up remote environment
    rich.print("\n[blue]Setting up remote environment...[/blue]")
    commands = [
        "set -e",
        f"source {activate_script}",
        "luce uv install",
        "luce install",
        "luce --install-completion",
        f"mkdir -p {setup_config.remote_luce_config['artifact_dir']}",
    ]

    subprocess.run(["ssh", name, "bash -c " + shlex.quote("\n".join(commands))], check=True)

    # 8. Run custom commands if any
    if setup_config.custom_commands:
        rich.print("\n[blue]Running custom commands...[/blue]")
        subprocess.run(
            ["ssh", name, "bash -c " + shlex.quote("set -e\n" + setup_config.custom_commands)],
            check=True,
        )

    rich.print("\n[green]Setup completed successfully![/green]")


@app.command()
def rm(
    name: Annotated[
        str,
        typer.Argument(
            help="Name of the server to remove",
            autocompletion=config_lib.complete_server_names,
        ),
    ],
    remove_ssh_config: Annotated[
        bool,
        typer.Option(
            "--remove-ssh-config", "-s", help="Also remove entry from SSH config if it exists"
        ),
    ] = False,
):
    """Remove a server from the luce configuration.

    This will remove the server from ~/.luce/config.toml.
    Optionally also removes the corresponding entry from ~/.ssh/config.
    """
    # Check if server exists in config
    try:
        servers = config_lib.get_server_configs()
        if name not in servers:
            print(f"Error: Server '{name}' not found in luce config", file=sys.stderr)
            raise typer.Exit(1)
    except typer.Exit as e:
        if e.exit_code == 1:
            # This can happen if no servers are configured at all
            print("Error: No servers found in config", file=sys.stderr)
        raise

    # Remove SSH config entry if requested
    if remove_ssh_config:
        ssh_config_path = Path.home() / ".ssh/config"
        if ssh_config_path.exists():
            rich.print(f"[blue]Removing SSH config entry for {name}...[/blue]")
            old_config = ssh_config_path.read_text()
            new_config = _remove_ssh_host(old_config, name)

            # Only update if there was an actual change
            if new_config != old_config:
                ssh_config_path.write_text(new_config)
                rich.print(f"[green]Removed SSH config entry for {name}[/green]")
            else:
                rich.print(f"[yellow]No SSH config entry found for {name}[/yellow]")

    # Remove server from luce config
    rich.print(f"[blue]Removing server '{name}' from luce config...[/blue]")
    config_lib.remove_server_from_config(name)
    rich.print(f"[green]Server '{name}' removed successfully[/green]")


def _remove_ssh_host(old_config: str, host: str) -> str:
    """Remove a Host block from SSH config.

    Args:
        old_config: Existing SSH config contents
        host: Host to remove (exact match after "Host ")

    Returns:
        Updated SSH config contents with the host removed
    """
    lines = old_config.splitlines()
    result: list[str] = []
    i = 0

    while i < len(lines):
        # Check for Host or Match directive, ignoring whitespace
        if lines[i].strip().startswith(("Host ", "Match ")):
            if lines[i].strip() == f"Host {host}":
                # Found our host - skip the block
                while i < len(lines):
                    if i == len(lines) - 1 or lines[i + 1].strip().startswith(("Host ", "Match ")):
                        break
                    i += 1
            else:
                # Different host - keep original line
                result.append(lines[i])
        else:
            # Keep original line
            result.append(lines[i])
        i += 1

    return "\n".join(result)


def _update_ssh_config(old_config: str, host: str, new_block: str) -> str:
    """Update SSH config, replacing existing Host block if it exists.

    Note: Not well tested; don't use without looking at the output first!

    Args:
        old_config: Existing SSH config contents
        host: Host to look for (exact match after "Host ")
        new_block: New config block to insert

    Returns:
        Updated SSH config contents with original formatting preserved
    """
    lines = old_config.splitlines()
    result: list[str] = []
    i = 0
    found = False

    while i < len(lines):
        # Check for Host or Match directive, ignoring whitespace
        if lines[i].strip().startswith(("Host ", "Match ")):
            if lines[i].strip() == f"Host {host}":
                # Found our host - skip the old block
                found = True
                while i < len(lines):
                    if i == len(lines) - 1 or lines[i + 1].strip().startswith(("Host ", "Match ")):
                        break
                    i += 1
                # Insert new block
                result.append(new_block)
                result.append("")
            else:
                # Different host - keep original line
                result.append(lines[i])
        else:
            # Keep original line
            result.append(lines[i])
        i += 1

    # If we didn't find the host, add the new block at the end
    if not found:
        if result and result[-1] != "":
            result.append("")  # Add blank line before new block
        result.append(new_block)

    return "\n".join(result)
