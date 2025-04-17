import pathlib
import queue
import shlex
import subprocess
import sys
import tempfile
import threading
from typing import Any

import anyio
import anyio.to_thread
import typer
from luce_lib import config_lib, monorepo_util


def get_default_server() -> tuple[str, config_lib.ServerConfig]:
    """Get the first server from config.

    Returns:
        Tuple of (server_name, server_config)

    Raises:
        typer.Exit: If no servers configured
    """
    servers = config_lib.get_server_configs()
    try:
        name = next(iter(servers))
        return name, servers[name]
    except StopIteration:
        print("Error: No servers found in config file.", file=sys.stderr)
        raise typer.Exit(1)


def _build_ssh_cmd(config: config_lib.ServerConfig, control_path: str | None = None) -> list[str]:
    """Build SSH command with optional control path."""
    ssh_cmd = ["ssh"]
    if config.identity_file:
        ssh_cmd.extend(["-i", config.identity_file])
    if control_path:
        ssh_cmd.extend(["-o", f"ControlPath={control_path}"])
    ssh_cmd.append(f"{config.user}@{config.hostname}" if config.user else config.hostname)
    return ssh_cmd


def _build_rsync_ssh_cmd(config: config_lib.ServerConfig, control_path: str | None = None) -> str:
    """Build rsync SSH command string."""
    rsync_ssh_cmd = "ssh"
    if config.identity_file:
        rsync_ssh_cmd = f"ssh -i {shlex.quote(config.identity_file)}"
    if control_path:
        rsync_ssh_cmd = f"{rsync_ssh_cmd} -o ControlPath={shlex.quote(control_path)}"
    return rsync_ssh_cmd


def _build_base_rsync_cmd(
    config: config_lib.ServerConfig,
    control_path: str | None = None,
    paths: list[str] | None = None,
    source_dir: pathlib.Path | None = None,
) -> list[str]:
    """Build base rsync command with common options."""

    # Add path-specific includes/excludes if paths provided.
    # (Note: Rsync applies filters in order, where the first match wins. So we first include and
    # exclude the manually-configured options, then filter down to the specific paths, then exclude
    # everything else. This ensures that rsync only checks a subset of the files it would have
    # checked if no paths were provided.)
    rsync_cmd = [
        "rsync",
        "-avz",
        "-e",
        _build_rsync_ssh_cmd(config, control_path),
        "--include=.env",
        "--include=**/.gitignore",
        "--filter=:- .gitignore",
        "--exclude=/.git",
        "--exclude=/.rsync_backups",
    ]

    # Add path-specific includes/excludes if paths provided
    if paths is not None and source_dir is not None:
        for path in paths:
            # Get relative path from source directory
            rel_path = pathlib.Path(path).relative_to(source_dir)

            # Include all parent directories (but not necessarily their contents) and the file
            # itself. Including parent directories explicitly is necessary to get rsync to scan
            # them to find the file.
            parts = rel_path.parts
            for i in range(len(parts)):
                include_path = "/".join(parts[: i + 1])
                rsync_cmd.append(f"--include=/{include_path}")

        # Exclude everything else
        rsync_cmd.append("--exclude=**/*")

    return rsync_cmd


def _ensure_remote_backup_dir(
    ssh_cmd: list[str], remote_path: str, assume_backup_dir_exists: bool
) -> None:
    """Ensure remote backup directory exists."""
    if not assume_backup_dir_exists:
        subprocess.run(
            [
                *ssh_cmd,
                (
                    f"mkdir -p '{remote_path}/.rsync_backups' && "
                    f"echo '/*' >'{remote_path}/.rsync_backups/.gitignore'"
                ),
            ],
            check=True,
        )


