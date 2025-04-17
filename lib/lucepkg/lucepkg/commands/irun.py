import shlex
import subprocess
import sys
from typing import Annotated, Optional

import typer
from luce_lib import config_lib
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

app = typer.Typer(help="Server command execution utilities")
console = Console()


@app.command()
def irun(
    server_name: Annotated[
        str,
        typer.Argument(
            help="Server to run the command on",
            autocompletion=config_lib.complete_server_names,
        ),
    ],
    command: Annotated[
        str,
        typer.Argument(
            help="Command to run in the tmux session",
        ),
    ],
    tmux_session: Annotated[
        Optional[str],
        typer.Argument(
            help="Name of tmux session to use (default: 'lucerun')",
        ),
    ] = "lucerun",
):
    """
    Run a command in a tmux session on a server.

    Creates a new tmux session if one doesn't exist, and runs the command in the first window/pane.
    If there's already a command running in the first window, it will exit with an error message.

    Examples:
        luce irun my-server "python my_script.py"
        luce irun gpu-server "nvidia-smi -l 5" monitor-gpu
    """
    # Get server config
    try:
        servers = config_lib.get_server_configs()
        if server_name not in servers:
            console.print(
                f"[bold red]Error:[/] Server '{server_name}' not found in config", file=sys.stderr
            )
            raise typer.Exit(1)
        server = servers[server_name]
    except typer.Exit:
        console.print(
            "[bold red]Error:[/] No servers configured. Run [cyan]`luce config add-server`[/] first.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    # Build SSH command base
    host_str = f"{server.user}@{server.hostname}" if server.user else server.hostname
    ssh_base = ["mosh"]
    if server.identity_file:
        ssh_base.extend(["--ssh", f"ssh -i {shlex.quote(server.identity_file)}"])
    ssh_base.append(host_str)

    # Step 1: Check if the session exists and if there are any commands running in it
    with console.status(
        f"[bold cyan]Checking for existing tmux session {tmux_session} on {host_str}...[/]",
        spinner="dots",
    ):
        # Script to check if session exists and if the first pane is running any processes
        check_script = (
            f"SESSION='{tmux_session}'; "
            "WINDOW='0'; "
            "PANE='0'; "
            'if ! tmux has-session -t "$SESSION" 2>/dev/null; then '
            "  echo 'NO_SESSION'; "
            "  exit 0; "
            "fi; "
            # Get the pane PID
            "PANE_PID=$(tmux display-message -p -t \"${SESSION}:${WINDOW}.${PANE}\" '#{pane_pid}' 2>/dev/null); "
            'if [ -z "$PANE_PID" ]; then '
            "  echo 'INVALID_PANE'; "
            "  exit 0; "
            "fi; "
            # Check if there's any foreground process running in the pane
            # First, get pane tty
            "PANE_TTY=$(tmux display-message -p -t \"${SESSION}:${WINDOW}.${PANE}\" '#{pane_tty}'); "
            # Find processes using this TTY and check if they're just shells or non-shell processes
            "PROCESSES=$(ps -o stat=,pid=,command= -t ${PANE_TTY##/dev/} | grep -v 'Ss\\|Ss+'); "
            'if [ -z "$PROCESSES" ]; then '
            "  echo 'PANE_IDLE'; "
            "else "
            "  echo 'PANE_BUSY'; "
            '  echo "$PROCESSES"; '
            "fi"
        )

        # Add the command to SSH base without mosh
        ssh_cmd = ["ssh"]
        if server.identity_file:
            ssh_cmd.extend(["-i", server.identity_file])
        ssh_cmd.append(host_str)
        ssh_cmd.append(check_script)

        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                console.print(
                    f"[bold red]Error:[/] Failed to check tmux session on server", file=sys.stderr
                )
                console.print(result.stderr, style="red")
                raise typer.Exit(1)
        except Exception as e:
            console.print(f"[bold red]Error:[/] Failed to connect to server: {e}", file=sys.stderr)
            raise typer.Exit(1)

    # Parse result of session/pane check
    session_status = result.stdout.strip()

    # Create session if it doesn't exist
    if "NO_SESSION" in session_status:
        console.print(
            f"[bold yellow]No tmux session named '{tmux_session}' found[/] - creating a new one"
        )
        create_session = True
    elif "INVALID_PANE" in session_status:
        console.print(
            f"[bold yellow]Invalid pane in session '{tmux_session}'[/] - will create a new window"
        )
        create_session = False
    elif "PANE_BUSY" in session_status:
        console.print(
            f"[bold red]Error:[/] The first pane in session '{tmux_session}' is already running a command:"
        )
        # Extract the process details from the output
        process_lines = [line for line in session_status.split("\n")[1:] if line.strip()]
        for line in process_lines:
            console.print(f"  [bold yellow]{line}[/]")
        console.print("\nUse a different session name or terminate the running command first.")
        raise typer.Exit(1)
    else:  # PANE_IDLE
        console.print(
            f"[bold green]Session '{tmux_session}' exists and is idle[/] - will run command"
        )
        create_session = False

    # Properly escape the command for shell execution
    escaped_command = command.replace("'", "'\\''")

    # Construct command to run in the tmux session
    if create_session:
        # Create a new session with remain-on-exit enabled
        tmux_cmd = (
            # First create a session with a dummy command that will keep running
            f"tmux new-session -d -s '{tmux_session}' 'bash' && "
            # Set remain-on-exit for the window
            f"tmux set-option -t '{tmux_session}' remain-on-exit on && "
            # Send the actual command to the session
            f"tmux send-keys -t '{tmux_session}:0.0' '{escaped_command}' Enter && "
            f"echo 'Command started in new tmux session \"{tmux_session}\"'"
        )
    else:
        tmux_cmd = (
            # Make sure remain-on-exit is set for this session
            f"tmux set-option -t '{tmux_session}' remain-on-exit on && "
            # Clear any previous command with Ctrl+C
            f"tmux send-keys -t '{tmux_session}:0.0' C-c && "
            f"sleep 0.5 && "
            # Send the command to the session
            f"tmux send-keys -t '{tmux_session}:0.0' '{escaped_command}' Enter && "
            f"echo 'Command started in existing tmux session \"{tmux_session}\"'"
        )

    # Execute the tmux command on the server
    with console.status(f"[bold cyan]Starting command on {host_str}...[/]", spinner="dots"):
        # Add the command to SSH base
        ssh_cmd = ["ssh"]
        if server.identity_file:
            ssh_cmd.extend(["-i", server.identity_file])
        ssh_cmd.append(host_str)
        ssh_cmd.append(tmux_cmd)

        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                console.print(
                    f"[bold red]Error:[/] Failed to start command on server", file=sys.stderr
                )
                console.print(result.stderr, style="red")
                raise typer.Exit(1)
        except Exception as e:
            console.print(f"[bold red]Error:[/] Failed to connect to server: {e}", file=sys.stderr)
            raise typer.Exit(1)

    output_text = Text()
    output_text.append("Command: ", style="bold")
    output_text.append(command, style="bold cyan")
    output_text.append("\nServer: ", style="bold")
    output_text.append(host_str, style="bold green")
    output_text.append("\nTmux session: ", style="bold")
    output_text.append(tmux_session, style="bold magenta")
    output_text.append("\n\nTo attach to this session, run: ", style="")
    output_text.append(f"luce imux {server_name} {tmux_session}", style="bold yellow")

    console.print(
        Panel(
            output_text,
            title="Command Started Successfully",
            border_style="green",
        )
    )
