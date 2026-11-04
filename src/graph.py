"""Workflow graph projection for the web editor."""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Tuple

from .parser import parse_workflow

# Layout constants
COL_WIDTH = 180   # horizontal distance between depth levels
ROW_HEIGHT = 124  # vertical height of one row slot
MARGIN_X = 40     # left margin for depth-0 (workflow root)
MARGIN_Y = 40     # top margin


def workflow_to_graph_file(filepath: str) -> Dict[str, Any]:
    """Load a workflow YAML file and return its editable graph projection."""
    workflow = parse_workflow(filepath)
    graph = workflow_to_graph(workflow)
    graph["source_path"] = os.path.abspath(os.path.expanduser(filepath))
    return graph


def workflow_to_graph(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an agent-yaml workflow dict to graph nodes and edges."""
    compiler = _GraphCompiler()
    task_tree = workflow.get("task", [])

    # First pass: compute total row height of the entire task tree
    total_rows = _subtree_height(task_tree)
    # Vertical center of the whole layout (used to place the workflow root)
    span_center = MARGIN_Y + (total_rows * ROW_HEIGHT) / 2

    # Second pass: compile and place all task nodes
    entries, exits = compiler.compile_task_tree(
        task_tree,
        parent_id="workflow",
        depth=1,
        band_start=MARGIN_Y,
        band_rows=total_rows,
    )

    metadata = {
        "directory": workflow.get("directory", "."),
        "cli-agent": workflow.get("cli-agent", "claude"),
        "cli-agent-config": workflow.get("cli-agent-config", {}),
        "on-error": workflow.get("on-error", "fail"),
        "template-variables": workflow.get("template-variables", {}),
        "environment": workflow.get("environment", {}),
        "includes": workflow.get("includes", {}),
        "ensure": workflow.get("ensure", {}),
    }
    compiler.nodes.insert(
        0,
        {
            "id": "workflow",
            "type": "workflow",
            "label": "Workflow",
            "status": "idle",
            "data": metadata,
            "position": {"x": MARGIN_X, "y": span_center},
        },
    )
    for entry in entries:
        compiler.add_edge("workflow", entry, "starts")

    return {
        "version": 1,
        "metadata": metadata,
        "nodes": compiler.nodes,
        "edges": compiler.edges,
        "entry_node_ids": entries,
        "exit_node_ids": exits,
    }


def graph_to_workflow(graph: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a graph produced by ``workflow_to_graph`` back to a workflow.

    v1 keeps the original task tree on nodes, so this supports editing node
    payloads and metadata without requiring a lossy graph layout algorithm.
    """
    metadata = copy.deepcopy(graph.get("metadata", {}))
    workflow = {key: value for key, value in metadata.items() if value not in ({}, [], None)}
    task_nodes = [
        node
        for node in graph.get("nodes", [])
        if node.get("type") in {"task", "loop", "parallel_group", "group"}
        and node.get("data", {}).get("task_tree") is not None
    ]
    root_nodes = [node for node in task_nodes if node.get("data", {}).get("path_depth") == 1]
    root_nodes.sort(key=lambda node: node.get("data", {}).get("ordinal", 0))
    workflow["task"] = [
        copy.deepcopy(node["data"]["task_tree"]) for node in root_nodes
    ]
    return workflow


def _subtree_height(task_tree: Any) -> int:
    """
    Compute the number of row slots consumed by a subtree.

    - list (sequential):  sum of children heights
    - dict leaf (loop or task with prompt): 1
    - dict group (parallel): max(1, sum of children heights)
    - anything else: 1
    """
    if isinstance(task_tree, list):
        if not task_tree:
            return 1
        return sum(_subtree_height(step) for step in task_tree)

    if isinstance(task_tree, dict):
        # Leaf nodes
        if "loop" in task_tree or "prompt" in task_tree:
            return 1
        # Parallel/group node: height is the sum of its children's heights
        # (they are laid out vertically even though they run in parallel)
        child_heights = sum(_subtree_height(v) for v in task_tree.values())
        return max(1, child_heights)

    return 1


class _GraphCompiler:
    def __init__(self):
        self.nodes: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        # ordinal per depth for graph_to_workflow reconstruction (sequential order)
        self._depth_ordinal: Dict[int, int] = {}

    def add_edge(self, source: str, target: str, label: str = ""):
        edge_id = f"{source}->{target}:{len(self.edges)}"
        self.edges.append({"id": edge_id, "source": source, "target": target, "label": label})

    def _next_ordinal(self, depth: int) -> int:
        ordinal = self._depth_ordinal.get(depth, 0)
        self._depth_ordinal[depth] = ordinal + 1
        return ordinal

    def add_node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        task_tree: Any,
        path: Tuple[str, ...],
        x: float,
        y: float,
    ):
        depth = len(path)
        ordinal = self._next_ordinal(depth)
        self.nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": label,
                "status": "idle",
                "data": {
                    "path": list(path),
                    "path_depth": depth,
                    "ordinal": ordinal,
                    "task_tree": copy.deepcopy(task_tree),
                    "summary": _summarize_task_tree(task_tree),
                },
                "position": {"x": x, "y": y},
            }
        )

    def compile_task_tree(
        self,
        task_tree: Any,
        parent_id=None,
        path: Tuple[str, ...] = (),
        depth: int = 1,
        band_start: float = MARGIN_Y,
        band_rows: int = 1,
    ) -> Tuple[List[str], List[str]]:
        """
        Recursively compile task_tree into nodes and edges.

        Parameters
        ----------
        task_tree : Any
            The workflow task tree (list, dict, or leaf value).
        parent_id : str | None
            Parent node id (for edge creation).
        path : tuple of str
            Path from root to this node (used as node id and label).
        depth : int
            Column index (depth 1 = first task column after workflow root).
        band_start : float
            Top y-coordinate (in pixels) of the vertical band allocated to this subtree.
        band_rows : int
            Number of row slots allocated to this subtree.
        """
        if isinstance(task_tree, list):
            entries: List[str] = []
            previous_exits: List[str] = []
            current_band_start = band_start
            for index, step in enumerate(task_tree):
                child_rows = _subtree_height(step)
                child_entries, child_exits = self.compile_task_tree(
                    step,
                    parent_id=parent_id,
                    path=path + (str(index),),
                    depth=depth,
                    band_start=current_band_start,
                    band_rows=child_rows,
                )
                if not entries:
                    entries = child_entries
                for previous_exit in previous_exits:
                    for child_entry in child_entries:
                        self.add_edge(previous_exit, child_entry, "then")
                previous_exits = child_exits
                current_band_start += child_rows * ROW_HEIGHT
            return entries, previous_exits

        if isinstance(task_tree, dict):
            node_id = ".".join(path) if path else "task"
            x = MARGIN_X + depth * COL_WIDTH
            y = band_start + (band_rows * ROW_HEIGHT) / 2

            if "loop" in task_tree:
                label = _path_label(path, "Loop")
                self.add_node(node_id, "loop", label, task_tree, path, x, y)
                return [node_id], [node_id]

            if "prompt" in task_tree:
                label = _path_label(path, "Task")
                self.add_node(node_id, "task", label, task_tree, path, x, y)
                return [node_id], [node_id]

            # Parallel group node: placed at center of its band
            group_type = "parallel_group" if len(task_tree) > 1 else "group"
            label = _path_label(path, "Parallel" if group_type == "parallel_group" else "Group")
            self.add_node(node_id, group_type, label, task_tree, path, x, y)

            entries_out = [node_id]
            exits_out: List[str] = []
            child_band_start = band_start
            for key, child in task_tree.items():
                child_rows = _subtree_height(child)
                child_entries, child_exits = self.compile_task_tree(
                    child,
                    parent_id=node_id,
                    path=path + (key,),
                    depth=depth + 1,
                    band_start=child_band_start,
                    band_rows=child_rows,
                )
                for child_entry in child_entries:
                    self.add_edge(node_id, child_entry, "contains")
                exits_out.extend(child_exits)
                child_band_start += child_rows * ROW_HEIGHT
            return entries_out, exits_out or [node_id]

        return [], []


def _path_label(path: Tuple[str, ...], fallback: str) -> str:
    if not path:
        return fallback
    label = path[-1]
    if label.isdigit():
        return f"{fallback} {int(label) + 1}"
    return label.replace("-", " ").replace("_", " ").title()


def _path_ordinal(path: Tuple[str, ...]) -> int:
    return sum(int(part) if part.isdigit() else 1 for part in path)


def _summarize_task_tree(task_tree: Any) -> Dict[str, Any]:
    if not isinstance(task_tree, dict):
        return {}
    if "loop" in task_tree:
        loop = task_tree.get("loop", {})
        return {"kind": "loop", "loop_type": loop.get("type"), "workers": loop.get("workers", 1)}
    if "prompt" in task_tree:
        prompt = task_tree.get("prompt", "")
        return {
            "kind": "task",
            "prompt_preview": prompt[:160],
            "has_validators": bool(task_tree.get("validate")),
            "on_error": task_tree.get("on-error"),
        }
    return {"kind": "group", "children": list(task_tree.keys())}
