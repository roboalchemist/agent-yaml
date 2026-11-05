import json
import os
import queue
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from agent_yaml.web.app import create_app
from agent_yaml.web.db import AgentYamlDB
from agent_yaml.web.runtime import RunManager
from agent_yaml.web.scheduler import compute_next_run, parse_interval_seconds


def test_db_records_events_and_node_state(tmp_path):
    db = AgentYamlDB(str(tmp_path / "runs.sqlite3"))
    try:
        workflow = db.create_workflow_version(
            "test",
            str(tmp_path / "workflow.yaml"),
            "directory: /tmp\ntask: []\n",
            {"nodes": [], "edges": []},
        )
        run = db.create_run(workflow["id"], trigger="manual")

        event = db.record_event(
            run["id"],
            {
                "type": "task_started",
                "timestamp": "2026-05-21T10:00:00+00:00",
                "node_id": "0.setup",
                "status": "running",
                "task_name": "setup",
            },
        )

        assert event["type"] == "task_started"
        states = db.list_node_states(run["id"])
        assert states[0]["node_id"] == "0.setup"
        assert states[0]["status"] == "running"
        assert states[0]["attempts"] == 1
    finally:
        db.close()


def test_schedule_next_run_interval_and_cron():
    now = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)

    assert parse_interval_seconds("5m") == 300
    assert compute_next_run("interval", "5m", now=now).startswith("2026-05-21T12:05:00")
    assert compute_next_run("cron", "*/15 * * * *", "UTC", now=now).startswith(
        "2026-05-21T12:15:00"
    )


def test_run_manager_persists_events_from_event_sink(tmp_path, monkeypatch):
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text("directory: /tmp\ntask:\n  - hello:\n      prompt: hi\n")
    db = AgentYamlDB(str(tmp_path / "runs.sqlite3"))
    manager = RunManager(db, max_workers=1)
    try:
        workflow = manager.import_workflow(str(workflow_file))

        def fake_run_workflow(path, dry_run=False, var_overrides=None, event_sink=None, **_kwargs):
            assert path == str(workflow_file)
            assert dry_run is True
            assert var_overrides == {"topic": "docs"}
            event_sink(
                {
                    "type": "task_started",
                    "node_id": "0.hello",
                    "status": "running",
                    "timestamp": "2026-05-21T10:00:00+00:00",
                }
            )
            event_sink(
                {
                    "type": "task_completed",
                    "node_id": "0.hello",
                    "status": "success",
                    "timestamp": "2026-05-21T10:00:02+00:00",
                }
            )
            return 0

        monkeypatch.setattr("agent_yaml.web.runtime.run_workflow", fake_run_workflow)

        run = manager.start_run(
            workflow["id"],
            trigger="manual",
            dry_run=True,
            variables={"topic": "docs"},
        )
        manager.executor.shutdown(wait=True)

        stored = db.get_run(run["id"])
        assert stored["status"] == "success"
        assert stored["exit_code"] == 0
        event_types = [event["type"] for event in db.list_events(run["id"])]
        assert "task_started" in event_types
        assert "task_completed" in event_types
        assert db.list_node_states(run["id"])[0]["status"] == "success"
    finally:
        manager.executor.shutdown(wait=True)
        db.close()


def test_workflows_discover_lists_examples_and_tasks(tmp_path, monkeypatch):
    """Discovery endpoint walks examples/ and tasks/, returns sorted results."""
    # Create temp directories with YAML workflow files
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Valid YAML mapping files
    (examples_dir / "foo.yaml").write_text("directory: /tmp\ntask: []\n")
    (tasks_dir / "bar.yaml").write_text("directory: /tmp\ntask: []\n")

    # A non-mapping YAML file (list) — should be silently skipped
    (examples_dir / "not-a-workflow.yaml").write_text("- item1\n- item2\n")

    # Point the discovery at tmp_path as cwd
    monkeypatch.chdir(tmp_path)

    app = create_app(db_path=str(tmp_path / "runs.sqlite3"))
    client = TestClient(app)

    response = client.get("/api/workflows/discover")
    assert response.status_code == 200

    data = response.json()
    # The non-mapping file should be excluded
    rel_paths = [entry["relative_path"] for entry in data]
    assert os.path.join("tasks", "bar.yaml") in rel_paths
    assert os.path.join("examples", "foo.yaml") in rel_paths
    assert os.path.join("examples", "not-a-workflow.yaml") not in rel_paths

    # Check directory and name fields
    foo_entry = next(e for e in data if e["name"] == "foo.yaml")
    assert foo_entry["directory"] == "examples"
    assert foo_entry["name"] == "foo.yaml"
    assert foo_entry["relative_path"] == os.path.join("examples", "foo.yaml")
    assert os.path.isabs(foo_entry["absolute_path"])

    bar_entry = next(e for e in data if e["name"] == "bar.yaml")
    assert bar_entry["directory"] == "tasks"

    # Verify sort order: examples before tasks (alphabetical by directory, then name)
    directories = [e["directory"] for e in data]
    assert directories == sorted(directories), "results must be sorted by (directory, name)"


