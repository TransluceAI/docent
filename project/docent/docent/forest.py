from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any, Callable, Sequence, TypedDict, cast

import matplotlib.pyplot as plt
import networkx as nx
from llm_util.types import ChatMessage
from log_util import get_logger
from pydantic import BaseModel, Field

logger = get_logger(__name__)


class ExportNode(TypedDict):
    id: str
    data: dict[str, Any]


class ExportEdge(TypedDict):
    source: str
    target: str
    data: dict[str, Any]


class ExportGraph:
    """We use export{Graph/Node/Edge} as the canonical representations of a graph. nx.Digraph is too jank."""

    def __init__(self):
        self.nodes: list[ExportNode] = []
        self.edges: list[ExportEdge] = []
        self.adj: dict[str, set[str]] = {}

    def add_node(self, node: ExportNode) -> None:
        self.nodes.append(node)

    def add_edge(self, edge: ExportEdge) -> None:
        self.edges.append(edge)
        self.adj.setdefault(edge["source"], set()).add(edge["target"])

    def has_edge(self, source: str, target: str) -> bool:
        return source in self.adj and target in self.adj[source]

    def export(self) -> tuple[list[ExportNode], list[ExportEdge]]:
        return self.nodes, self.edges

    def export_as_nx(self) -> nx.DiGraph:
        G = nx.DiGraph()
        for node in self.nodes:
            G.add_node(node["id"], **node["data"])  # type: ignore
        for edge in self.edges:
            G.add_edge(edge["source"], edge["target"], **edge["data"])  # type: ignore
        return G


class NodeColorConfig(BaseModel):
    """Configuration for coloring nodes based on metadata conditions."""

    condition: Callable[[dict[str, Any]], bool]
    color: str
    label: str

    class Config:
        arbitrary_types_allowed = True


class NodeData(BaseModel, ABC):
    """Abstract base class for data stored in nodes."""

    node_type: str

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        pass

    @abstractmethod
    def key(self) -> str:
        """Get a unique key for this node data."""

    @abstractmethod
    def get_label(self) -> str:
        """Get a human-readable label for visualization."""

    def get_type(self) -> str:
        """Get the type of the node data for visualization."""
        return self.node_type


