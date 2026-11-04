"""SQLite persistence for the local web runner."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def default_home() -> str:
    return os.path.abspath(
        os.path.expanduser(os.environ.get("AGENT_YAML_HOME", "~/.agent-yaml"))
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentYamlDB:
    """Small SQLite wrapper for workflow versions, runs, events, and schedules."""

    def __init__(self, db_path: Optional[str] = None):
        self.home = default_home()
        if db_path:
            self.db_path = os.path.abspath(os.path.expanduser(db_path))
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        else:
            os.makedirs(self.home, exist_ok=True)
            self.db_path = os.path.join(self.home, "agent-yaml.sqlite3")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self):
        with self._lock:
            self._conn.executescript(
                """
                create table if not exists workflow_versions (
                    id integer primary key autoincrement,
                    name text not null,
                    path text not null,
                    yaml_text text not null,
                    graph_json text not null,
                    created_at text not null
                );

                create table if not exists runs (
                    id integer primary key autoincrement,
                    workflow_version_id integer not null references workflow_versions(id),
                    status text not null,
                    trigger text not null,
                    dry_run integer not null default 0,
                    variables_json text not null default '{}',
                    started_at text,
                    finished_at text,
                    exit_code integer,
                    error text
                );

                create table if not exists run_events (
                    id integer primary key autoincrement,
                    run_id integer not null references runs(id),
                    ts text not null,
                    event_type text not null,
                    node_id text,
                    status text,
                    message text,
                    payload_json text not null default '{}'
                );

                create table if not exists node_states (
                    run_id integer not null references runs(id),
                    node_id text not null,
                    status text not null,
                    started_at text,
                    finished_at text,
                    attempts integer not null default 0,
                    last_message text,
                    payload_json text not null default '{}',
                    primary key (run_id, node_id)
                );

                create table if not exists schedules (
                    id integer primary key autoincrement,
                    workflow_version_id integer not null references workflow_versions(id),
                    name text not null,
                    kind text not null,
                    expression text not null,
                    timezone text not null default 'America/Los_Angeles',
                    active integer not null default 1,
                    next_run_at text,
                    last_run_at text,
                    created_at text not null,
                    updated_at text not null
                );
                """
            )
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    def create_workflow_version(self, name: str, path: str, yaml_text: str, graph: Dict[str, Any]):
        with self._lock:
            cursor = self._conn.execute(
                """
                insert into workflow_versions (name, path, yaml_text, graph_json, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (name, os.path.abspath(os.path.expanduser(path)), yaml_text, json.dumps(graph), utc_now_iso()),
            )
            self._conn.commit()
            return self.get_workflow_version(cursor.lastrowid)

    def list_workflow_versions(self) -> List[Dict[str, Any]]:
        return self._rows(
            """
            select id, name, path, created_at from workflow_versions
            order by created_at desc, id desc
            """
        )

    def get_workflow_version(self, workflow_version_id: int) -> Optional[Dict[str, Any]]:
        row = self._row("select * from workflow_versions where id = ?", (workflow_version_id,))
        if not row:
            return None
        row["graph"] = json.loads(row.pop("graph_json"))
        return row

    def create_run(
        self,
        workflow_version_id: int,
        trigger: str = "manual",
        dry_run: bool = False,
        variables: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            cursor = self._conn.execute(
                """
                insert into runs
                  (workflow_version_id, status, trigger, dry_run, variables_json, started_at)
                values (?, 'queued', ?, ?, ?, ?)
                """,
                (
                    workflow_version_id,
                    trigger,
                    1 if dry_run else 0,
                    json.dumps(variables or {}),
                    utc_now_iso(),
                ),
            )
            self._conn.commit()
            return self.get_run(cursor.lastrowid)

    def update_run(self, run_id: int, **fields):
        if not fields:
            return
        allowed = {"status", "finished_at", "exit_code", "error", "started_at"}
        assignments = []
        values = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            values.append(value)
        if not assignments:
            return
        values.append(run_id)
        with self._lock:
            self._conn.execute(
                f"update runs set {', '.join(assignments)} where id = ?",
                tuple(values),
            )
            self._conn.commit()

    def list_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        runs = self._rows(
            """
            select r.*, w.name as workflow_name, w.path as workflow_path
            from runs r join workflow_versions w on w.id = r.workflow_version_id
            order by r.id desc
            limit ?
            """,
            (limit,),
        )
        for run in runs:
            self._decode_run(run)
        return runs

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        run = self._row(
            """
            select r.*, w.name as workflow_name, w.path as workflow_path
            from runs r join workflow_versions w on w.id = r.workflow_version_id
            where r.id = ?
            """,
            (run_id,),
        )
        if run:
            self._decode_run(run)
            run["node_states"] = self.list_node_states(run_id)
        return run

    def record_event(self, run_id: int, event: Dict[str, Any]) -> Dict[str, Any]:
        event_type = event.get("type", "event")
        node_id = event.get("node_id")
        status = event.get("status")
        message = event.get("message")
        ts = event.get("timestamp") or utc_now_iso()
        payload = {
            key: value
            for key, value in event.items()
            if key not in {"type", "node_id", "status", "message", "timestamp"}
        }
        with self._lock:
            cursor = self._conn.execute(
                """
                insert into run_events
                  (run_id, ts, event_type, node_id, status, message, payload_json)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, ts, event_type, node_id, status, message, json.dumps(payload)),
            )
            if node_id and status:
                existing = self._row(
                    "select attempts from node_states where run_id = ? and node_id = ?",
                    (run_id, node_id),
                )
                attempts = int(existing["attempts"]) if existing else 0
                if event_type in {"task_started", "task_retrying"}:
                    attempts += 1
                started_at = ts if event_type.endswith("_started") else None
                finished_at = ts if status in {"success", "failed", "skipped", "cancelled"} else None
                self._conn.execute(
                    """
                    insert into node_states
                      (run_id, node_id, status, started_at, finished_at, attempts, last_message, payload_json)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(run_id, node_id) do update set
                      status = excluded.status,
                      started_at = coalesce(node_states.started_at, excluded.started_at),
                      finished_at = coalesce(excluded.finished_at, node_states.finished_at),
                      attempts = excluded.attempts,
                      last_message = excluded.last_message,
                      payload_json = excluded.payload_json
                    """,
                    (
                        run_id,
                        node_id,
                        status,
                        started_at,
                        finished_at,
                        attempts,
                        message,
                        json.dumps(payload),
                    ),
                )
            self._conn.commit()
            stored = self.get_event(cursor.lastrowid)
            return stored

    def get_event(self, event_id: int) -> Dict[str, Any]:
        event = self._row("select * from run_events where id = ?", (event_id,))
        self._decode_event(event)
        return event

    def list_events(self, run_id: int, after_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if after_id is None:
            events = self._rows("select * from run_events where run_id = ? order by id", (run_id,))
        else:
            events = self._rows(
                "select * from run_events where run_id = ? and id > ? order by id",
                (run_id, after_id),
            )
        for event in events:
            self._decode_event(event)
        return events

    def list_node_states(self, run_id: int) -> List[Dict[str, Any]]:
        states = self._rows(
            "select * from node_states where run_id = ? order by node_id",
            (run_id,),
        )
        for state in states:
            state["payload"] = json.loads(state.pop("payload_json"))
        return states

    def create_schedule(
        self,
        workflow_version_id: int,
        name: str,
        kind: str,
        expression: str,
        timezone_name: str,
        next_run_at: Optional[str],
        active: bool = True,
    ) -> Dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            cursor = self._conn.execute(
                """
                insert into schedules
                  (workflow_version_id, name, kind, expression, timezone, active, next_run_at, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_version_id,
                    name,
                    kind,
                    expression,
                    timezone_name,
                    1 if active else 0,
                    next_run_at,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return self.get_schedule(cursor.lastrowid)

    def list_schedules(self, active_only: bool = False) -> List[Dict[str, Any]]:
        if active_only:
            schedules = self._rows(
                """
                select s.*, w.name as workflow_name
                from schedules s join workflow_versions w on w.id = s.workflow_version_id
                where s.active = 1
                order by s.next_run_at is null, s.next_run_at
                """
            )
        else:
            schedules = self._rows(
                """
                select s.*, w.name as workflow_name
                from schedules s join workflow_versions w on w.id = s.workflow_version_id
                order by s.id desc
                """
            )
        for schedule in schedules:
            schedule["active"] = bool(schedule["active"])
        return schedules

    def get_schedule(self, schedule_id: int) -> Optional[Dict[str, Any]]:
        schedule = self._row(
            """
            select s.*, w.name as workflow_name
            from schedules s join workflow_versions w on w.id = s.workflow_version_id
            where s.id = ?
            """,
            (schedule_id,),
        )
        if schedule:
            schedule["active"] = bool(schedule["active"])
        return schedule

    def update_schedule(self, schedule_id: int, **fields):
        allowed = {
            "name",
            "kind",
            "expression",
            "timezone",
            "active",
            "next_run_at",
            "last_run_at",
        }
        assignments = []
        values = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            if key == "active":
                value = 1 if value else 0
            values.append(value)
        assignments.append("updated_at = ?")
        values.append(utc_now_iso())
        values.append(schedule_id)
        with self._lock:
            self._conn.execute(
                f"update schedules set {', '.join(assignments)} where id = ?",
                tuple(values),
            )
            self._conn.commit()

    def delete_schedule(self, schedule_id: int):
        with self._lock:
            self._conn.execute("delete from schedules where id = ?", (schedule_id,))
            self._conn.commit()

    def _row(self, query: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            row = cursor.fetchone()
            return dict(row) if row else None

    def _rows(self, query: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

    def _decode_run(self, run: Dict[str, Any]):
        run["dry_run"] = bool(run["dry_run"])
        run["variables"] = json.loads(run.pop("variables_json"))

    def _decode_event(self, event: Dict[str, Any]):
        event["payload"] = json.loads(event.pop("payload_json"))
        event["type"] = event.pop("event_type")