def test_discover_entries_carry_catalog_metadata(tmp_path, monkeypatch):
    """Each discovery entry exposes id/agent/directory/stage count for the UI catalog."""
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "solo.yaml").write_text(
        "directory: /work\ncli-agent: opencode\ndescription: |\n  A demo workflow.\n"
        "  Second line.\ntask:\n  - one:\n      prompt: hi\n"
        "  - group:\n      a: {prompt: a}\n      b:\n        loop: {type: csv, source: data.csv}\n"
    )
    monkeypatch.chdir(tmp_path)

    client = TestClient(create_app(db_path=str(tmp_path / "runs.sqlite3")))
    entry = client.get("/api/workflows/discover").json()[0]

    assert entry["id"] == os.path.join("examples", "solo.yaml")
    assert entry["cli_agent"] == "opencode"
    assert entry["workflow_directory"] == "/work"
    assert entry["stage_count"] == 3
    assert entry["description"] == "A demo workflow."


def test_run_state_endpoint_returns_node_states(tmp_path):
    """The graph restore endpoint exposes node status/attempts for a persisted run."""
    db_path = str(tmp_path / "runs.sqlite3")
    client = TestClient(create_app(db_path=db_path))

    db = AgentYamlDB(db_path=db_path)
    try:
        workflow = db.create_workflow_version(
            "wf", str(tmp_path / "wf.yaml"), "directory: /tmp\ntask: []\n", {"nodes": [], "edges": []}
        )
        run = db.create_run(workflow["id"], trigger="manual")
        db.record_event(
            run["id"],
            {
                "type": "task_started",
                "timestamp": "2026-05-21T10:00:00+00:00",
                "node_id": "0.hello",
                "status": "running",
            },
        )
        db.record_event(
            run["id"],
            {
                "type": "task_completed",
                "timestamp": "2026-05-21T10:00:03+00:00",
                "node_id": "0.hello",
                "status": "success",
            },
        )
    finally:
        db.close()

    response = client.get(f"/api/runs/{run['id']}/state")
    assert response.status_code == 200
    body = response.json()
    assert body["run"]["id"] == run["id"]
    assert body["nodes"][0]["node_id"] == "0.hello"
    assert body["nodes"][0]["status"] == "success"
    assert body["nodes"][0]["attempts"] == 1


def test_run_state_endpoint_404(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "runs.sqlite3")))
    assert client.get("/api/runs/999/state").status_code == 404


def test_event_stream_does_not_repeat_persisted_events(tmp_path, monkeypatch):
    """Replay + live queue can both carry an event; the stream must emit each id once."""
    db = AgentYamlDB(str(tmp_path / "runs.sqlite3"))
    manager = RunManager(db, max_workers=1)
    try:
        workflow = db.create_workflow_version(
            "wf", str(tmp_path / "wf.yaml"), "directory: /tmp\ntask: []\n", {"nodes": [], "edges": []}
        )
        run = db.create_run(workflow["id"], trigger="manual")
        started = db.record_event(
            run["id"],
            {"type": "task_started", "node_id": "a", "status": "running", "ts": "2026-05-21T10:00:00+00:00"},
        )
        finished = db.record_event(
            run["id"],
            {"type": "task_completed", "node_id": "a", "status": "success", "ts": "2026-05-21T10:00:01+00:00"},
        )

        # Simulate the race: the live queue also carries the already-persisted event.
        subscriber = queue.Queue()
        subscriber.put(started)
        subscriber.put(finished)
        monkeypatch.setattr(manager, "subscribe", lambda run_id: subscriber)

        stream = manager.event_stream(run["id"])
        first = json.loads(next(stream)[len("data: "):])
        second = json.loads(next(stream)[len("data: "):])
        stream.close()

        assert [first["id"], second["id"]] == [started["id"], finished["id"]]
        assert first["type"] == "task_started"
        assert second["type"] == "task_completed"
    finally:
        manager.executor.shutdown(wait=True)
        db.close()


def test_static_assets_ship_the_webgl_renderer(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "runs.sqlite3")))

    page = client.get("/")
    assert page.status_code == 200
    assert "gl-canvas" in page.text
    assert "/static/app.js" in page.text

    renderer = client.get("/static/webgl.js")
    assert renderer.status_code == 200
    assert 'getContext("webgl2"' in renderer.text