class MessageData(NodeData):
    """Represents a message in the conversation chain."""

    message: ChatMessage
    node_type: str = "message"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MessageData):
            return False
        return self.key() == other.key()

    def key(self) -> str:
        """Get a unique key for this message data."""
        content_str = json.dumps(self.message.model_dump(exclude={"source"}), sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()

    def get_label(self) -> str:
        content_str = str(self.message)
        if len(content_str) > 30:
            content_str = content_str[:30] + "..."
        return content_str


class EnvConfigData(NodeData):
    """Represents an environment configuration."""

    config: dict[str, Any]
    node_type: str = "env_config"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EnvConfigData):
            return False
        return self.key() == other.key()

    def key(self) -> str:
        """Get a unique key for this environment configuration."""
        config_str = json.dumps(self.config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()

    def __repr__(self) -> str:
        config_str = str(self.config)
        if len(config_str) > 50:
            config_str = config_str[:50] + "..."
        return f"EnvConfig({config_str})"

    def get_label(self) -> str:
        config_str = str(self.config)
        if len(config_str) > 30:
            config_str = config_str[:30] + "..."
        return config_str


class Node(BaseModel):
    """Represents a node in the forest."""

    data: MessageData | EnvConfigData
    id: str = Field(default_factory=lambda: f"node_{uuid.uuid4()}")
    children: dict[str, Node] = Field(default_factory=dict)  # Maps transcript_id -> child node
    parent_id: str | None = None

    class Config:
        arbitrary_types_allowed = True

    def add_child(self, transcript_id: str, child_node: Node) -> Node:
        """
        Add a child node to this node for a specific transcript.

        Args:
            transcript_id: The ID of the transcript this child belongs to
            child_node: The child node to add

        Returns:
            The added child node
        """
        self.children[transcript_id] = child_node
        child_node.parent_id = self.id
        return child_node

    def key(self) -> str:
        """Get a unique key for this node based on its data."""
        return self.data.key()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return False
        return self.key() == other.key()

    def __repr__(self) -> str:
        return f"Node({self.data})"


class TranscriptForest(BaseModel):
    """A forest data structure to store representations of interventional transcripts."""

    key_to_root_id: dict[str, str] = Field(default_factory=dict)  # Config key -> root node ID
    node_dict: dict[str, Node] = Field(default_factory=dict)  # Node ID -> node
    transcript_metadata: dict[str, dict[str, Any]] = Field(
        default_factory=dict
    )  # Transcript ID -> metadata
    transcript_derivation: dict[str, str] = Field(
        default_factory=dict
    )  # Transcript ID -> parent transcript ID
    # Map from transcript ID to root node ID
    transcript_roots: dict[str, str] = Field(default_factory=dict)  # Transcript ID -> root node ID

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def from_json(cls, fpath: str) -> "TranscriptForest":
        start = perf_counter()
        with open(fpath, "r") as f:
            obj = cls.model_validate_json(f.read())
        logger.info(f"Loaded forest from {fpath} in {perf_counter() - start:.2f} seconds")
        return obj

    def to_json(self, fpath: str) -> None:
        start = perf_counter()
        with open(fpath, "w") as f:
            f.write(self.model_dump_json())
        logger.info(f"Dumped forest to {fpath} in {perf_counter() - start:.2f} seconds")

    def add_transcript(
        self,
        transcript_id: str,
        env_config: dict[str, Any],
        messages: Sequence[ChatMessage],
        metadata: dict[str, Any] | None = None,
        compute_derivations: bool = True,
    ) -> None:
        """
        Add an transcript to the forest.

        Args:
            transcript_id: Unique identifier for the transcript.
            env_config: Configuration parameters for the environment.
            messages: list of messages that represent interactions with the environment.
            metadata: Additional metadata for the transcript (creation time, etc.).

        Raises:
            ValueError: If the transcript_id already exists in the forest.
        """
        # Check if the transcript_id already exists
        if transcript_id in self.transcript_roots:
            raise ValueError(
                f"Transcript ID '{transcript_id}' already exists in the forest. Use a unique ID."
            )

        # Create environment config object
        env_config_obj = EnvConfigData(config=env_config)
        env_config_key = env_config_obj.key()

        # Check if we already have a root node for this environment configuration
        if env_config_key not in self.key_to_root_id:
            # Create a new root node for this environment configuration
            root_node = Node(data=env_config_obj)
            self.key_to_root_id[env_config_key] = root_node.id
            self.node_dict[root_node.id] = root_node
        else:
            root_node_id = self.key_to_root_id[env_config_key]
            root_node = self.node_dict[root_node_id]

        # Store the root node for this transcript
        self.transcript_roots[transcript_id] = root_node.id

        # Store metadata if provided
        if metadata:
            self.transcript_metadata[transcript_id] = metadata
        else:
            self.transcript_metadata[transcript_id] = {}

        # Start traversal from the root node
        current_node = root_node

        # Traverse the tree, adding new nodes as needed
        for message_dict in messages:
            message = MessageData(message=message_dict)
            message_key = message.key()

            # First check if this transcript already has a child at this node
            assert (
                transcript_id not in current_node.children
            ), f"Transcript ID {transcript_id} should not already be in the tree"

            # Check if any other transcript has a matching child
            child_found = False
            for _, child in current_node.children.items():
                if child.key() == message_key:
                    # Found a matching child in another transcript, reuse it for this transcript
                    current_node.children[transcript_id] = child
                    current_node = child
                    child_found = True
                    break

            # No matching child found, create a new one
            if not child_found:
                new_node = Node(data=message)
                current_node.add_child(transcript_id, new_node)
                current_node = new_node
                self.node_dict[new_node.id] = new_node

        # Try to infer the most likely parent transcript based on path similarity
        if compute_derivations and len(self.transcript_roots) > 1:
            # TODO(kevin): make this way more efficient!
            self.recompute_all_derivations()

    def recompute_all_derivations(self) -> None:
        """
        Recompute derivation relationships for all transcripts in the forest.

        This ensures that all transcript derivations are based on the most current
        algorithm and data. Useful when the derivation inference algorithm has been
        improved or when transcript data has been modified.
        """
        # Clear all existing derivation relationships
        self.transcript_derivation = {}

        # Group transcripts by their root node (environment config)
        root_to_transcripts: dict[str, list[str]] = {}
        for transcript_id, root_id in self.transcript_roots.items():
            if root_id not in root_to_transcripts:
                root_to_transcripts[root_id] = []
            root_to_transcripts[root_id].append(transcript_id)

        # For each group of transcripts sharing the same root, recompute derivations
        for root_id, transcript_ids in root_to_transcripts.items():
            if len(transcript_ids) > 1:
                for transcript_id in transcript_ids:
                    self._infer_transcript_derivation(transcript_id, root_id)

    def _infer_transcript_derivation(self, transcript_id: str, root_node_id: str) -> None:
        """
        Infer the most likely parent transcript based on path similarity.
        Only considers messages before the intervention_index in the current transcript.
        TODO(kevin): can be made more efficient

        Args:
            transcript_id: The transcript ID to find a parent for
            root_node_id: The ID of the root node for this transcript
        """
        # Get all transcripts that share the same root
        related_transcripts = [
            exp_id
            for exp_id, root_id in self.transcript_roots.items()
            if root_id == root_node_id and exp_id != transcript_id
        ]

        if not related_transcripts:
            return

        # Get the path for the current transcript
        current_path = self.get_transcript_traversal(transcript_id)

        # If an intervention index is available, truncate to only include messages before it
        intervention_index = None
        if (
            transcript_id in self.transcript_metadata
            and "intervention_index" in self.transcript_metadata[transcript_id]
        ):
            intervention_index = self.transcript_metadata[transcript_id]["intervention_index"]
        if intervention_index is not None:
            current_path = current_path[:intervention_index]  # Get messages *before* intervention

        # Iterate through all other transcripts to check for common prefixes
        best_match: str | None = None
        max_common_length = 0
        for other_id in related_transcripts:
            other_path = self.get_transcript_traversal(other_id)

            # Find common prefix length
            common_length = 0
            for i in range(min(len(current_path), len(other_path))):
                if current_path[i] == other_path[i]:
                    common_length = i + 1
                else:
                    break

            # Any transcript with at least one message in common (2 nodes including env config)
            # is a candidate parent
            if common_length >= 2:
                # Found a longer common prefix
                if common_length > max_common_length:
                    max_common_length = common_length
                    best_match = other_id
                # Found an equally-long common prefix, use timestamp as tiebreaker
                elif common_length == max_common_length and best_match is not None:
                    other_timestamp = self.transcript_metadata.get(other_id, {}).get(
                        "intervention_timestamp"
                    )
                    best_match_timestamp = self.transcript_metadata.get(best_match, {}).get(
                        "intervention_timestamp"
                    )

                    # Choose the one with the earlier timestamp (if available)
                    if other_timestamp and best_match_timestamp:
                        if other_timestamp < best_match_timestamp:
                            best_match = other_id

        # If we found a good match, record it
        if best_match is not None:
            self.transcript_derivation[transcript_id] = best_match

    def get_transcript_traversal(self, transcript_id: str) -> list[NodeData]:
        """
        Get the traversal of a particular transcript.

        Args:
            transcript_id: The ID of the transcript to retrieve.

        Returns:
            list of node data representing the path of the transcript.
        """
        if transcript_id not in self.transcript_roots:
            raise ValueError(f"Transcript ID {transcript_id} not found")

        # Start from the root node
        root_node_id = self.transcript_roots[transcript_id]
        current_node = self.node_dict[root_node_id]

        # Build the path
        path: list[NodeData] = [current_node.data]

        # Traverse the tree following the transcript_id
        while transcript_id in current_node.children:
            current_node = current_node.children[transcript_id]
            path.append(current_node.data)

        return path

    def to_export_graph(self) -> ExportGraph:
        """
        Convert the forest to a list of nodes and edges.
        """
        G = ExportGraph()

        for node_id, node in self.node_dict.items():
            G.add_node({"id": node_id, "data": node.data.model_dump()})

        for node_id, node in self.node_dict.items():
            for child_id in node.children.keys():
                G.add_edge({"source": node_id, "target": child_id, "data": {}})

        return G

    def plot(
        self,
        figsize: tuple[float, float] = (18, 12),
        node_size: int = 1000,
        font_size: int = 8,
    ):
        """
        Plot the forest using NetworkX and matplotlib.

        Args:
            figsize: Size of the figure (width, height) in inches.
            node_size: Size of the nodes in the plot.
            font_size: Size of the font for node labels.
            highlight_transcript_id: If provided, highlights the specific transcript path.

        Returns:
            Tuple of (NetworkX graph, node positions) for further customization.
        """
        G = self.to_export_graph().export_as_nx()

        plt.figure(figsize=figsize)  # type: ignore

        # Use a hierarchical layout for better visualization
        try:
            pos = nx.nx_agraph.graphviz_layout(G, prog="dot", args="-Grankdir=TB")  # type: ignore
        except ImportError:
            print("pygraphviz not available, using spring_layout instead.")
            pos = cast(dict[str, tuple[float, float]], nx.spring_layout(G, seed=42))  # type: ignore

        # Separate nodes by type
        env_config_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "env_config"]  # type: ignore
        message_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "message"]  # type: ignore

        # Draw nodes with different colors based on type
        nx.draw_networkx_nodes(  # type: ignore
            G,
            pos,
            nodelist=env_config_nodes,
            node_color="lightgreen",
            node_size=node_size,
            alpha=0.8,
        )
        nx.draw_networkx_nodes(  # type: ignore
            G,
            pos,
            nodelist=message_nodes,
            node_color="lightblue",
            node_size=node_size,
            alpha=0.8,
        )

        # Draw edges
        nx.draw_networkx_edges(G, pos, arrows=True)  # type: ignore

        plt.title("Transcript Forest")  # type: ignore

        # Add labels (common to both visualization modes)
        labels = {n: d.get("label", "message")[:30] for n, d in G.nodes(data=True)}  # type: ignore
        nx.draw_networkx_labels(G, pos, labels, font_size=font_size)  # type: ignore

        plt.axis("off")  # type: ignore
        plt.tight_layout()  # type: ignore
        plt.show()  # type: ignore

    def _infer_root_transcripts(self):
        return [
            k
            for k in self.transcript_roots.keys()
            if self.transcript_metadata[k]["intervention_timestamp"] is None
        ]

    def build_transcript_derivation_tree(
        self, root_transcript_ids: list[str] | None = None
    ) -> ExportGraph:
        """
        Build a tree representation of transcript derivations from a root transcript.

        Args:
            root_transcript_id: ID of the root transcript. If None, roots are inferred from not having intervention_timestamp.

        Returns:
            NetworkX DiGraph representing the transcript derivation tree.
        """
        if root_transcript_ids is None:
            root_transcript_ids = self._infer_root_transcripts()

        # Check that all root transcript IDs are present
        root_transcript_ids_set = set(root_transcript_ids)
        for r_id in root_transcript_ids_set:
            if r_id not in self.transcript_roots:
                raise ValueError(f"Root transcript ID {r_id} not found")

        # Get the environment config root for this transcript
        root_ids_set = set([self.transcript_roots[r_id] for r_id in root_transcript_ids_set])

        # Create a directed graph
        G = ExportGraph()

        # Find all transcripts that share the same environment config
        related_transcripts: list[str] = []
        for t_id, root_id in self.transcript_roots.items():
            if root_id in root_ids_set:
                related_transcripts.append(t_id)

        # Add transcript nodes
        for t_id in related_transcripts:
            # Count the number of messages in the transcript
            path_data = self.get_transcript_traversal(t_id)
            num_messages = len(path_data) - 1  # Subtract 1 for env config

            # Add metadata to each transcript node
            node_attrs = {
                "id": t_id,
                "num_messages": num_messages,
            }

            # Add any stored metadata
            if t_id in self.transcript_metadata:
                node_attrs.update(self.transcript_metadata[t_id])

            G.add_node({"id": t_id, "data": node_attrs})

        # Add derivation edges
        for t_id in related_transcripts:
            if (
                t_id in self.transcript_derivation
                and self.transcript_derivation[t_id] in related_transcripts
            ):
                parent_id = self.transcript_derivation[t_id]

                # Skip so we don't point an edge at the specified root
                if t_id in root_transcript_ids_set:
                    continue

                G.add_edge({"source": parent_id, "target": t_id, "data": {}})

        return G

    def plot_transcript_derivation_tree(
        self,
        root_transcript_ids: list[str] | None = None,
        figsize: tuple[float, float] = (18, 12),
        node_size: int = 2000,
        font_size: int = 10,
        color_configs: list[NodeColorConfig] | None = None,
    ):
        """
        Visualize the transcript derivation tree from a root transcript.

        Args:
            root_transcript_id: ID of the root transcript.
            figsize: Size of the figure (width, height) in inches.
            node_size: Size of the nodes in the plot.
            font_size: Size of the font for node labels.
            color_configs: List of NodeColorConfig objects that define coloring rules based on metadata.

        Returns:
            Tuple of (NetworkX graph, node positions) for further customization.
        """
        if root_transcript_ids is None:
            root_transcript_ids = self._infer_root_transcripts()

        G = self.build_transcript_derivation_tree(root_transcript_ids).export_as_nx()

        plt.figure(figsize=figsize)  # type: ignore

        # Use a hierarchical layout
        try:
            pos = nx.nx_agraph.graphviz_layout(G, prog="dot", args="-Grankdir=TB")  # type: ignore
        except ImportError:
            print("pygraphviz not available, using spring_layout instead.")
            pos = nx.spring_layout(G, seed=42)  # type: ignore

        # Draw nodes and edges
        nx.draw_networkx_nodes(G, pos, node_color="lightblue", node_size=node_size, alpha=0.8)  # type: ignore
        nx.draw_networkx_edges(G, pos, arrows=True, arrowsize=20, width=2)  # type: ignore

        # Highlight root transcript
        nx.draw_networkx_nodes(  # type: ignore
            G, pos, nodelist=root_transcript_ids, node_color="gold", node_size=node_size, alpha=0.8
        )

        # Apply metadata-based coloring if provided
        if color_configs:
            for config in color_configs:
                # Find transcripts that match the condition
                matching_transcripts: list[str] = []

                # Iterate through all transcripts in the metadata
                for transcript_id, metadata in self.transcript_metadata.items():
                    # Only consider transcripts that are in the graph
                    if transcript_id in G:  # type: ignore
                        if config.condition(metadata):
                            matching_transcripts.append(transcript_id)

                # Draw these nodes with the specified color
                if matching_transcripts:
                    nx.draw_networkx_nodes(  # type: ignore
                        G,
                        pos,
                        nodelist=matching_transcripts,
                        node_color=config.color,
                        node_size=node_size,
                        alpha=0.8,
                        label=config.label,
                    )

        # Create custom labels using forest_label from metadata if available
        custom_labels = {}
        for exp_id in G.nodes():  # type: ignore
            # Check if this transcript has metadata with a forest_label
            if (
                exp_id in self.transcript_metadata
                and "forest_label" in self.transcript_metadata[exp_id]
                and self.transcript_metadata[exp_id]["forest_label"] is not None
            ):
                # Use the forest_label from metadata
                custom_labels[exp_id] = self.transcript_metadata[exp_id]["forest_label"]
            else:
                # Fall back to using the transcript ID
                custom_labels[exp_id] = exp_id

        # Add transcript labels
        nx.draw_networkx_labels(G, pos, labels=custom_labels, font_size=font_size)  # type: ignore

        # Add additional labels showing message counts
        message_counts = {}
        for exp_id in G.nodes():  # type: ignore
            message_count = G.nodes[exp_id].get("num_messages", 0)  # type: ignore
            message_counts[exp_id] = f"{message_count} msgs"

        # Position the second label slightly below the node
        pos_attrs = {}
        for k, v in pos.items():  # type: ignore
            pos_attrs[k] = (v[0], v[1] - 0.1)

        nx.draw_networkx_labels(  # type: ignore
            G, pos_attrs, labels=message_counts, font_size=font_size - 2, font_color="darkblue"
        )

        plt.title("Transcript Derivation Tree")  # type: ignore
        plt.axis("off")  # type: ignore
        plt.tight_layout()  # type: ignore
        plt.show()  # type: ignore

    def delete_transcript(self, transcript_id: str) -> None:
        """
        Delete an transcript from the forest and clean up any orphaned nodes.

        This method removes the transcript from all relevant data structures and
        cleans up any nodes that are no longer referenced by any transcript.
        It also updates transcript derivation relationships.

        Args:
            transcript_id: The ID of the transcript to delete.

        Raises:
            ValueError: If the transcript_id does not exist in the forest.
        """
        # Check if the transcript exists
        if transcript_id not in self.transcript_roots:
            raise ValueError(f"Transcript ID '{transcript_id}' not found in the forest.")

        # Get the root node for this transcript
        root_node_id = self.transcript_roots[transcript_id]

        # Remove transcript from transcript_roots
        del self.transcript_roots[transcript_id]

        # Remove transcript metadata
        if transcript_id in self.transcript_metadata:
            del self.transcript_metadata[transcript_id]

        # Update transcript derivation relationships
        # 1. Find transcripts derived from this one
        derived_transcripts = [
            exp_id
            for exp_id, parent_id in self.transcript_derivation.items()
            if parent_id == transcript_id
        ]

        # 2. Remove this transcript from derivation dict
        if transcript_id in self.transcript_derivation:
            del self.transcript_derivation[transcript_id]

        # 3. Recompute derivations for all affected transcripts
        for derived_exp_id in derived_transcripts:
            # Remove the old derivation relationship
            if derived_exp_id in self.transcript_derivation:
                del self.transcript_derivation[derived_exp_id]

            # Recompute the derivation if the transcript still exists
            if derived_exp_id in self.transcript_roots:
                derived_root_id = self.transcript_roots[derived_exp_id]
                self._infer_transcript_derivation(derived_exp_id, derived_root_id)

        # Start from the root node and traverse the path
        current_node_id = root_node_id
        current_node = self.node_dict[current_node_id]

        # Traverse the path, removing transcript_id from children dictionaries
        # and cleaning up orphaned nodes as we go
        self._remove_transcript_path(current_node, transcript_id)

    def _remove_transcript_path(self, node: Node, transcript_id: str) -> bool:
        """
        Remove transcript_id from a node's children and clean up orphaned nodes.

        This method traverses the path of the transcript, removing the transcript ID
        from each node's children dictionary. It also cleans up any nodes that become
        orphaned (no longer referenced by any transcript) during this process.

        Args:
            node: The current node to process.
            transcript_id: The ID of the transcript to remove.

        Returns:
            bool: True if the node should be kept, False if it can be removed.
        """
        # If this transcript has a child at this node
        if transcript_id in node.children:
            child_node = node.children[transcript_id]

            # Remove the transcript from this node's children
            del node.children[transcript_id]

            # Recursively process the child node
            # If the child node should be removed, we'll do that cleanup here
            should_keep_child = self._remove_transcript_path(child_node, transcript_id)

            if not should_keep_child:
                # The child node is orphaned, so we can clean it up

                # Remove from node_dict
                del self.node_dict[child_node.id]

                # If this is a root node, remove from key_to_root_id
                if child_node.data.node_type == "env_config":
                    env_config_key = child_node.data.key()
                    if (
                        env_config_key in self.key_to_root_id
                        and self.key_to_root_id[env_config_key] == child_node.id
                    ):
                        del self.key_to_root_id[env_config_key]

        # Determine if this node should be kept or removed
        # A node should be kept if:
        # 1. It has children (it's part of some transcript's path)
        # 2. It's a root node for any transcript
        if node.children or node.id in self.transcript_roots.values():
            return True

        # 3. Check if this node is part of any transcript's path by examining its parent
        # This is much more efficient than checking all nodes in the forest
        if node.parent_id and node.parent_id in self.node_dict:
            parent_node = self.node_dict[node.parent_id]
            # Check if any other transcript references this node through the parent
            for exp_id, child in parent_node.children.items():
                if child.id == node.id and exp_id != transcript_id:
                    return True

        # If we get here, the node is truly orphaned and can be removed
        return False

    def build_merged_experiment_tree(
        self,
        root_transcript_ids: list[str] | None = None,
    ) -> tuple[ExportGraph, dict[str, list[str]]]:
        """
        Build a merged derivation tree where transcripts with the same experiment ID are combined.

        This method creates a higher-level view of the transcript derivation tree by merging all
        transcripts that share the same experiment ID into a single node. The resulting graph shows
        relationships between experiment groups rather than individual transcripts.

        Args:
            root_transcript_ids: List of IDs of the root transcripts. If None, roots are inferred.

        Returns:
            Tuple of (NetworkX graph, experiment_to_transcripts mapping) for further customization.
        """
        if root_transcript_ids is None:
            root_transcript_ids = self._infer_root_transcripts()

        # First build the regular transcript derivation tree
        G_original = self.build_transcript_derivation_tree(root_transcript_ids)

        # Create a new graph for the merged representation
        G = ExportGraph()

        # Map from experiment ID to list of transcript IDs
        experiment_to_transcripts: dict[str, list[str]] = {}

        # Group transcripts by experiment ID
        for transcript_id in self.transcript_metadata.keys():
            if "experiment_id" not in self.transcript_metadata[transcript_id]:
                raise ValueError(
                    f"Experiment ID key 'experiment_id' not found in transcript metadata for transcript ID '{transcript_id}'"
                )

            experiment_id = str(self.transcript_metadata[transcript_id]["experiment_id"])
            experiment_to_transcripts.setdefault(experiment_id, []).append(transcript_id)

        # Create nodes for each experiment group
        for experiment_id, transcript_ids in experiment_to_transcripts.items():
            # Count correct/total transcripts
            num_transcripts, total_score = 0, 0
            for transcript_id in transcript_ids:
                num_transcripts += 1
                score_key = self.transcript_metadata[transcript_id]["default_score_key"]
                if score_key:
                    total_score += self.transcript_metadata[transcript_id]["scores"].get(score_key)
            mean_score = total_score / num_transcripts

            # Try to find an experiment description from any transcript in this group
            intervention_description = None
            for transcript_id in transcript_ids:
                if (
                    cur := self.transcript_metadata[transcript_id].get("intervention_description")
                ) is None:
                    logger.warning(
                        f"Experiment description key 'intervention_description' not found in transcript metadata for transcript ID '{transcript_id}'"
                    )
                if cur is not None:
                    intervention_description = cur
                    break

            # Add node for this experiment
            G.add_node(
                {
                    "id": experiment_id,
                    "data": {
                        "description": intervention_description,
                        "num_transcripts": num_transcripts,
                        "mean_score": mean_score,
                        "transcript_ids": transcript_ids,
                    },
                }
            )

        # Create edges between experiment groups
        for src_exp_id, src_transcripts in experiment_to_transcripts.items():
            for dst_exp_id, dst_transcripts in experiment_to_transcripts.items():
                if src_exp_id == dst_exp_id:
                    continue

                # Check if there's any edge from a transcript in src to a transcript in dst
                edges_between_groups: list[tuple[str, str]] = []
                for src_t_id in src_transcripts:
                    for dst_t_id in dst_transcripts:
                        if G_original.has_edge(src_t_id, dst_t_id):
                            edges_between_groups.append((src_t_id, dst_t_id))

                # If there are edges between the groups, add an edge in the merged graph
                if edges_between_groups:
                    G.add_edge(
                        {
                            "source": src_exp_id,
                            "target": dst_exp_id,
                            "data": {
                                "weight": len(edges_between_groups),
                                "transcript_edges": edges_between_groups,
                            },
                        }
                    )

        return G, experiment_to_transcripts

    def plot_merged_experiment_tree(
        self,
        root_transcript_ids: list[str] | None = None,
        figsize: tuple[float, float] = (18, 12),
        node_size: int = 2000,
        font_size: int = 10,
        color_configs: list[NodeColorConfig] | None = None,
    ) -> tuple[nx.DiGraph, dict[str, tuple[float, float]]]:
        """
        Visualize a merged derivation tree where transcripts with the same experiment ID are combined.

        This method creates a higher-level view of the transcript derivation tree by merging all
        transcripts that share the same experiment ID into a single node. The resulting graph shows
        relationships between experiment groups rather than individual transcripts.

        Args:
            root_transcript_ids: List of IDs of the root transcripts. If None, roots are inferred.
            figsize: Size of the figure (width, height) in inches.
            node_size: Size of the nodes in the plot.
            font_size: Size of the font for node labels.
            color_configs: List of NodeColorConfig objects that define coloring rules based on metadata.

        Returns:
            Tuple of (NetworkX graph, node positions) for further customization.
        """
        # Build the merged experiment tree
        G_merged_export, experiment_to_transcripts = self.build_merged_experiment_tree(
            root_transcript_ids
        )
        G_merged = G_merged_export.export_as_nx()

        # Plot the merged graph
        plt.figure(figsize=figsize)  # type: ignore

        # Use a hierarchical layout
        try:
            pos = nx.nx_agraph.graphviz_layout(G_merged, prog="dot", args="-Grankdir=TB")  # type: ignore
        except ImportError:
            print("pygraphviz not available, using spring_layout instead.")
            # For spring_layout, increase k parameter to push nodes further apart
            pos = cast(dict[str, tuple[float, float]], nx.spring_layout(G_merged, seed=42, k=0.5))  # type: ignore

        # Ensure pos is properly typed
        pos_dict: dict[str, tuple[float, float]] = cast(dict[str, tuple[float, float]], pos)

        # Draw nodes with colors based on accuracy
        for experiment_id in G_merged.nodes():  # type: ignore
            # Get accuracy metrics
            num_transcripts = G_merged.nodes[experiment_id].get("num_transcripts", 0)  # type: ignore
            mean_score = G_merged.nodes[experiment_id].get("mean_score", 0)  # type: ignore

            # Determine node color based on accuracy
            if num_transcripts == 0:
                node_color = "lightgray"  # No transcripts
            elif mean_score == 0:
                node_color = "salmon"  # No correct transcripts
            elif mean_score >= 0.8:
                node_color = "limegreen"  # All transcripts are correct
            else:
                node_color = "yellowgreen"  # Some are correct

            # Draw this node with the appropriate color
            nx.draw_networkx_nodes(  # type: ignore
                G_merged,
                pos_dict,
                nodelist=[experiment_id],
                node_color=node_color,
                node_size=node_size,
                alpha=0.8,
            )

        # Draw edges
        nx.draw_networkx_edges(  # type: ignore
            G_merged,
            pos_dict,
            width=2.0,  # Use a fixed width for all edges
            arrows=True,
            arrowsize=20,
        )

        # Highlight all experiments containing root transcripts
        if root_transcript_ids is not None:
            # Find experiment IDs that contain root transcripts using the experiment_to_transcripts mapping
            root_experiment_ids: set[str] = set()
            for exp_id, transcript_ids in experiment_to_transcripts.items():
                if any(t_id in root_transcript_ids for t_id in transcript_ids):
                    root_experiment_ids.add(exp_id)

            # Filter to only include experiment IDs that are in the graph
            root_experiment_ids_list: list[str] = [
                exp_id for exp_id in root_experiment_ids if exp_id in G_merged
            ]

            if root_experiment_ids_list:
                nx.draw_networkx_nodes(  # type: ignore
                    G_merged,
                    pos_dict,
                    nodelist=root_experiment_ids_list,
                    node_color="none",  # Transparent fill
                    node_size=node_size + 200,  # Slightly larger to create a border effect
                    alpha=1.0,
                    linewidths=3,
                    edgecolors="gold",
                )

        # Create custom labels for experiment nodes
        custom_labels = {}
        for experiment_id in G_merged.nodes():  # type: ignore
            num_transcripts = G_merged.nodes[experiment_id].get("num_transcripts", 0)  # type: ignore
            mean_score = G_merged.nodes[experiment_id].get("mean_score", 0)  # type: ignore

            # Get experiment description if available, otherwise use ID
            description = G_merged.nodes[experiment_id].get("description")  # type: ignore
            label = description if description else experiment_id  # type: ignore

            # Create a descriptive label with score
            custom_labels[experiment_id] = (
                f"{label}\n({num_transcripts} transcripts, {mean_score:.2f} score)"
            )
        nx.draw_networkx_labels(G_merged, pos_dict, labels=custom_labels, font_size=font_size)  # type: ignore

        plt.title("Merged Experiment Derivation Tree")  # type: ignore
        plt.axis("off")  # type: ignore
        plt.tight_layout()  # type: ignore
        plt.show()  # type: ignore

        return G_merged, pos_dict