def _run_rsync(
    rsync_cmd: list[str],
    source_dir: pathlib.Path,
    host_str: str,
    remote_path: str,
    backup_dir: str,
) -> None:
    """Run rsync command with backup."""
    rsync_cmd.extend(
        [
            "--backup",
            f"--backup-dir={backup_dir}",
            "--delete",
            "./",
            f"{host_str}:{remote_path}",
        ]
    )
    subprocess.run(
        rsync_cmd,
        check=True,
        cwd=source_dir,
    )


def push_to_server(
    server_name: str,
    config: config_lib.ServerConfig,
    paths: list[str] | None = None,
    assume_backup_dir_exists: bool = False,
    control_path: str | None = None,
    source_dir: pathlib.Path | None = None,
) -> None:
    """Push local changes to a remote server.

    Args:
        server_name: Name of the server (for display)
        config: Server configuration
        paths: Optional list of paths to sync. If None, syncs everything.
        assume_backup_dir_exists: If True, skip creating backup directory
        control_path: Optional control path for SSH connection sharing
        source_dir: Optional source directory. If None, uses monorepo root.
    """
    if source_dir is None:
        source_dir = monorepo_util.find_monorepo_root()
        remote_path = config.remote_path
    else:
        # Find which repository this path belongs to
        repo_configs = config_lib.get_repo_configs()
        repo_name = None

        for name, repo_config in repo_configs.items():
            repo_path = pathlib.Path(repo_config.local_path).expanduser()
            try:
                source_dir.relative_to(repo_path)
                repo_name = name
                break
            except ValueError:
                continue

        if repo_name is None or (
            repo_name != "clarity" and (not config.repos or repo_name not in config.repos)
        ):
            # It's okay for some remote machines to not have a remote path configured for
            # particular repositories.
            return

        if repo_name == "clarity":
            remote_path = config.remote_path
        else:
            assert config.repos
            remote_path = config.repos[repo_name]

    host_str = f"{config.user}@{config.hostname}" if config.user else config.hostname
    print(f"Pushing to {server_name} ({host_str})...")

    # Build SSH command
    ssh_cmd = _build_ssh_cmd(config, control_path)

    # Push repository
    rsync_cmd = _build_base_rsync_cmd(config, control_path, paths, source_dir)
    backup_dir = f"{remote_path}/.rsync_backups/before_push"
    _ensure_remote_backup_dir(ssh_cmd, remote_path, assume_backup_dir_exists)
    _run_rsync(rsync_cmd, source_dir, host_str, remote_path, backup_dir)

    print(f"Push to {server_name} completed successfully.")


async def _push_with_error_handling(
    name: str,
    config: config_lib.ServerConfig,
    paths: list[str] | None,
    assume_backup_dir_exists: bool,
    control_path: str | None,
    source_dir: pathlib.Path | None = None,
) -> None:
    """Push to server with error handling."""
    try:
        # Run the blocking push_to_server function in a thread pool
        await anyio.to_thread.run_sync(
            push_to_server, name, config, paths, assume_backup_dir_exists, control_path, source_dir
        )
    except subprocess.CalledProcessError as e:
        error_msg = str(e)
        if e.stderr:
            error_msg += f"\nCommand stderr: {e.stderr.decode('utf-8', errors='replace')}"
        print(f"Warning: Push to {name} failed: {error_msg}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Push to {name} failed: {str(e)}", file=sys.stderr)


def _extract_server_names(server_name: str) -> list[str]:
    """Extract server names from a comma-separated list or "--all"."""
    if server_name == "--all":
        return list(config_lib.get_server_configs().keys())
    return server_name.split(",")


