# Interface Runner (`agent-yaml serve`)

`agent-yaml serve` starts a local FastAPI app plus a WebGL stage graph so you can browse workflows,
launch runs, watch tasks light up as they execute, and schedule runs. This page documents the HTTP
and SSE contract, the event vocabulary, and the SQLite store — the pieces you need to integrate with
or extend the runner.

## Start It

```bash
agent-yaml serve                       # http://127.0.0.1:8765
agent-yaml serve --port 9000 --reload  # different port, autoreload for development
agent-yaml serve --db /tmp/runs.sqlite # override the database file
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8765` | Port |
| `--db` | `$AGENT_YAML_HOME/runs.sqlite` (`~/.agent-yaml`) | SQLite file |
| `--reload` | off | uvicorn autoreload |

Workflow discovery walks `examples/` and `tasks/` **relative to the server's cwd**, so start it from
the repo root.

---

## What the UI Does

1. **Catalog** — `GET /api/workflows/discover` lists every `examples/*.yaml` and `tasks/*.yaml` with
   agent, workflow directory, stage count and description (from the workflow's `description` or
   `name`). Files that are not YAML mappings are skipped with a `[discover] skipping …` log line.
2. **Import** — selecting one imports it into `workflow_versions`, snapshotting the YAML text and the
   computed graph.
3. **Graph** — the stage graph is rendered with WebGL2 (`agent_yaml/web/static/webgl.js`); a DOM/SVG
   fallback exists for browsers without WebGL2.
4. **Run** — starting a run executes the workflow in a background thread with an event sink attached.
5. **Trace** — events stream over SSE and appear as rows with timestamp, node, status and message;
   rows carry `index`/`total`/`item_id` for loop items. The trace supports filters, follow-scroll,
   follow-stage, and click-to-focus on a node.

---

## HTTP API

All endpoints return JSON except the SSE stream.

| Method | Path | Body / query | Returns |
|--------|------|--------------|---------|
| `GET` | `/` | — | The UI (`static/index.html`) |
| `GET` | `/api/health` | — | `{"status": "ok"}` |
| `GET` | `/api/workflows/discover` | — | Catalog entries (`id`, `relative_path`, `absolute_path`, `directory`, `name`, `cli_agent`, `workflow_directory`, `stage_count`, `description`) |
| `POST` | `/api/workflows/import` | `{"path": "...", "name": "..."}` | Created workflow version (404 if the path is missing, 400 on parse failure) |
| `GET` | `/api/workflows` | — | Imported workflow versions |
| `GET` | `/api/workflows/{id}` | — | One version, including `graph_json` |
| `POST` | `/api/workflows/{id}/runs` | `{"dry_run": false, "variables": {"k": "v"}}` | Created run (executes immediately, `trigger: "manual"`) |
| `GET` | `/api/runs` | `?limit=100` | Run history, newest first |
| `GET` | `/api/runs/{id}` | — | Run detail (`status`, `trigger`, `exit_code`, `variables`, timings) |
| `GET` | `/api/runs/{id}/events` | — | Persisted events in id order |
| `GET` | `/api/runs/{id}/state` | — | `{"run": …, "nodes": [{node_id, status, attempts, started_at, finished_at, …}]}` |
| `GET` | `/api/runs/{id}/stream` | — | SSE stream (see below) |
| `GET` | `/api/schedules` | — | All schedules |
| `POST` | `/api/schedules` | `{workflow_version_id, name, kind, expression, timezone?, active?}` | Created schedule |
| `PATCH` | `/api/schedules/{id}` | any subset of the create fields | Updated schedule (recomputes `next_run_at`) |
| `DELETE` | `/api/schedules/{id}` | — | `{"status": "deleted"}` |

`variables` in `POST /runs` are the same string overrides as `--var`, so a run started from the UI
can parameterise the workflow.

### Driving it from the shell

```bash
curl -s localhost:8765/api/workflows/discover | jq '.[0]'
curl -s -X POST localhost:8765/api/workflows/import \
  -H 'content-type: application/json' \
  -d '{"path": "examples/03-parallel.yaml"}'
curl -s -X POST localhost:8765/api/workflows/1/runs \
  -H 'content-type: application/json' \
  -d '{"dry_run": true, "variables": {"environment": "staging"}}'
curl -sN localhost:8765/api/runs/1/stream     # live events until run_finished
```

---

## SSE Contract

`GET /api/runs/{id}/stream` is `text/event-stream`:

- **Replay first.** Every persisted event is sent in id order, so reconnecting clients get full
  history.
- **Then live.** New events are pushed as they are recorded.
- **Keepalive.** `: keepalive\n\n` every 15 seconds of silence keeps proxies from closing the stream.
- **No duplicates.** If catch-up already delivered an event id, the live path skips it
  (`agent_yaml/web/runtime.py:136`). Consumers may treat the stream as a strictly increasing id sequence.
- **Termination.** The server closes the stream after `run_finished`.
- Wire format is one JSON object per frame:

```
data: {"id": 42, "type": "task_completed", "timestamp": "2026-02-02T20:41:03.117+00:00", "node_id": "1.review", "status": "success", "message": null, "payload": {}}
```

Every event has `id`, `type`, `timestamp`, `node_id`, `status`, `message`, and `payload`. Persistence
splits the event: `type`, `node_id`, `status`, `message`, `timestamp` become columns and everything
else lands in `payload` (`agent_yaml/web/db.py:210`).

---

## Event Vocabulary

