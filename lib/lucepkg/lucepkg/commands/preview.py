import json
import pathlib
import sys
import textwrap
import typing
from typing import Annotated, Any, List, TypeVar

import datasets
import pandas as pd
import typer
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

app = typer.Typer(help="Preview file contents")

T = TypeVar("T")


def _add_wrapped_string_to_node(string: str, node: TreeNode[None]) -> None:
    """Add a string to a node, wrapping lines and showing line breaks."""
    # Split into lines and wrap each
    lines = string.split("\n")
    for i, line in enumerate(lines):
        if line:
            # Wrap non-empty line to 100 chars
            wrapped = textwrap.wrap(line, width=100)
            for j, subline in enumerate(wrapped):
                text = Text()
                text.append(subline)
                # Add highlighted \n for last subline in each line (except last line)
                if j == len(wrapped) - 1 and i < len(lines) - 1:
                    text.append("\\n", style="bold magenta")
                node.add_leaf(text)
        else:
            # For empty lines, just show the newline marker (except for last line)
            if i < len(lines) - 1:
                text = Text()
                text.append("\\n", style="bold magenta")
                node.add_leaf(text)


def _style_value(value: object) -> Text:
    """Create a styled Text for a JSON value."""
    text = Text()
    if isinstance(value, str):
        # String values in green with quotes
        text.append(repr(value), style="green")
    elif isinstance(value, bool):
        # Booleans in yellow
        text.append(str(value), style="yellow")
    elif isinstance(value, (int, float)):
        # Numbers in cyan
        text.append(str(value), style="cyan")
    elif value is None:
        # None in yellow like booleans
        text.append("None", style="yellow")
    else:
        # Other types (shouldn't happen) in default color
        text.append(repr(value))
    return text


def _add_json_to_tree(data: Any, node: TreeNode[Any]) -> None:
    """Recursively add JSON data to a tree node, expanding all nodes."""
    if isinstance(data, dict):
        data = typing.cast(dict[Any, Any], data)
        for key, value in data.items():
            text = Text()
            # Key in blue with quotes if string
            if isinstance(key, str):
                text.append(repr(key), style="blue")
            else:
                text.append(repr(key))

            if isinstance(value, (dict, list)):
                child = node.add(text, expand=True)
                _add_json_to_tree(value, child)
            elif isinstance(value, str):
                # For strings, show both repr and expandable view
                text.append(": ")
                text.append_text(_style_value(value))
                child = node.add(text, expand=False)
                _add_wrapped_string_to_node(value, child)
            else:
                text.append(": ")
                text.append_text(_style_value(value))
                node.add_leaf(text)
    elif isinstance(data, list):
        data = typing.cast(list[Any], data)
        for i, value in enumerate(data):
            text = Text()
            # Index in magenta with brackets
            text.append("[", style="magenta dim")
            text.append(str(i), style="magenta")
            text.append("]", style="magenta dim")

            if isinstance(value, (dict, list)):
                child = node.add(text, expand=True)
                _add_json_to_tree(value, child)
            elif isinstance(value, str):
                # For strings, show both repr and expandable view
                text.append(": ")
                text.append_text(_style_value(value))
                child = node.add(text, expand=False)
                _add_wrapped_string_to_node(value, child)
            else:
                text.append(": ")
                text.append_text(_style_value(value))
                node.add_leaf(text)


class LazyDatasetPreviewApp(App[None]):
    """Base class for previewing datasets with lazy loading."""

    def __init__(self, title: str, length: int) -> None:
        super().__init__()
        self.title = title
        self.length = length
        self._tree: Tree[int] | None = None

    def get_item(self, index: int) -> Any:
        """Get item at index. Must be implemented by subclasses."""
        raise NotImplementedError("No items")

    def compose(self) -> ComposeResult:
        self._tree = Tree(f"• {self.title}")
        self._tree.root.expand()
        # Add placeholder nodes for each item
        for i in range(self.length):
            # Parse first item eagerly and expand it
            if i == 0:
                node = self._tree.root.add(f"[{i}]", expand=True)
                _add_json_to_tree(self.get_item(i), node)
            else:
                # Add placeholder with the index stored
                self._tree.root.add(f"[{i}]", data=i, expand=False)
        yield self._tree

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[int]) -> None:
        """Load data when a node is expanded."""
        node = event.node
        # Skip if this isn't a root-level node or if it's already populated
        assert self._tree is not None
        if node.parent is not self._tree.root or node.children:
            return
        # Load and parse the data
        try:
            assert node.data is not None
            data = self.get_item(node.data)
            # Clear the stored index to save memory
            node.data = None
            # Add the parsed data
            _add_json_to_tree(data, node)
        except Exception as e:
            # If loading fails, show the error
            node.add_leaf(f"Error: {e}")


