"""Docent MCP server for IDE plugins."""

import argparse
import sys
import webbrowser
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]

from docent.sdk.client import Docent

_client: Docent | None = None
_config_file: str | Path | None = None


def get_client() -> Docent:
    global _client
    if _client is None:
        _client = Docent(config_file=_config_file, log_stream=sys.stderr)
    return _client


mcp = FastMCP("docent", json_response=True)


@mcp.tool()
def get_metadata_fields(collection_id: str) -> str:
    "Get the available metadata fields for agent runs in a collection. Use this to discover what metadata keys are available for filtering and analysis."
    client = get_client()
    try:
        fields = client.get_metadata_fields(
            collection_id, include_sample_values=True, sample_limit=10
        )

        if not fields:
            return f"No metadata fields found for collection {collection_id}"

        def _render_value(value: str) -> str:
            value = value.replace("\n", "\\n")
            if len(value) > 80:
                return value[:77] + "..."
            return value

        lines: list[str] = []
        for field in fields:
            name = str(field.get("name", "(unknown)"))
            field_type = str(field.get("type", "str"))
            line = f"- {name} ({field_type})"

            sample_values = cast(list[dict[str, Any]], field.get("sample_values") or [])
            total_unique_values = cast(int | None, field.get("total_unique_values"))
            if sample_values:
                rendered_samples = ", ".join(
                    f"{_render_value(str(s.get('value', '')))} ({int(s.get('count', 0))} runs)"
                    for s in sample_values
                    if s.get("value") is not None
                )
                other_suffix = ""
                if total_unique_values is not None:
                    other_count = total_unique_values - len(sample_values)
                    if other_count > 0:
                        other_suffix = f" (+{other_count} other values)"
                line = f"{line}: {rendered_samples}{other_suffix}"

            lines.append(line)

        field_list = "\n".join(lines)
        return f"Metadata fields for collection {collection_id}:\n{field_list}"
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            return f"Collection not found: {collection_id}"
        return f"Error fetching metadata fields: {e}"


@mcp.tool()
def list_result_sets(collection_id: str, prefix: str | None = None) -> str:
    "List result sets in a collection. Use this to discover what result sets exist in a collection, optionally filtered by name prefix."
    client = get_client()
    if not collection_id:
        return "Error: collection_id is required (pass explicitly or set DOCENT_COLLECTION_ID)"

    try:
        result_sets = client.list_result_sets(collection_id, prefix=prefix)

        if not result_sets:
            prefix_msg = f" with prefix '{prefix}'" if prefix else ""
            return f"No result sets found for collection {collection_id}{prefix_msg}"

        result_lines: list[str] = []
        for rs in result_sets:
            name = rs.get("name") or "(unnamed)"
            result_count = rs.get("result_count", 0)
            created_at = rs.get("created_at", "")
            result_set_id = rs.get("id", "")
            result_lines.append(
                f"- {name} (ID: {result_set_id}, Results: {result_count}, Created: {created_at})"
            )

        prefix_msg = f" (filtered by prefix '{prefix}')" if prefix else ""
        return f"Result sets in collection {collection_id}{prefix_msg}:\n" + "\n".join(result_lines)
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            return f"Collection not found: {collection_id}"
        return f"Error fetching result sets: {e}"


@mcp.tool()
def navigate_to(collection_id: str, path: str) -> str:
    "Open a page in the Docent dashboard in the browser. For a result set, path is `/results/<result_set_name>`"
    client = get_client()
    if not collection_id:
        return "Error: collection_id is required (pass explicitly or set DOCENT_COLLECTION_ID)"

    path = path.lstrip("/")
    url = f"{client._web_url}/dashboard/{collection_id}/{path}"  # type: ignore[reportPrivateUsage]

    webbrowser.open(url)
    return f"Opened {url} in browser"


def main():
    global _config_file

    parser = argparse.ArgumentParser(description="Docent MCP Server")
    parser.add_argument(
        "--config-file",
        type=str,
        help="Path to a dotenv config file with DOCENT_API_KEY, DOCENT_API_URL, etc.",
    )
    args = parser.parse_args()

    if args.config_file:
        _config_file = args.config_file

    mcp.run(transport="stdio")
