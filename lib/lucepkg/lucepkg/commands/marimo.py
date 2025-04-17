import copy
import datetime
import json
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Annotated, Any, Dict, Optional

import markdownify
import typer
from luce_lib import config_lib, monorepo_util

app = typer.Typer(help="Marimo notebook commands")


def find_free_port():
    """Find a free port on localhost"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


# Hidden command for internal use
@app.command(name="_internal_server_tunnel", hidden=True)
def internal_server_tunnel(
    notebook_path: Annotated[
        str, typer.Argument(help="Path to the marimo notebook file on remote server")
    ],
    server_name: Annotated[str, typer.Argument(help="Name of the server to connect to")],
    local_state_file: Annotated[str, typer.Argument(help="Path to the local state file")],
    tmux_session: Annotated[str, typer.Argument(help="Name of the tmux session")],
):
    """Internal command to create an SSH tunnel to a remote marimo server

    This is an internal command used by 'luce marimo open --server'.
    It is not meant to be used directly.
    """

    # Get server config
    server_configs = config_lib.get_server_configs()
    if server_name not in server_configs:
        print(f"Error: Server '{server_name}' not found in config", file=sys.stderr)
        raise typer.Exit(1)

    server_config = server_configs[server_name]

    # Convert paths to Path objects
    remote_path = Path(notebook_path)
    local_state_path = Path(local_state_file)

    # Start the remote server
    print(f"Starting marimo server on {server_name}...")

    # Prepare base SSH command with identity file if provided
    ssh_base_cmd = ["ssh"]
    if server_config.identity_file:
        ssh_base_cmd.extend(["-i", server_config.identity_file])

    if server_config.user:
        ssh_base_cmd.append(f"{server_config.user}@{server_config.hostname}")
    else:
        ssh_base_cmd.append(f"{server_config.hostname}")

    # SSH command to start the server
    start_cmd = ssh_base_cmd.copy()
    luce_exc = shlex.quote(str(Path(server_config.remote_path) / "lib/lucepkg/bin/luce"))
    remote_open = f"{luce_exc} marimo open --headless {shlex.quote(str(remote_path))}"
    start_cmd.append(f"bash -l -c {shlex.quote(remote_open)}")

    # Run the SSH command
    subprocess.run(start_cmd, check=True)

    # Get the remote state file content
    remote_state_file = f"{remote_path.parent}/__marimo__/{remote_path.stem}.luce-state.json"
    get_state_cmd = ssh_base_cmd.copy()
    get_state_cmd.append(f"cat {shlex.quote(str(remote_state_file))}")

    # Run the command to get the remote state
    try:
        result = subprocess.run(get_state_cmd, capture_output=True, text=True, check=True)
        remote_state = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Error: Failed to get remote server information: {e}", file=sys.stderr)
        raise typer.Exit(1)

    # Find a free local port
    local_port = find_free_port()

    # Create the local state file with tunnel information
    session_info = {
        "host": "localhost",
        "port": local_port,
        "token": remote_state["token"],
        "tmux_name": tmux_session,
        "is_tunnel": True,
        "remote_server": server_name,
        "remote_notebook_path": str(remote_path),
        "remote_port": remote_state["port"],
    }

    with open(local_state_path, "w") as f:
        json.dump(session_info, f, indent=2)

    print(f"Tunnel information saved to {local_state_path}")

    # Create the SSH tunnel
    print(
        f"Creating SSH tunnel from localhost:{local_port} to localhost:{remote_state['port']} on"
        f" {server_name}"
    )

    # SSH tunnel command
    tunnel_cmd = ssh_base_cmd.copy()
    tunnel_cmd.insert(1, "-N")  # Don't execute a remote command
    tunnel_cmd.insert(1, "-L")  # Local port forwarding
    tunnel_cmd.insert(2, f"{local_port}:localhost:{remote_state['port']}")

    # Start the tunnel in a loop to handle disconnections
    while True:
        tunnel_process = None
        try:
            print("Starting SSH tunnel...")
            tunnel_process = subprocess.Popen(tunnel_cmd)

            # Print success message
            print("Tunnel established. Server accessible at:")
            print(f"http://localhost:{local_port}?access_token={remote_state['token']}")
            print("\nPress Ctrl+C to stop the tunnel and shutdown the server")

            # Wait for the tunnel process to terminate
            tunnel_process.wait()

            # If we get here, the tunnel terminated unexpectedly
            print("Tunnel disconnected. Reconnecting in 2 seconds...")
            time.sleep(2)
        except KeyboardInterrupt:
            # Handle Ctrl+C
            break

    print("\nShutting down tunnel and remote server...")

    # Kill the tunnel if it's still running
    if tunnel_process is not None and tunnel_process.poll() is None:
        tunnel_process.terminate()
        tunnel_process.wait()

    # Shutdown the remote server
    shutdown_cmd = ssh_base_cmd.copy()
    remote_shutdown = f"{luce_exc} marimo shutdown {shlex.quote(str(remote_path))}"
    shutdown_cmd.append(f"bash -l -c {shlex.quote(remote_shutdown)}")

    try:
        subprocess.run(shutdown_cmd, check=True)
        print("Remote server shut down successfully")
    except subprocess.CalledProcessError:
        print("Warning: Failed to shut down remote server properly", file=sys.stderr)

    # Remove the state file
    try:
        if local_state_path.exists():
            local_state_path.unlink()
            print(f"Removed state file {local_state_path}")
    except Exception as e:
        print(f"Warning: Failed to remove state file: {e}", file=sys.stderr)


def find_cells_by_name(notebook_data: Dict[str, Any], cell_name: str) -> list[Dict[str, Any]]:
    """Find all cells in a notebook by their name."""
    cells: list[Dict[str, Any]] = []
    for cell in notebook_data.get("cells", []):
        # Check if the cell has marimo metadata with a name
        cell_metadata = cell.get("metadata", {}).get("marimo", {})
        if cell_name == "@all" or cell_metadata.get("name") == cell_name:
            cells.append(cell)
    return cells


def postprocess_cell_and_get_chars(cell: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
    """Postprocess a cell to create plaintext summaries of HTML content"""
    cell = copy.deepcopy(cell)
    total_chars = 0
    for i, output in enumerate(cell["outputs"]):
        name = cell.get("metadata", {}).get("marimo", {}).get("name", f"Cell {i}")
        try:
            if output["output_type"] == "display_data":
                assert "data" in output
                if "text/plain" in output["data"]:
                    total_chars += len(output["data"]["text/plain"])
                    print(f"{name}: Found text/plain output ({total_chars} characters)")
                else:
                    if "text/html" in output["data"]:
                        markdown_version = markdownify.markdownify(
                            "".join(output["data"]["text/html"])
                        )
                        output["data"]["text/plain"] = markdown_version
                        total_chars += len(markdown_version)
                        print(
                            f"{name}: Converted text/html output to text/plain "
                            f"({len(markdown_version)} characters)"
                        )
                    else:
                        print(
                            "Warning: Could not convert cell output with mime types"
                            f" {tuple(output['data'].keys())}",
                            file=sys.stderr,
                        )
            elif output["output_type"] == "stream":
                output_len = len("".join(output["text"]))
                print(f"{name}: Found stream output ({output_len} characters)")
        except Exception as e:
            print(f"Warning: Failed to postprocess cell outputs: {e}", file=sys.stderr)
    return cell, total_chars


@app.command()
def fetch_output(
    notebook_path: Annotated[str, typer.Argument(help="Path to the marimo notebook file")],
    cell_name: Annotated[str, typer.Argument(help="Name of the cell to fetch output from")],
):
    """Fetch the output of a specific cell from a marimo notebook

    This command reads the output of a named cell from a marimo notebook.
    The notebook must have been executed by a marimo kernel, which saves
    the outputs in the __marimo__ directory.

    The command will:
    1. Wait up to 10 seconds for the cell output to become available
    2. Extract the named cell to a separate notebook
    3. Print the path to the extracted notebook

    Special cell name:
    - "@all": Returns the path to the entire notebook output instead of extracting a single cell
    """
    # Convert to Path object and get absolute path
    py_path = Path(notebook_path).resolve()

    # Check if the Python file exists
    if not py_path.exists():
        print(f"Error: Notebook file {notebook_path} not found", file=sys.stderr)
        raise typer.Exit(1)

    # Determine the path to the __marimo__ directory
    marimo_dir = py_path.parent / "__marimo__"

    # Check if the __marimo__ directory exists
    if not marimo_dir.exists() or not marimo_dir.is_dir():
        print(
            "Error: __marimo__ directory not found. Make sure the notebook has been executed.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    # Build the path to the notebook file
    notebook_file = marimo_dir / f"{py_path.stem}.ipynb"

    # Check if we have a remote session
    luce_state_file = marimo_dir / f"{py_path.stem}.luce-state.json"
    luce_state = None
    is_remote = False
    if luce_state_file.exists():
        with open(luce_state_file, "r") as f:
            luce_state = json.load(f)
        if luce_state.get("is_tunnel"):
            print(
                f"Notebook is running on remote server {luce_state['remote_server']}; need to copy!"
            )
            is_remote = True

    # Set up timeout for waiting for both file and cell
    timeout = 10  # seconds
    start_time = time.time()
    raw_cells = None
    notebook_data = None

    # Poll until we find both the file and the cell, or timeout
    while time.time() - start_time < timeout:

        if is_remote:
            assert luce_state is not None
            # Copy the notebook from the remote server
            remote_notebook_path = Path(luce_state["remote_notebook_path"])
            remote_notebook_output_file = (
                remote_notebook_path.parent / "__marimo__" / f"{py_path.stem}.ipynb"
            )

            # Get server configuration
            ssh_config = config_lib.get_server_configs().get(luce_state["remote_server"], None)
            if ssh_config:
                # Use rsync instead of scp for better reliability
                rsync_base = ["rsync", "-avz"]
                if ssh_config.identity_file:
                    rsync_base.extend(["-e", f"ssh -i {ssh_config.identity_file}"])

                # Build the remote URL
                if ssh_config.user:
                    remote_url = (
                        f"{ssh_config.user}@{ssh_config.hostname}:{remote_notebook_output_file}"
                    )
                else:
                    remote_url = f"{ssh_config.hostname}:{remote_notebook_output_file}"

                # Copy the notebook file from remote to local
                rsync_cmd = rsync_base + [remote_url, str(notebook_file)]

                try:
                    subprocess.run(rsync_cmd, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Warning: Failed to copy remote notebook: {e}", file=sys.stderr)
                    print(
                        "The notebook may not be available or the server connection failed.",
                        file=sys.stderr,
                    )
            else:
                print(
                    f"Warning: Could not find server config for {luce_state['remote_server']}",
                    file=sys.stderr,
                )
        else:
            # Skip if the file doesn't exist yet
            if not notebook_file.exists():
                time.sleep(0.5)
                continue

        assert notebook_file.exists()

        # Try to read and parse the notebook file
        try:
            with open(notebook_file, "r") as f:
                notebook_data = json.load(f)

            # Find the cell by name
            raw_cells = find_cells_by_name(notebook_data, cell_name)
            if raw_cells:
                # We found the cell, break out of the loop
                break
        except json.JSONDecodeError:
            # If we can't parse the file, it might be in the middle of being written
            pass

        # Wait a bit before checking again
        time.sleep(0.5)

    # If we timed out or couldn't find the cell
    if notebook_data is None:
        print(
            f"Error: Notebook file {notebook_file} not found or could not be read in __marimo__"
            " directory.\n\nInstructions for "
            "Claude: DO NOT try to fix this on your own or read this another way! It is very "
            "unlikely you can solve this yourself. If you have an idea for what to try, ask the "
            "user for confirmation first. But it's OK to just wait for the user to fix it.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    if not raw_cells:
        print(
            f"Error: Cell named '{cell_name}' not found in the notebook.\n\nInstructions for "
            "Claude: DO NOT try to fix this on your own or read this another way! It is very "
            "unlikely you can solve this yourself. If you have an idea for what to try, ask the "
            "user for confirmation first. But it's OK to just wait for the user to fix it.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    # Process the cell to create plaintext summaries of HTML content
    rewritten_cells = []
    total_chars = 0
    for cell in raw_cells:
        cell, chars = postprocess_cell_and_get_chars(cell)
        rewritten_cells.append(cell)
        total_chars += chars

    # Create a new notebook with just this cell
    extracted_notebook = {
        "cells": rewritten_cells,
        "metadata": notebook_data.get("metadata", {}),
        "nbformat": notebook_data.get("nbformat", 4),
        "nbformat_minor": notebook_data.get("nbformat_minor", 5),
    }

    # Write the extracted notebook
    extracted_path = marimo_dir / f"{py_path.stem}_{cell_name}__extracted_cell.ipynb"
    with open(extracted_path, "w") as f:
        json.dump(extracted_notebook, f, indent=1)

    # Print the result
    if cell_name == "@all":
        print(f"Full notebook output is at {notebook_file.absolute()}.")
    else:
        print(f"Extracted cell {cell_name} to {extracted_path.absolute()}.")

    if total_chars > 5000:
        print(
            "INSTRUCTIONS FOR CLAUDE: Cell outputs are very large! Please dispatch an agent to"
            " read it and produce a truncated version that contains all of the important info,"
            " instead of reading it all at once."
        )
    else:
        print("Claude: you can use your notebook tool to read it!")


@app.command(name="open")
def open_(
    notebook_path: Annotated[str, typer.Argument(help="Path to the marimo notebook file")],
    headless: Annotated[
        bool, typer.Option("--headless", help="Start server without opening browser")
    ] = False,
    server: Annotated[
        Optional[str],
        typer.Option("--server", "-s", help="Run on remote server instead of locally"),
    ] = None,
):
    """Open a marimo notebook in the browser

    This command opens a marimo notebook in the browser. It will:
    1. Check if there's an existing marimo server for this notebook
    2. Start a new server if needed in a detached tmux session
    3. Open the notebook URL in the default web browser (unless --headless is specified)

    The --headless option starts the server without opening the browser,
    which is useful for automated scenarios or remote server setups.

    The --server option runs the notebook on a remote server, setting up an SSH
    tunnel to make it accessible locally. The notebook must be in the monorepo.
    """

    # Convert to Path object and get absolute path
    py_path = Path(notebook_path).resolve()

    # If server is specified, check that the notebook is in the monorepo
    if server:
        try:
            monorepo_root = monorepo_util.find_monorepo_root()
            rel_path = py_path.relative_to(monorepo_root)
        except (ValueError, RuntimeError):
            print(
                f"Error: Notebook {notebook_path} must be in the monorepo to use with --server.",
                file=sys.stderr,
            )
            raise typer.Exit(1)

        try:
            server_config = config_lib.get_server_configs()[server]
        except KeyError:
            print(f"Error: Server '{server}' not found in config", file=sys.stderr)
            raise typer.Exit(1)

        remote_abs_path = Path(server_config.remote_path) / rel_path

        # Check that the notebook exists on the remote server and is up to date
        print("Verifying notebook is up to date on remote server...")

        # Compute local md5sum
        try:
            local_md5_result = subprocess.run(
                ["md5sum", str(py_path)], capture_output=True, text=True, check=True
            )
            local_md5 = local_md5_result.stdout.strip().split()[0]
        except (subprocess.CalledProcessError, IndexError) as e:
            print(f"Error computing local checksum: {e}", file=sys.stderr)
            raise typer.Exit(1)

        # Prepare SSH command with identity file if provided
        ssh_base_cmd = ["ssh"]
        if server_config.identity_file:
            ssh_base_cmd.extend(["-i", server_config.identity_file])

        if server_config.user:
            ssh_base_cmd.append(f"{server_config.user}@{server_config.hostname}")
        else:
            ssh_base_cmd.append(f"{server_config.hostname}")

        # Compute remote md5sum
        try:
            remote_md5_cmd = ssh_base_cmd.copy()
            remote_md5_cmd.append(f"md5sum {shlex.quote(str(remote_abs_path))}")
            remote_md5_result = subprocess.run(
                remote_md5_cmd, capture_output=True, text=True, check=True
            )
            remote_md5 = remote_md5_result.stdout.strip().split()[0]
        except (subprocess.CalledProcessError, IndexError) as e:
            print(f"Error: Remote notebook not found or inaccessible: {e}", file=sys.stderr)
            print(
                "Make sure the notebook exists on the remote server at the expected path.",
                file=sys.stderr,
            )
            raise typer.Exit(1)

        # Compare checksums
        if local_md5 != remote_md5:
            print(
                "Error: Notebook on remote server is out of sync with local version.",
                file=sys.stderr,
            )
            print("Please sync the notebook to the remote server first:", file=sys.stderr)
            print(f"  luce sync {server}", file=sys.stderr)
            raise typer.Exit(1)

        print("Checksum verified: local and remote notebooks match.")
    else:
        remote_abs_path = None

    # Check if the Python file exists locally
    if not py_path.exists():
        print(f"Error: Notebook file {notebook_path} not found", file=sys.stderr)
        raise typer.Exit(1)

    # Determine the path to the __marimo__ directory
    marimo_dir = py_path.parent / "__marimo__"

    # Create the __marimo__ directory if it doesn't exist
    if not marimo_dir.exists():
        marimo_dir.mkdir(parents=True)

    # Path to the state file
    state_file = marimo_dir / f"{py_path.stem}.luce-state.json"

    # Initialize with defaults
    session_info: dict[str, Any] = {
        "host": None,
        "port": None,
        "token": None,
        "tmux_name": None,
    }
    tmux_session = None
    tmux_log_file = marimo_dir / f"{py_path.stem}.tmux_out.log"

    # STEP 1: Get or create tmux session

    # Try to load existing state
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                saved_info = json.load(f)

                # Check for conflicts with server parameter
                if server and "remote_server" in saved_info:
                    saved_server = saved_info.get("remote_server")
                    if saved_server != server:
                        print(
                            f"Error: Notebook already running on server '{saved_server}', but"
                            f" '{server}' was requested.",
                            file=sys.stderr,
                        )
                        print(f"Run `luce marimo shutdown {notebook_path}` first.", file=sys.stderr)
                        raise typer.Exit(1)

                # If server was requested but state shows local server
                if server and "remote_server" not in saved_info:
                    print(
                        f"Error: Notebook already running locally, but server '{server}' was"
                        " requested.",
                        file=sys.stderr,
                    )
                    print(f"Run `luce marimo shutdown {notebook_path}` first.", file=sys.stderr)
                    raise typer.Exit(1)

                # If local was requested but state shows remote server
                if not server and "remote_server" in saved_info:
                    print(
                        "Error: Notebook already running on server"
                        f" '{saved_info['remote_server']}', but local execution was requested.",
                        file=sys.stderr,
                    )
                    print(f"Run `luce marimo shutdown {notebook_path}` first.", file=sys.stderr)
                    raise typer.Exit(1)

                # Update our session_info with any values from the saved file
                for key in session_info:
                    if key in saved_info and saved_info[key] is not None:
                        session_info[key] = saved_info[key]

        except (json.JSONDecodeError, FileNotFoundError):
            # If file can't be parsed, we'll just use defaults
            pass

    # Check if we have a tmux session already
    if session_info["tmux_name"] is not None:
        # Verify the session exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_info["tmux_name"]],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            # Session exists
            tmux_session = session_info["tmux_name"]
            print(f"Using existing tmux session: {tmux_session}")
        else:
            print(f"Ignoring old tmux session: {session_info['tmux_name']}")
            # Clear the session info
            session_info = {
                "host": None,
                "port": None,
                "token": None,
                "tmux_name": None,
            }

    # Create a new session if needed
    if tmux_session is None:
        tmux_log_file.unlink(missing_ok=True)
        if server:
            # Running on a remote server
            print(f"Setting up remote server on {server}...")

            # Generate a unique session name
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            tmux_session = f"luce_marimo_tunnel_{timestamp}_{py_path.stem}"

            # Update session_info with tmux session name and remote info before launching
            session_info["tmux_name"] = tmux_session
            session_info["remote_server"] = server
            session_info["remote_notebook_path"] = str(remote_abs_path)

            # Save the initial state file
            with open(state_file, "w") as f:
                json.dump(session_info, f, indent=2)

            # Create a new tmux session for the tunnel
            print(f"Starting SSH tunnel in tmux session '{tmux_session}'...")

            # Start the internal tunnel command in a new tmux session
            subprocess.run(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    tmux_session,
                    "-n",
                    "marimo-tunnel",
                    (
                        "luce marimo _internal_server_tunnel"
                        f" {shlex.quote(str(remote_abs_path))} {shlex.quote(server)} "
                        f"{shlex.quote(str(state_file))} {shlex.quote(tmux_session)} 2>&1"
                        f" | tee -i {shlex.quote(str(tmux_log_file))}"
                    ),
                ],
                check=True,
            )

        else:
            # Generate a unique session name for local server
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            tmux_session = f"luce_marimo_{timestamp}_{py_path.stem}"

            # Create a new tmux session
            print(f"Starting marimo server in tmux session '{tmux_session}'...")

            # Start the tmux session with the marimo server
            subprocess.run(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    tmux_session,
                    "-n",
                    "marimo",
                    (
                        f"luce run -p marimo -p edit {shlex.quote(str(py_path))} --watch --headless"
                        f" 2>&1 | tee -i {shlex.quote(str(tmux_log_file))}"
                    ),
                ],
                check=True,
            )

            # Save the tmux session name in case we need to resume later.
            session_info["tmux_name"] = tmux_session
            with open(state_file, "w") as f:
                json.dump(session_info, f, indent=2)

    # STEP 2: Try to get URL info if needed
    if (
        session_info["host"] is None
        or session_info["port"] is None
        or session_info["token"] is None
    ):
        print("Waiting for server to start...")

        # Different approach based on server type
        is_remote = server is not None

        # Poll for up to 15 seconds
        max_wait = 15  # seconds
        start_time = time.time()
        success = False

        while time.time() - start_time < max_wait:
            still_running_result = subprocess.run(
                ["tmux", "has-session", "-t", session_info["tmux_name"]],
                capture_output=True,
                check=False,
            )
            if still_running_result.returncode != 0:
                print("Warning: Server has exited unexpectedly!", file=sys.stderr)
                break
            time.sleep(0.5)

            if is_remote:
                # For remote servers, the _internal_server_tunnel command will update the state file
                if state_file.exists():
                    try:
                        with open(state_file, "r") as f:
                            updated_info = json.load(f)
                            # Check if we have all the connection info
                            if all(
                                key in updated_info and updated_info[key] is not None
                                for key in ["host", "port", "token"]
                            ):
                                session_info = updated_info
                                success = True
                                break
                    except (json.JSONDecodeError, FileNotFoundError):
                        pass
            else:
                # For local servers, we need to check the tmux output
                output = tmux_log_file.read_text()
                url_match = re.search(r"URL: (http://[^?\s]+)\?access_token=([^\s]+)", output)

                if url_match:
                    # Extract host, port, and token
                    base_url = url_match.group(1)
                    token = url_match.group(2)

                    # Parse the base URL to get host and port
                    url_parts = base_url.split("://")
                    host_port = url_parts[1].split(":")
                    host = host_port[0]
                    port = int(host_port[1]) if len(host_port) > 1 else 80

                    # Update server info
                    session_info["host"] = host
                    session_info["port"] = port
                    session_info["token"] = token

                    # Save the updated info
                    with open(state_file, "w") as f:
                        json.dump(session_info, f, indent=2)

                    success = True
                    break

            time.sleep(0.5)

        if server:
            session_str = "tunnel session"
        else:
            session_str = "marimo session"

        print(
            f"=== {session_str} status: ===\n"
            + tmux_log_file.read_text()
            + f"\n=== End {session_str} status ===\n"
        )

        if not success:
            print(
                "Warning: Could not determine server URL after waiting. "
                "The server might still be starting or encountered an error.\n\n"
                f"You can attach to the server with: tmux attach -t {tmux_session}\n"
                "You can also try running this command again after a few seconds.",
                file=sys.stderr,
            )
            raise typer.Exit(1)

    # STEP 3: Construct the URL to open and possibly open in browser
    url = (
        f"http://{session_info['host']}:{session_info['port']}?access_token={session_info['token']}"
    )

    # Open the URL in the default browser unless headless mode is specified
    if not headless:
        print(f"Opening {url} in your browser...")
        webbrowser.open(url)
    else:
        print(f"Server running at {url}")
        print("Browser not opened because --headless was specified.")

    # Print tmux session info
    if server:
        print(f"\nThe marimo tunnel is running in tmux session '{tmux_session}'.")
        print(f"You can attach to it with: tmux attach -t {tmux_session}")
        print(f"You can check its logs with: cat {tmux_log_file}")
        remote_log_file = (
            Path(session_info["remote_notebook_path"]).parent
            / "__marimo__"
            / (Path(session_info["remote_notebook_path"]).stem + ".tmux_out.log")
        )
        print(f"You can check the remote logs with: ssh {server} 'cat {remote_log_file}'")
    else:
        print(f"\nThe marimo server is running in tmux session '{tmux_session}'.")
        print(f"You can attach to it with: tmux attach -t {tmux_session}")
        print(f"You can check its logs at: {tmux_log_file}")
    print(f"To shut down the server: luce marimo shutdown {notebook_path}")


@app.command()
def reopen(
    notebook_path: Annotated[str, typer.Argument(help="Path to the marimo notebook file")],
):
    """Reopen a marimo notebook with an existing server

    This command reopens a browser connection to an existing marimo server.
    It does not start a new server, but simply reads the connection info from
    the state file and opens the browser to that URL.

    If the server is not running, you should use `luce marimo open` instead.
    """

    # Convert to Path object and get absolute path
    py_path = Path(notebook_path).resolve()

    # Check if the Python file exists
    if not py_path.exists():
        print(f"Error: Notebook file {notebook_path} not found", file=sys.stderr)
        raise typer.Exit(1)

    # Determine the path to the __marimo__ directory
    marimo_dir = py_path.parent / "__marimo__"

    # Path to the state file
    state_file = marimo_dir / f"{py_path.stem}.luce-state.json"

    # Check if state file exists
    if not state_file.exists():
        print(f"Error: No server information found for {notebook_path}", file=sys.stderr)
        print("Use `luce marimo open` to start a new server first.", file=sys.stderr)
        raise typer.Exit(1)

    # Load the server info
    try:
        with open(state_file, "r") as f:
            session_info = json.load(f)
    except json.JSONDecodeError:
        print(f"Error: Failed to parse state file {state_file}", file=sys.stderr)
        raise typer.Exit(1)

    # Check if we have the required connection info
    if not all(
        key in session_info and session_info[key] is not None for key in ["host", "port", "token"]
    ):
        print("Error: Incomplete server information in state file", file=sys.stderr)
        print("Try running `luce marimo open` to start a new server.", file=sys.stderr)
        raise typer.Exit(1)

    # Check if the tmux session exists
    tmux_session = session_info.get("tmux_name")
    if tmux_session:
        result = subprocess.run(
            ["tmux", "has-session", "-t", tmux_session], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            print(
                f"Warning: Tmux session '{tmux_session}' not found. The server may not be running.",
                file=sys.stderr,
            )
            print("Continuing anyway, but the connection might fail.", file=sys.stderr)

    # Construct the URL
    url = (
        f"http://{session_info['host']}:{session_info['port']}?access_token={session_info['token']}"
    )

    # Open the URL
    print(f"Opening {url} in your browser...")
    webbrowser.open(url)

    # Print session info if available
    if tmux_session:
        print(f"\nThe server is running in tmux session '{tmux_session}'.")
        print(f"You can attach to it with: tmux attach -t {tmux_session}")
        print(f"To shut down the server: luce marimo shutdown {notebook_path}")


@app.command()
def shutdown(
    notebook_path: Annotated[str, typer.Argument(help="Path to the marimo notebook file")],
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Force kill session if graceful shutdown fails")
    ] = False,
    archive_output: Annotated[
        bool, typer.Option(help="Archive the notebook output before shutting down")
    ] = True,
):
    """Shut down a running marimo server

    This command shuts down a marimo server that was started with 'luce marimo open'.
    It will:
    1. Find the tmux session for the server
    2. Archive the notebook output if requested (default: yes)
    3. Send Ctrl+C followed by 'y' to gracefully terminate the server
    4. Delete the state file

    Use --no-archive-output to skip archiving the notebook output.
    """

    # Convert to Path object and get absolute path
    py_path = Path(notebook_path).resolve()

    # Check if the Python file exists
    if not py_path.exists():
        print(f"Warning: Notebook file {notebook_path} not found", file=sys.stderr)

    # Determine the path to the __marimo__ directory
    marimo_dir = py_path.parent / "__marimo__"

    # Path to the state file
    state_file = marimo_dir / f"{py_path.stem}.luce-state.json"

    # Check if state file exists
    if not state_file.exists():
        print(f"No running server found for {notebook_path}", file=sys.stderr)
        raise typer.Exit(1)

    # Load the state file
    try:
        with open(state_file, "r") as f:
            session_info = json.load(f)
    except json.JSONDecodeError:
        print(f"Error: Failed to parse state file {state_file}", file=sys.stderr)
        raise typer.Exit(1)

    # Check if this is a remote server setup
    is_remote = "remote_server" in session_info and session_info["remote_server"] is not None
    remote_server = session_info.get("remote_server")
    remote_path = session_info.get("remote_notebook_path")

    # Get the tmux session name
    tmux_session = session_info.get("tmux_name")
    if not tmux_session:
        print("Error: No tmux session found in state file", file=sys.stderr)
        raise typer.Exit(1)

    # Check if the tmux session exists
    has_session_result = subprocess.run(
        ["tmux", "has-session", "-t", tmux_session], capture_output=True, text=True, check=False
    )

    # Handle archiving differently for remote servers
    if archive_output:
        if is_remote:
            # For remote servers, we need to first copy the file from the remote
            print(f"Archiving notebook output from remote server {remote_server}...")

            # Get the remote output path
            if remote_path:
                remote_output_file = (
                    f"{Path(remote_path).parent}/__marimo__/{Path(remote_path).stem}.ipynb"
                )

                # Create timestamp
                timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                archive_path = marimo_dir / f"{py_path.stem}.archived_output_{timestamp}.ipynb"

                # Prepare base SSH command with identity file if needed
                ssh_config = config_lib.get_server_configs().get(remote_server, None)
                if ssh_config:
                    scp_base = ["scp"]
                    if ssh_config.identity_file:
                        scp_base.extend(["-i", ssh_config.identity_file])

                    # Copy the notebook file from remote
                    if ssh_config.user:
                        remote_url = f"{ssh_config.user}@{ssh_config.hostname}:{remote_output_file}"
                    else:
                        remote_url = f"{ssh_config.hostname}:{remote_output_file}"
                    scp_cmd = scp_base + [remote_url, str(archive_path)]

                    try:
                        subprocess.run(scp_cmd, check=True)
                        print(f"Archived remote notebook output to {archive_path}")
                    except subprocess.CalledProcessError:
                        print("Error: Failed to archive remote notebook output", file=sys.stderr)
                        if not force:
                            raise typer.Exit(1)
                else:
                    print(
                        f"Error: Could not find server config for {remote_server}",
                        file=sys.stderr,
                    )
                    if not force:
                        raise typer.Exit(1)
            else:
                print("Error: Remote notebook path not found in state file", file=sys.stderr)
                if not force:
                    raise typer.Exit(1)
        else:
            # For local servers, archive the notebook file directly
            notebook_file = marimo_dir / f"{py_path.stem}.ipynb"

            if notebook_file.exists():
                # Create a timestamp for the archive
                timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

                # Create the archive path
                archive_path = marimo_dir / f"{py_path.stem}.archived_output_{timestamp}.ipynb"

                # Copy the notebook file
                shutil.copy2(notebook_file, archive_path)
                print(f"Archived notebook output to {archive_path}")

    if has_session_result.returncode != 0:
        if not force:
            print(
                f"Tmux session '{tmux_session}' not found, but state file exists.", file=sys.stderr
            )
            print("Use --force to delete the state file anyway.", file=sys.stderr)
            raise typer.Exit(1)
        else:
            print(f"Deleting state file for {notebook_path}")
            state_file.unlink()
            print("Server state deleted.")
            return
    else:
        # Handle shutdown differently for remote vs local servers
        if is_remote:
            print(f"Shutting down tunnel in tmux session '{tmux_session}'...")

            # For remote tunnels, just send Ctrl+C to the tunnel process
            # The tunnel process will handle the remote server shutdown
            subprocess.run(["tmux", "send-keys", "-t", tmux_session, "C-c"], check=True)
        else:
            # Local server shutdown
            print(f"Shutting down server in tmux session '{tmux_session}'...")

            # Send Ctrl+C
            subprocess.run(["tmux", "send-keys", "-t", tmux_session, "C-c"], check=True)

            # Brief pause before sending next command
            time.sleep(0.5)

            # Send "y" and Enter to confirm shutdown
            subprocess.run(["tmux", "send-keys", "-t", tmux_session, "y", "Enter"], check=True)

        # Wait for the session to terminate
        max_wait = 15
        start_time = time.time()
        while time.time() - start_time < max_wait:
            result = subprocess.run(
                ["tmux", "has-session", "-t", tmux_session],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                # Session no longer exists
                break
            time.sleep(0.5)

    # Check if the session is still running
    has_session_result_2 = subprocess.run(
        ["tmux", "has-session", "-t", tmux_session], capture_output=True, text=True, check=False
    )

    if has_session_result_2.returncode == 0 and force:
        # Session still exists, kill it forcefully
        print("Server not responding to graceful shutdown, killing session...")
        subprocess.run(["tmux", "kill-session", "-t", tmux_session], check=True)

        # For remote servers, also try to shut down the remote server directly
        if is_remote and remote_server and remote_path:
            print("Attempting to shut down remote server directly...")
            ssh_config = config_lib.get_server_configs().get(remote_server, None)
            if ssh_config:
                ssh_cmd = ["ssh"]
                if ssh_config.identity_file:
                    ssh_cmd.extend(["-i", ssh_config.identity_file])
                ssh_cmd.append(f"{ssh_config.user}@{ssh_config.hostname}")
                remote_shutdown_cmd = (
                    f"cd {Path(remote_path).parent} && luce marimo shutdown --force"
                    f" {Path(remote_path).name}"
                )
                ssh_cmd.append(remote_shutdown_cmd)

                try:
                    subprocess.run(ssh_cmd, check=True)
                except subprocess.CalledProcessError:
                    print("Warning: Failed to shut down remote server directly", file=sys.stderr)

    elif has_session_result_2.returncode == 0:
        print(
            "Server still running. You may need to attach to the session and shut it down"
            " manually:",
            file=sys.stderr,
        )
        print(f"  tmux attach -t {tmux_session}", file=sys.stderr)
        print("Or use --force to kill the session:", file=sys.stderr)
        print(f"  luce marimo shutdown {notebook_path} --force", file=sys.stderr)
        raise typer.Exit(1)

    # Delete the state file
    if state_file.exists():
        state_file.unlink()

    if is_remote:
        print("Remote server and tunnel shutdown complete.")
    else:
        print("Server shutdown complete.")