def push_all_or_one(
    server_name: str,
    paths: list[str] | None = None,
    assume_backup_dir_exists: bool = False,
    control_path: str | None = None,
    source_dir: pathlib.Path | None = None,
) -> None:
    """Push to all servers or a single server.

    Args:
        server_name: Server name or comma-separated list of server names or "--all"
        paths: Optional list of paths to sync. If None, syncs everything.
        assume_backup_dir_exists: If True, skip creating backup directory
        control_path: Optional control path for SSH connection sharing
        source_dir: Optional source directory. If None, uses monorepo root.
    """
    servers = config_lib.get_server_configs()
    server_names = _extract_server_names(server_name)

    for name in server_names:
        if name not in servers:
            print(f"Error: Server '{name}' not found in config", file=sys.stderr)
            raise typer.Exit(1)

    # Run pushes in parallel using anyio
    async def push_all_servers():
        async with anyio.create_task_group() as tg:
            for name in server_names:
                config = servers[name]
                tg.start_soon(
                    _push_with_error_handling,
                    name,
                    config,
                    paths,
                    assume_backup_dir_exists,
                    control_path,
                    source_dir,
                )

    # Run the async function
    anyio.run(push_all_servers)


def watch_and_sync(server_name: str, legacy: bool = False) -> None:
    """Watch for changes and sync them to server(s).

    Args:
        server_name: Server name or comma-separated list of server names or "--all"
        legacy: If True, use old behavior (sync all files on any change)
    """
    servers = config_lib.get_server_configs()
    server_names = _extract_server_names(server_name)

    # Check if all servers are in config
    for name in server_names:
        if name not in servers:
            print(f"Error: Server '{name}' not found in config", file=sys.stderr)
            raise typer.Exit(1)

    # Check if fswatch is installed
    try:
        subprocess.run(["fswatch", "--version"], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        if e.returncode == 127:  # Command not found
            print("Error: fswatch not installed. Please install fswatch.", file=sys.stderr)
            raise typer.Exit(1)
        raise

    # Get all paths to watch
    paths_to_watch = [monorepo_util.find_monorepo_root()]
    repo_configs = config_lib.get_repo_configs()
    for repo_config in repo_configs.values():
        local_path = pathlib.Path(repo_config.local_path).expanduser()
        if local_path.exists():
            paths_to_watch.append(local_path)

    if legacy:
        print("Running in legacy mode (separate full rsync calls)")
        print("Starting sync. Running initial push...")
        push_all_or_one(server_name)

        print("Watching for changes...")

        # Start fswatch process for all paths
        process = subprocess.Popen(
            ["fswatch", "-o"] + [str(path) for path in paths_to_watch],
            stdout=subprocess.PIPE,
            text=True,
        )

        try:
            # Read output line by line and push on changes
            while True:
                line = process.stdout.readline()  # pyright: ignore
                if not line:
                    break
                push_all_or_one(server_name)
        finally:
            process.terminate()
        return

    # Create temporary control directory
    with tempfile.TemporaryDirectory(dir="/tmp/") as temp_dir:
        control_path = str(pathlib.Path(temp_dir) / "%C")
        processes: list[subprocess.Popen[Any]] = []
        ssh_commands: list[tuple[list[str], str]] = []  # [(cmd, host_str), ...]
        fswatch_process = None
        try:
            print(f"Starting long-running SSH connections with control path: {control_path}")
            # Build list of configs to process
            configs_to_setup = [servers[name] for name in server_names]

            # Set up SSH connections for all configs
            for config in configs_to_setup:
                host_str = f"{config.user}@{config.hostname}" if config.user else config.hostname
                ssh_cmd = [
                    "ssh",
                    "-nN",
                    "-o",
                    "ControlMaster=yes",
                    "-o",
                    f"ControlPath={control_path}",
                    host_str,
                ]
                process = subprocess.Popen(ssh_cmd)
                print(f"- Started SSH connection process {process.pid} for {host_str}")
                processes.append(process)
                ssh_commands.append((ssh_cmd, host_str))

            print("Starting sync. Running initial push...")
            # Push monorepo first
            push_all_or_one(server_name, control_path=control_path)

            # Push all configured repositories
            repo_configs = config_lib.get_repo_configs()
            for repo_name, repo_config in repo_configs.items():
                local_path = pathlib.Path(repo_config.local_path).expanduser()
                if local_path.exists():
                    print(f"Pushing initial state of repository '{repo_name}'...")
                    push_all_or_one(server_name, control_path=control_path, source_dir=local_path)
                else:
                    print(
                        f"Warning: Local path '{local_path}' for repository '{repo_name}' does not exist, skipping...",
                        file=sys.stderr,
                    )

            print("Watching for changes...")

            # Create queue for file change batches
            file_queue: queue.Queue[tuple[str, pathlib.Path]] = queue.Queue()

            # Function to read from fswatch and batch changes
            def batch_file_changes(
                fswatch_process: subprocess.Popen[Any],
                file_queue: queue.Queue[tuple[str, pathlib.Path]],
            ) -> None:
                while True:
                    line = fswatch_process.stdout.readline()  # pyright: ignore
                    if not line:
                        break
                    # Find which repository the change came from
                    changed_path = pathlib.Path(line.strip())
                    source_repo = None
                    for path in paths_to_watch:
                        try:
                            changed_path.relative_to(path)
                            source_repo = path
                            break
                        except ValueError:
                            continue
                    if source_repo:
                        file_queue.put((line.strip(), source_repo))

            # Start fswatch process for all paths
            fswatch_process = subprocess.Popen(
                ["fswatch", "-r"] + [str(path) for path in paths_to_watch],
                stdout=subprocess.PIPE,
                text=True,
            )

            # Start daemon thread for batching file changes
            batch_thread = threading.Thread(
                target=batch_file_changes, args=(fswatch_process, file_queue), daemon=True
            )
            batch_thread.start()

            # Process batches from the queue in main thread
            while True:
                try:
                    # Get next batch with timeout
                    pending_changes: list[tuple[str, pathlib.Path]] = []
                    pending_changes.append(file_queue.get())
                    print("Detected changes. Collecting...", end=" ")
                    while True:
                        try:
                            pending_changes.append(file_queue.get(timeout=0.01))
                        except queue.Empty:
                            break
                    print(
                        f"Collected {len(pending_changes)} changes ({len(set(path for _, path in pending_changes))} unique repos)"
                    )

                    # Check for SSH connection status and restart any failed processes
                    for i, (process, (cmd, host_str)) in enumerate(zip(processes, ssh_commands)):
                        if process.poll() is not None:
                            # Start new SSH process with saved command
                            print(
                                f"SSH connection process {process.pid} for {host_str} has "
                                "terminated. Restarting...",
                                end=" ",
                            )
                            new_process = subprocess.Popen(cmd)
                            print(f"Restarted as process {new_process.pid}")
                            processes[i] = new_process

                    # Group changes by repository
                    changes_by_repo: dict[pathlib.Path, list[str]] = {}
                    for path_str, repo_path in pending_changes:
                        if repo_path not in changes_by_repo:
                            changes_by_repo[repo_path] = []
                        changes_by_repo[repo_path].append(path_str)

                    # Push changes for each repository
                    for repo_path, repo_changes in changes_by_repo.items():
                        if len(repo_changes) < 50:
                            push_all_or_one(
                                server_name,
                                paths=repo_changes,
                                assume_backup_dir_exists=True,
                                control_path=control_path,
                                source_dir=repo_path,
                            )
                        else:
                            # If too many changes, do a full sync
                            push_all_or_one(
                                server_name,
                                assume_backup_dir_exists=True,
                                control_path=control_path,
                                source_dir=repo_path,
                            )

                except KeyboardInterrupt:
                    print("\nStopping file watch...")
                    break

            # Main loop ended, thread will be terminated automatically since it's a daemon

        finally:
            # Clean up fswatch process if it exists
            if fswatch_process is not None and fswatch_process.poll() is None:
                fswatch_process.terminate()

            # Clean up all SSH processes
            for process in processes:
                if process.poll() is None:  # If process is still running
                    process.terminate()
            print("Closed long-running SSH connections.")
