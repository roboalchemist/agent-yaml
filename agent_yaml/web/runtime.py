"""Run orchestration for the local web app."""

from __future__ import annotations

import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional

from agent_yaml.cli import run_workflow
from agent_yaml.graph import workflow_to_graph_file
from agent_yaml.web.db import AgentYamlDB, utc_now_iso
from agent_yaml.web.scheduler import DEFAULT_TIMEZONE, compute_next_run


class RunManager:
    """Coordinates background workflow executions and live event subscribers."""

    def __init__(self, db: AgentYamlDB, max_workers: int = 2):
        self.db = db
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._subscribers: Dict[int, List[queue.Queue]] = {}
        self._subscribers_lock = threading.RLock()
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None

    def import_workflow(self, path: str, name: Optional[str] = None):
        graph = workflow_to_graph_file(path)
        with open(path, "r", encoding="utf-8") as handle:
            yaml_text = handle.read()
        workflow_name = name or path.rsplit("/", 1)[-1]
        return self.db.create_workflow_version(workflow_name, path, yaml_text, graph)

    def start_run(
        self,
        workflow_version_id: int,
        trigger: str = "manual",
        dry_run: bool = False,
        variables: Optional[Dict[str, str]] = None,
    ):
        workflow = self.db.get_workflow_version(workflow_version_id)
        if not workflow:
            raise ValueError(f"workflow version not found: {workflow_version_id}")
        run = self.db.create_run(workflow_version_id, trigger=trigger, dry_run=dry_run, variables=variables)
        self.executor.submit(self._run_workflow, run["id"], workflow["path"], dry_run, variables or {})
        return run

    def _run_workflow(self, run_id: int, workflow_path: str, dry_run: bool, variables: Dict[str, str]):
        self.db.update_run(run_id, status="running", started_at=utc_now_iso())

        def event_sink(event):
            stored = self.db.record_event(run_id, event)
            self.publish(run_id, stored)

        try:
            exit_code = run_workflow(
                workflow_path,
                dry_run=dry_run,
                var_overrides=variables,
                event_sink=event_sink,
            )
            status = "success" if exit_code == 0 else "failed"
            self.db.update_run(
                run_id,
                status=status,
                exit_code=exit_code,
                finished_at=utc_now_iso(),
            )
            final_event = self.db.record_event(run_id, {
                "type": "run_finished",
                "timestamp": utc_now_iso(),
                "node_id": "workflow",
                "status": status,
                "message": None,
                "payload": {"exit_code": exit_code},
            })
            self.publish(run_id, final_event)
        except Exception as exc:
            self.db.update_run(
                run_id,
                status="failed",
                exit_code=1,
                error=str(exc),
                finished_at=utc_now_iso(),
            )
            final_event = self.db.record_event(run_id, {
                "type": "run_finished",
                "timestamp": utc_now_iso(),
                "node_id": "workflow",
                "status": "failed",
                "message": str(exc),
                "payload": {},
            })
            self.publish(run_id, final_event)

    def publish(self, run_id: int, event):
        with self._subscribers_lock:
            subscribers = list(self._subscribers.get(run_id, []))
        for subscriber in subscribers:
            subscriber.put(event)

    def subscribe(self, run_id: int):
        subscriber = queue.Queue()
        with self._subscribers_lock:
            self._subscribers.setdefault(run_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, run_id: int, subscriber):
        with self._subscribers_lock:
            subscribers = self._subscribers.get(run_id, [])
            if subscriber in subscribers:
                subscribers.remove(subscriber)
            if not subscribers and run_id in self._subscribers:
                self._subscribers.pop(run_id, None)

    def event_stream(self, run_id: int):
        last_id = None
        for event in self.db.list_events(run_id):
            last_id = event["id"]
            yield sse(event)

        subscriber = self.subscribe(run_id)
        try:
            while True:
                for event in self.db.list_events(run_id, after_id=last_id):
                    last_id = event["id"]
                    yield sse(event)
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                event_id = event.get("id")
                # Catch-up above may already have delivered this event (it was persisted
                # after we subscribed); never emit the same id twice.
                if event_id is not None and last_id is not None and event_id <= last_id:
                    continue
                if event_id is not None:
                    last_id = event_id
                yield sse(event)
                if event.get("type") == "run_finished":
                    return
        finally:
            self.unsubscribe(run_id, subscriber)

    def create_schedule(
        self,
        workflow_version_id: int,
        name: str,
        kind: str,
        expression: str,
        timezone_name: str = DEFAULT_TIMEZONE,
        active: bool = True,
    ):
        next_run_at = compute_next_run(kind, expression, timezone_name) if active else None
        return self.db.create_schedule(
            workflow_version_id,
            name,
            kind,
            expression,
            timezone_name,
            next_run_at,
            active=active,
        )

    def start_scheduler(self):
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self):
        self._scheduler_stop.set()

    def _scheduler_loop(self):
        while not self._scheduler_stop.is_set():
            self.tick_schedules()
            self._scheduler_stop.wait(5)

    def tick_schedules(self):
        now = datetime.now(timezone.utc)
        for schedule in self.db.list_schedules(active_only=True):
            next_run_at = schedule.get("next_run_at")
            if not next_run_at:
                continue
            due_at = datetime.fromisoformat(next_run_at)
            if due_at > now:
                continue
            self.start_run(schedule["workflow_version_id"], trigger=f"schedule:{schedule['id']}")
            next_due = compute_next_run(
                schedule["kind"],
                schedule["expression"],
                schedule.get("timezone") or DEFAULT_TIMEZONE,
                now=now,
            )
            self.db.update_schedule(
                schedule["id"],
                last_run_at=utc_now_iso(),
                next_run_at=next_due,
            )


def sse(event) -> str:
    return "data: " + json.dumps(event) + "\n\n"
