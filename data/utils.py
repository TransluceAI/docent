"""
Shared utilities for the data registry.

Provides common functionality for file display, environment handling, and error management.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Tuple

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from docent_core._env_util import ENV

console = Console()

# Display formatting constants
MAX_FILENAME_DISPLAY_LENGTH = 45
MAX_COLLECTION_NAME_DISPLAY_LENGTH = 35
TRUNCATION_SUFFIX = "..."
TRUNCATED_FILENAME_LENGTH = MAX_FILENAME_DISPLAY_LENGTH - len(TRUNCATION_SUFFIX)
TRUNCATED_COLLECTION_NAME_LENGTH = MAX_COLLECTION_NAME_DISPLAY_LENGTH - len(TRUNCATION_SUFFIX)


def get_server_host() -> str:
    """Get the Docent server host from environment."""
    server_host = ENV.get("DOCENT_API_URL", "http://localhost:8889/")
    if server_host.endswith("/"):
        server_host = server_host[:-1]
    return server_host


def create_aligned_file_display(
    filtered_files: List[Dict[str, Any]], current_revision: str | None = None
) -> Tuple[List[str], List[str]]:
    """Create aligned file display with proper column padding."""
    if not filtered_files:
        return [], []

    # Calculate column widths for alignment
    max_filename_len = max(len(f["file"].key) for f in filtered_files)
    max_filename_len = min(max_filename_len, MAX_FILENAME_DISPLAY_LENGTH)
    max_size_len = max(len(f["file"].size_human) for f in filtered_files)

    display_options: List[str] = []
    file_keys: List[str] = []

    for file_info in filtered_files:
        s3_file = file_info["file"]
        source_icons = file_info["source_icons"]

        # Truncate and pad filename
        filename = s3_file.key
        if len(filename) > MAX_FILENAME_DISPLAY_LENGTH:
            filename = filename[:TRUNCATED_FILENAME_LENGTH] + TRUNCATION_SUFFIX
        filename_padded = filename.ljust(max_filename_len)

        # Pad file size
        size_padded = s3_file.size_human.rjust(max_size_len)

        # Create aligned display string
        display_name = f"{filename_padded} | {size_padded} | {source_icons}"
        display_options.append(display_name)
        file_keys.append(s3_file.key)

    return display_options, file_keys


def create_aligned_collection_display(collection_details: List[Dict[str, Any]]) -> List[str]:
    """Create aligned collection display with proper column padding."""
    if not collection_details:
        return []

    # Calculate column widths for alignment
    max_name_len = max(len(details["name"]) for details in collection_details)
    max_name_len = min(max_name_len, MAX_COLLECTION_NAME_DISPLAY_LENGTH)
    max_runs_len = max(len(str(details["agent_runs_count"])) for details in collection_details)

    display_options: List[str] = []
    for details in collection_details:
        # Format the created_at date if it's available
        created_str = details["created_at"]
        if isinstance(created_str, str) and "T" in created_str:
            # Parse ISO format and show just the date
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                created_str = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        # Truncate name if too long and pad
        name = details["name"]
        if len(name) > MAX_COLLECTION_NAME_DISPLAY_LENGTH:
            name = name[:TRUNCATED_COLLECTION_NAME_LENGTH] + TRUNCATION_SUFFIX
        name_padded = name.ljust(max_name_len)

        # Format other columns
        id_short = details["id"][:8] + "..."
        runs_padded = str(details["agent_runs_count"]).rjust(max_runs_len)

        # Create aligned display string
        display_name = f"{name_padded} | {id_short} | {created_str} | {runs_padded} runs"
        display_options.append(display_name)

    return display_options


def make_safe_filename(name: str) -> str:
    """Convert a name to safe filename format."""
    # Replace spaces and special characters with underscores
    safe_name = "".join(c if c.isalnum() else "_" for c in name)
    # Remove multiple consecutive underscores
    while "__" in safe_name:
        safe_name = safe_name.replace("__", "_")
    # Remove leading/trailing underscores
    return safe_name.strip("_").lower()


def log_error(message: str, exception: Exception | None = None) -> None:
    """Log an error message with consistent formatting."""
    if exception:
        console.print(f"[red]{message}: {exception}[/red]")
    else:
        console.print(f"[red]{message}[/red]")


def log_success(message: str) -> None:
    """Log a success message with consistent formatting."""
    console.print(f"[green]{message}[/green]")


def log_warning(message: str) -> None:
    """Log a warning message with consistent formatting."""
    console.print(f"[yellow]{message}[/yellow]")


def log_info(message: str) -> None:
    """Log an info message with consistent formatting."""
    console.print(f"[blue]{message}[/blue]")


def count_csv_rows(csv_path: str | Path) -> int:
    """Count rows in a CSV file, excluding header."""
    import csv
    import sys

    csv.field_size_limit(sys.maxsize)

    path = Path(csv_path)
    if not path.exists() or path.stat().st_size == 0:
        return 0

    with open(path, "r") as f:
        reader = csv.DictReader(f)
        return sum(1 for _ in reader)


@contextmanager
def simple_progress(description: str):
    """Context manager for simple spinner progress bar."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description, total=None)
        yield progress, task
        progress.update(task, completed=True)
