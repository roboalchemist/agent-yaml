from agent_yaml.graph import COL_WIDTH, MARGIN_X, MARGIN_Y, ROW_HEIGHT, graph_to_workflow, workflow_to_graph


def test_workflow_to_graph_projects_parallel_and_loop_nodes():
    workflow = {
        "directory": "/tmp",
        "cli-agent": "claude",
        "task": [
            {
                "setup": {"prompt": "prepare"},
                "scan": {"prompt": "scan"},
            },
            {
                "items": {
                    "loop": {"type": "csv", "source": "items.csv", "workers": 2},
                    "prompt": "process {{loop.item.name}}",
                }
            },
        ],
    }

    graph = workflow_to_graph(workflow)
    node_types = {node["id"]: node["type"] for node in graph["nodes"]}

    assert node_types["workflow"] == "workflow"
    assert node_types["0"] == "parallel_group"
    assert node_types["0.setup"] == "task"
    assert node_types["0.scan"] == "task"
    assert node_types["1.items"] == "loop"
    assert any(edge["label"] == "then" for edge in graph["edges"])


def test_graph_to_workflow_round_trips_root_task_tree():
    workflow = {
        "directory": "/tmp",
        "template-variables": {"name": "world"},
        "task": [{"hello": {"prompt": "hello {{name}}"}}],
    }

    graph = workflow_to_graph(workflow)
    rebuilt = graph_to_workflow(graph)

    assert rebuilt["directory"] == "/tmp"
    assert rebuilt["template-variables"] == {"name": "world"}
    assert rebuilt["task"] == workflow["task"]


def test_layout_no_overlap_for_parallel_and_sequential():
    """
    Two sequential steps, each a 3-way parallel group.
    No two node bounding boxes should overlap given NODE_WIDTH=150, NODE_HEIGHT=104.
    """
    NODE_WIDTH = 150
    NODE_HEIGHT = 104

    workflow = {
        "directory": "/tmp",
        "cli-agent": "claude",
        "task": [
            {
                "step-a": {"prompt": "do a"},
                "step-b": {"prompt": "do b"},
                "step-c": {"prompt": "do c"},
            },
            {
                "step-d": {"prompt": "do d"},
                "step-e": {"prompt": "do e"},
                "step-f": {"prompt": "do f"},
            },
        ],
    }

    graph = workflow_to_graph(workflow)

    # Build axis-aligned bounding boxes centered on each node's position
    def bbox(node):
        x = node["position"]["x"]
        y = node["position"]["y"]
        half_w = NODE_WIDTH / 2
        half_h = NODE_HEIGHT / 2
        return (x - half_w, y - half_h, x + half_w, y + half_h)

    def overlaps(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1

    nodes = graph["nodes"]
    for i, node_a in enumerate(nodes):
        for j, node_b in enumerate(nodes):
            if i >= j:
                continue
            box_a = bbox(node_a)
            box_b = bbox(node_b)
            assert not overlaps(box_a, box_b), (
                f"Nodes overlap: {node_a['id']} at {node_a['position']} "
                f"and {node_b['id']} at {node_b['position']}"
            )

    # Verify structural correctness: parallel group nodes exist at depth 1
    node_types = {node["id"]: node["type"] for node in nodes}
    assert node_types["0"] == "parallel_group"
    assert node_types["1"] == "parallel_group"
    assert node_types["0.step-a"] == "task"
    assert node_types["0.step-b"] == "task"
    assert node_types["0.step-c"] == "task"
    assert node_types["1.step-d"] == "task"
    assert node_types["1.step-e"] == "task"
    assert node_types["1.step-f"] == "task"

    # Verify the two sequential group nodes share the same x (same depth)
    node_positions = {node["id"]: node["position"] for node in nodes}
    assert node_positions["0"]["x"] == node_positions["1"]["x"], (
        "Sequential parallel groups should be in the same column"
    )
    expected_group_x = MARGIN_X + 1 * COL_WIDTH
    assert node_positions["0"]["x"] == expected_group_x

    # All depth-2 task nodes should share the same x column
    depth2_nodes = [n for n in nodes if n.get("data", {}).get("path_depth") == 2]
    xs = {n["position"]["x"] for n in depth2_nodes}
    assert len(xs) == 1, f"All depth-2 tasks should share x={MARGIN_X + 2 * COL_WIDTH}, got {xs}"
    assert xs.pop() == MARGIN_X + 2 * COL_WIDTH

    # Verify workflow root is at MARGIN_X and vertically centered
    workflow_node = next(n for n in nodes if n["id"] == "workflow")
    assert workflow_node["position"]["x"] == MARGIN_X
    # Total height = 6 rows; center = MARGIN_Y + 6 * ROW_HEIGHT / 2 = 40 + 372 = 412
    expected_root_y = MARGIN_Y + (6 * ROW_HEIGHT) / 2
    assert workflow_node["position"]["y"] == expected_root_y
