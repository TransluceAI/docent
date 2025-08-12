"""
Data importers for different file formats.

Each importer takes a file and returns a list of AgentRun objects and metadata.
"""

from typing import Tuple

from rich.console import Console

from .agentic_misalignment import load_agent_runs as process_agentic_misalignment_file
from .cursor import process_cursor_file
from .inspect_log import process_inspect_file
from .malt import process_malt_file_json
from .oh_swe_bench import process_oh_swe_bench_file
from .tau_bench import process_tau_bench_file

console = Console()

# Registry of available importers
IMPORTERS = {
    "inspect": process_inspect_file,
    "oh_swe_bench": process_oh_swe_bench_file,
    "tau_bench": process_tau_bench_file,
    "agentic_misalignment": process_agentic_misalignment_file,
    "cursor": process_cursor_file,
    "malt": process_malt_file_json,
}


def get_importer(importer_name: str):
    """Get an importer function by name."""
    if importer_name not in IMPORTERS:
        available = ", ".join(IMPORTERS.keys())
        raise ValueError(f"Unknown importer '{importer_name}'. Available: {available}")

    return IMPORTERS[importer_name]


def parse_filename(filename: str) -> Tuple[str, str, str]:
    """
    Parse a filename to extract collection name, importer, and extension.

    Format: [collection_name].[importer_name].[extension]
    """
    parts = filename.split(".")
    if len(parts) < 2:
        raise ValueError(
            f"Invalid filename format '{filename}'. "
            "Expected: [collection_name].[importer_name].[extension]"
        )
    extension = parts[-1]
    importer_name = parts[-2]
    if len(parts) == 2:
        collection_name = importer_name
    else:
        collection_name = ".".join(parts[:-2])  # Handle collection names with dots

    return collection_name, importer_name, extension