def _print_tree_node(tree: dict[str, Any], indent_level: int, all_exp_ids: list[str]) -> None:
    """
    Helper method to recursively print a tree structure with proper indentation.

    Args:
        tree: Dictionary representing the tree structure.
        indent_level: Current indentation level.
        all_exp_ids: List of all transcript IDs in this tree.
    """
    # Sort nodes to maintain consistent order
    for path_key in sorted(tree.keys(), key=lambda k: tree[k]["depth"]):
        node_data = tree[path_key]

        # Create the indentation
        indent = "  " * indent_level

        # Get the node data
        node = node_data["node"]
        exps = node_data["exps"]

        # Determine if this is a divergence point
        is_divergence = len(exps) < len(all_exp_ids) and indent_level > 0

        # Format transcript IDs that pass through this node
        exp_str = ", ".join(exps)

        # Format the node string
        node_type = node.data.get_type() if hasattr(node.data, "get_type") else "unknown"
        node_label = node.data.get_label() if hasattr(node.data, "get_label") else str(node.data)

        # Print with appropriate formatting
        if is_divergence:
            logger.info(f"{indent}↳ [{node_type}] {node_label} ({exp_str})")
        else:
            logger.info(f"{indent}• [{node_type}] {node_label} ({exp_str})")

        # Recursively print children
        _print_tree_node(node_data["children"], indent_level + 1, all_exp_ids)
