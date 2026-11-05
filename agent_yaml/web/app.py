"""FastAPI application for the agent-yaml visual runner."""

import glob
import os
import sys
from typing import Any, Dict, List, Optional

from agent_yaml.web.db import AgentYamlDB
from agent_yaml.web.runtime import RunManager
from agent_yaml.web.scheduler import DEFAULT_TIMEZONE, compute_next_run

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - create_app reports the actionable error
    BaseModel = object
    Field = None


class ImportWorkflowRequest(BaseModel):
    path: str
    name: Optional[str] = None


class RunRequest(BaseModel):
    dry_run: bool = False
    variables: Dict[str, str] = Field(default_factory=dict)


class ScheduleRequest(BaseModel):
    workflow_version_id: int
    name: str
    kind: str
    expression: str
    timezone: str = DEFAULT_TIMEZONE
    active: bool = True


class SchedulePatchRequest(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    expression: Optional[str] = None
    timezone: Optional[str] = None
    active: Optional[bool] = None


def _count_stages(task_tree: Any) -> int:
    """
    Count executable stages in a task tree.

    A leaf (prompt or loop) is one stage; a group contributes its children, so the
    number is the count of agent invocations a run can perform.
    """
    if isinstance(task_tree, list):
        return sum(_count_stages(step) for step in task_tree)

    if isinstance(task_tree, dict):
        if "loop" in task_tree or "prompt" in task_tree:
            return 1
        if task_tree.get("task"):
            return _count_stages(task_tree["task"])
        meta = {
            "prompt", "task", "loop", "include", "on-error", "directory",
            "cli-agent-config", "validate", "retry", "skip-if", "env", "when",
        }
        return sum(
            _count_stages(value)
            for key, value in task_tree.items()
            if key not in meta and isinstance(value, (dict, list))
        )

    return 0


def _discover_workflows(cwd: str) -> List[Dict[str, Any]]:
    """
    Walk examples/ and tasks/ relative to cwd for *.yaml and *.yml files.

    Returns a list of dicts sorted by (directory, name):
        {id, directory, name, relative_path, absolute_path,
         cli_agent, workflow_directory, stage_count, description}

    Files that don't parse as YAML mappings are silently skipped.
    """
    try:
        import yaml as _yaml
    except ImportError:
        _yaml = None  # type: ignore[assignment]

    results: List[Dict[str, Any]] = []
    for directory in ("examples", "tasks"):
        dir_path = os.path.join(cwd, directory)
        if not os.path.isdir(dir_path):
            continue
        for pattern in ("*.yaml", "*.yml"):
            for abs_path in glob.glob(os.path.join(dir_path, pattern)):
                name = os.path.basename(abs_path)
                rel_path = os.path.join(directory, name)
                # Skip files that don't parse as YAML mappings
                if _yaml is not None:
                    try:
                        with open(abs_path, "r", encoding="utf-8") as fh:
                            data = _yaml.safe_load(fh)
                        if not isinstance(data, dict):
                            continue
                    except Exception:
                        print(
                            f"[discover] skipping {rel_path}: parse error",
                            file=sys.stderr,
                        )
                        continue
                workflow = data if isinstance(data, dict) else {}
                description = workflow.get("description") or workflow.get("name") or ""
                if isinstance(description, str):
                    description = description.strip().splitlines()[0][:140] if description.strip() else ""
                else:
                    description = ""
                results.append(
                    {
                        "id": rel_path,
                        "directory": directory,
                        "name": name,
                        "relative_path": rel_path,
                        "absolute_path": os.path.abspath(abs_path),
                        "cli_agent": workflow.get("cli-agent", "claude"),
                        "workflow_directory": workflow.get("directory", "."),
                        "stage_count": _count_stages(workflow.get("task", [])),
                        "description": description,
                    }
                )
    results.sort(key=lambda entry: (entry["directory"], entry["name"]))
    return results


def create_app(db_path: Optional[str] = None):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - exercised by CLI environments
        raise RuntimeError(
            "The web UI requires optional dependencies. Install with: "
            "pip install fastapi uvicorn pydantic"
        ) from exc

    app = FastAPI(title="agent-yaml visual runner")
    db = AgentYamlDB(db_path=db_path)
    manager = RunManager(db)
    static_dir = os.path.join(os.path.dirname(__file__), "static")

    @app.on_event("startup")
    def _startup():
        manager.start_scheduler()

    @app.on_event("shutdown")
    def _shutdown():
        manager.stop_scheduler()
        db.close()

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/workflows/import")
    def import_workflow(request: ImportWorkflowRequest):
        path = os.path.abspath(os.path.expanduser(request.path))
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"workflow not found: {path}")
        try:
            return manager.import_workflow(path, request.name)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/workflows")
    def list_workflows():
        return db.list_workflow_versions()

    @app.get("/api/workflows/discover")
    def discover_workflows():
        """List available YAML workflows in examples/ and tasks/ relative to cwd."""
        return _discover_workflows(os.getcwd())

    @app.get("/api/workflows/{workflow_version_id}")
    def get_workflow(workflow_version_id: int):
        workflow = db.get_workflow_version(workflow_version_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="workflow not found")
        return workflow

    @app.post("/api/workflows/{workflow_version_id}/runs")
    def start_run(workflow_version_id: int, request: RunRequest):
        try:
            return manager.start_run(
                workflow_version_id,
                trigger="manual",
                dry_run=request.dry_run,
                variables=request.variables,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runs")
    def list_runs(limit: int = 100):
        return db.list_runs(limit=limit)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int):
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/api/runs/{run_id}/events")
    def list_events(run_id: int):
        return db.list_events(run_id)

    @app.get("/api/runs/{run_id}/state")
    def get_run_state(run_id: int):
        """Node states for a run (status, attempts, started/finished) for graph restore."""
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run": run, "nodes": db.list_node_states(run_id)}

    @app.get("/api/runs/{run_id}/stream")
    def stream_events(run_id: int):
        if not db.get_run(run_id):
            raise HTTPException(status_code=404, detail="run not found")
        return StreamingResponse(manager.event_stream(run_id), media_type="text/event-stream")

    @app.get("/api/schedules")
    def list_schedules():
        return db.list_schedules()

    @app.post("/api/schedules")
    def create_schedule(request: ScheduleRequest):
        if not db.get_workflow_version(request.workflow_version_id):
            raise HTTPException(status_code=404, detail="workflow not found")
        try:
            return manager.create_schedule(
                request.workflow_version_id,
                request.name,
                request.kind,
                request.expression,
                request.timezone,
                active=request.active,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/schedules/{schedule_id}")
    def update_schedule(schedule_id: int, request: SchedulePatchRequest):
        schedule = db.get_schedule(schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="schedule not found")
        updates = request.dict(exclude_unset=True)
        kind = updates.get("kind", schedule["kind"])
        expression = updates.get("expression", schedule["expression"])
        timezone_name = updates.get("timezone", schedule["timezone"])
        active = updates.get("active", schedule["active"])
        if active:
            updates["next_run_at"] = compute_next_run(kind, expression, timezone_name)
        else:
            updates["next_run_at"] = None
        try:
            db.update_schedule(schedule_id, **updates)
            return db.get_schedule(schedule_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/schedules/{schedule_id}")
    def delete_schedule(schedule_id: int):
        db.delete_schedule(schedule_id)
        return {"status": "deleted"}

    return app