class JsonlPreviewApp(LazyDatasetPreviewApp):
    """App to preview JSONL data in a tree view with lazy loading."""

    def __init__(self, lines: List[str], title: str) -> None:
        self.lines = lines
        super().__init__(title, len(lines))

    def get_item(self, index: int) -> object:
        return json.loads(self.lines[index])


class HfDatasetPreviewApp(LazyDatasetPreviewApp):
    """App to preview HuggingFace datasets in a tree view with lazy loading."""

    def __init__(self, dataset: datasets.Dataset, title: str) -> None:
        self.dataset = dataset
        super().__init__(title, len(dataset))

    def get_item(self, index: int) -> Any:
        return typing.cast(Any, self.dataset[index])


class DataFramePreviewApp(LazyDatasetPreviewApp):
    """App to preview pandas DataFrame data in a tree view with lazy loading."""

    def __init__(self, df: pd.DataFrame, title: str) -> None:
        self.df = df
        super().__init__(title, len(df))

    def get_item(self, index: int) -> dict[str, Any]:
        # Convert row to dict, handling numpy/pandas types
        row = self.df.iloc[index].to_dict()
        # Convert numpy/pandas types to Python native types
        return {k: v.item() if hasattr(v, "item") else v for k, v in row.items()}


@app.command(name="jsonl")
def _jsonl(  # pyright: ignore[reportUnusedFunction]
    file: Annotated[
        str,
        typer.Argument(help="JSONL file to preview, or '-' for stdin"),
    ],
):
    """Preview a JSONL file in a tree view."""
    try:
        if file == "-":
            lines = sys.stdin.readlines()
            title = "stdin"
        else:
            path = pathlib.Path(file).absolute()
            lines = path.read_text().splitlines()
            title = str(path)

        if not lines:
            print("Error: Empty JSONL file")
            raise typer.Exit(1)

    except FileNotFoundError:
        print(f"Error: File not found: {file}")
        raise typer.Exit(1)

    app = JsonlPreviewApp(lines, title)
    app.run()


@app.command(name="hfds")
def _hfds(  # pyright: ignore[reportUnusedFunction]
    path: Annotated[
        str,
        typer.Argument(help="Path to HuggingFace dataset directory"),
    ],
):
    """Preview a HuggingFace dataset in a tree view."""
    try:
        dataset = datasets.Dataset.load_from_disk(path)  # pyright: ignore[reportUnknownMemberType]
        title = pathlib.Path(path).absolute().name
    except Exception as e:
        print(f"Error loading dataset: {e}")
        raise typer.Exit(1)

    app = HfDatasetPreviewApp(dataset, title)
    app.run()


class JsonPreviewApp(App[None]):
    """App to preview JSON data in a tree view."""

    def __init__(self, data: Any, title: str) -> None:
        super().__init__()
        self.data = data
        self.title = title

    def compose(self) -> ComposeResult:
        tree = Tree[None](f"• {self.title}")
        tree.root.expand()
        _add_json_to_tree(self.data, tree.root)
        yield tree


@app.command(name="json")
def _json(  # pyright: ignore[reportUnusedFunction]
    file: Annotated[
        str,
        typer.Argument(help="JSON file to preview, or '-' for stdin"),
    ],
):
    """Preview a JSON file in a tree view."""
    try:
        if file == "-":
            data = json.loads(sys.stdin.read())
            title = "stdin"
        else:
            path = pathlib.Path(file).absolute()
            data = json.loads(path.read_text())
            title = str(path)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
        raise typer.Exit(1)
    except FileNotFoundError:
        print(f"Error: File not found: {file}")
        raise typer.Exit(1)
    app = JsonPreviewApp(data, title)
    app.run()


@app.command(name="parquet")
def _parquet(  # pyright: ignore[reportUnusedFunction]
    file: Annotated[
        str,
        typer.Argument(help="Parquet file to preview"),
    ],
):
    """Preview a Parquet file in a tree view."""
    try:
        path = pathlib.Path(file).absolute()
        df = pd.read_parquet(path)
        title = str(path)
    except FileNotFoundError:
        print(f"Error: File not found: {file}")
        raise typer.Exit(1)
    except Exception as e:
        print(f"Error loading Parquet file: {e}")
        raise typer.Exit(1)

    app = DataFramePreviewApp(df, title)
    app.run()