| Event | Emitted when | Extra fields |
|-------|--------------|--------------|
| `workflow_started` | run begins | — |
| `loop_started` | a loop begins | loop metadata |
| `loop_item_started` | one iteration begins | `loop_type`, `index`, `total`, `item_id` |
| `loop_item_completed` | iteration succeeded | same |
| `loop_item_failed` | iteration failed | same, plus `message` |
| `task_started` | agent invocation begins | `attempt` |
| `task_completed` | task and its validators succeeded | `attempt`, `exit_code` |
| `task_failed` | task or its validation failed | `attempt`, `exit_code`, `payload.validation` |
| `task_skipped` | `skip-if`/`when` said no | `payload.skip_condition` or `payload.when_condition` |
| `task_retrying` | validation failure caused a retry | `attempt`, `message` |
| `validators_started` | validators begin | `total` |
| `validators_completed` | validators finished | `payload` with per-validator results |
| `run_finished` | run ended (always last) | `payload.exit_code`, `node_id: "workflow"` |

Event names are never invented ad hoc: `agent_yaml/events.py` is a no-op without a sink, and the runner is
the only component that supplies one.

### Node identity invariant

Graph node ids are **dot-joined task paths**, and events must carry exactly those ids or the graph
highlight/focus breaks (`agent_yaml/graph.py:224`). For `examples/03-parallel.yaml`:

```json
{"id": "0", "type": "workflow", "label": "Workflow", "status": "idle", "data": {…}}
{"id": "0.setup", "type": "task", "label": "setup", "status": "idle"}
```

Edges are labelled `contains` (parent → child) or `then` (sequential sibling → sibling), and the
graph payload is `{version, source_path, metadata, nodes, edges, entry_node_ids, exit_node_ids}`.

`node_states` is derived, not authoritative: `task_started` and `task_retrying` increment
`attempts`, `*_started` sets `started_at` once, and a terminal status (`success`, `failed`,
`skipped`, `cancelled`) sets `finished_at`.

---

## Persistence

One SQLite file (`$AGENT_YAML_HOME/runs.sqlite`), five tables, created with
`create table if not exists` on startup (`agent_yaml/web/db.py:39`):

| Table | Holds |
|-------|-------|
| `workflow_versions` | `name`, `path`, `yaml_text`, `graph_json`, `created_at` — an import snapshot |
| `runs` | `workflow_version_id`, `status`, `trigger`, `dry_run`, `variables_json`, timings, `exit_code`, `error` |
| `run_events` | `ts`, `event_type`, `node_id`, `status`, `message`, `payload_json` |
| `node_states` | Per `(run_id, node_id)`: `status`, `started_at`, `finished_at`, `attempts`, `last_message`, `payload_json` |
| `schedules` | `workflow_version_id`, `name`, `kind`, `expression`, `timezone`, `active`, `next_run_at`, `last_run_at` |

There are no versioned migrations — schema changes require care with existing databases. `trigger`
is `manual` or `schedule:<id>`.

---

## Scheduler

| `kind` | `expression` | Examples |
|--------|--------------|----------|
| `interval` | seconds, or `<n>[smhd]` | `90`, `5m`, `2h`, `1d` |
| `cron` | five fields: minute hour day month weekday | `0 9 * * 1-5`, `*/15 * * * *` |

- Cron fields support `*`, `n`, `a-b`, comma lists, and `*/n` steps; weekday `0` is Sunday.
- `timezone` defaults to `America/Los_Angeles` and only affects cron evaluation; `next_run_at` is
  stored in UTC.
- The scheduler ticks every 5 seconds, launches due runs with `trigger: schedule:<id>`, then computes
  the next occurrence (`agent_yaml/web/runtime.py:183`).
- `active: false` pauses a schedule (`next_run_at` is null).

---

## Limitations

1. **Local, single-user, no auth.** Every endpoint is unauthenticated and binds to `127.0.0.1` by
   default — do not expose it.
2. **Two concurrent runs** — the run manager thread pool is fixed at `max_workers=2`
   (`agent_yaml/web/runtime.py:21`). Extra runs queue.
3. **Discovery is cwd-relative** and only walks `examples/` and `tasks/`; a workflow elsewhere must be
   imported by absolute path.
4. **No `Last-Event-ID` resume.** Reconnecting replays from the beginning of the run, deduped by id.
5. **No cancellation endpoint.** Stopping a run means killing the server process.
6. **`yaml_text` snapshots are what execute**, not the file on disk — re-import after editing a
   workflow, or you are running the old version.
7. **The graph and the trace are separate contracts**: the graph comes from parsing the YAML at
   import time, the trace from runtime events. A workflow edited after import can have mismatched
   node ids between the two.

---

## Best Practices

1. **Re-import after every edit** — snapshots make this explicit, and stale imports are the most
   common "my change did nothing" cause.
2. **Watch a `--dry-run` first** when exploring a workflow in the UI; validators and agent calls are
   skipped.
3. **Filter the trace by `loop_item_*`** when a parallel loop is producing hundreds of rows.
4. **Keep `AGENT_YAML_HOME` on fast local disk** if you want run history beyond a single debugging
   session; it grows per event.
5. **Use the API, not the UI, in automation** — the SSE stream is the supported way to observe a run.

---

Source of truth: `agent_yaml/web/app.py` (routes, discovery), `agent_yaml/web/runtime.py` (run manager, SSE,
scheduler loop), `agent_yaml/web/db.py` (schema, event persistence), `agent_yaml/web/scheduler.py` (interval/cron),
`agent_yaml/events.py`, `agent_yaml/graph.py`, `agent_yaml/web/static/webgl.js`.
