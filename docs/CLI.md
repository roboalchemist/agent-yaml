# CLI reference

```
agent-yaml run <workflow.yaml> [options]
agent-yaml validate <workflow.yaml> [--cli-agent NAME]
agent-yaml serve [--host HOST] [--port PORT] [--db PATH]
```

## `run`

| Flag | Effect |
|------|--------|
| `--dry-run` | Validate and print the execution plan. No subprocess is started, though the agent CLI's availability is still checked |
| `--verbose`, `-v` | Progress logging to stderr |
| `--debug` | Print the full agent command per task and stream agent output |
| `--var key=value` | Override a template variable (repeatable, empty strings allowed) |
| `--env-file PATH` | Load a `.env` file (repeatable, later files override earlier ones) |
| `--directory DIR`, `-d` | Override the workflow's `directory` |
| `--model MODEL` | Model for every task, overriding the workflow and task config |
| `--resume` | Accepted for compatibility but currently a no-op. Resumption is per loop, driven by `resume: true` in the loop config |

Exit codes: `0` on success, `1` on any failure (parse, validation, or task failure).

A dry run prints the argv it would execute, so a wrong model or an option the CLI rejects shows up
before you spend tokens.

## `validate`

Parses the workflow, runs schema validation, and checks that the configured agent CLI is on `PATH`.
It never executes tasks. Exit codes: `0` success, `1` failure.

## `serve`

Starts the local visual runner (FastAPI plus server-sent events).

```bash
agent-yaml serve --host 127.0.0.1 --port 8765        # SQLite in ~/.agent-yaml by default
agent-yaml serve --db /tmp/agent-yaml.db --reload
```

It discovers workflows under `examples/` and `tasks/`, draws the stage graph on a WebGL2 canvas,
streams execution events over SSE, and persists runs plus interval or cron schedules in SQLite.
`AGENT_YAML_HOME` overrides the state directory and `--db` overrides the database file.

API surface (JSON unless noted):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/workflows/discover` | catalog entries (agent, directory, stage count, description) |
| `POST /api/workflows/import` | import a workflow path and project its graph |
| `GET /api/workflows` / `GET /api/workflows/{id}` | imported versions and their graph |
| `POST /api/workflows/{id}/runs` | start a run (`dry_run`, `variables`) |
| `GET /api/runs`, `/api/runs/{id}` | run history and detail |
| `GET /api/runs/{id}/events` | persisted callbacks |
| `GET /api/runs/{id}/state` | node states (status, attempts, timings) |
| `GET /api/runs/{id}/stream` | live SSE callbacks |
| `GET/POST/PATCH/DELETE /api/schedules` | interval and cron schedules |

## Environment precedence

Later wins:

```
system env  <  --env-file  <  workflow environment:  <  task env:  <  CLI --var
```

Values are interpolated, non-strings are stringified, and `os.environ` is never mutated.

## Error handling and retries

| Level | Setting | Values |
|-------|---------|--------|
| Workflow or task | `on-error` | `fail` (default), `continue`, `skip` |
| Loop item | `retry.on-failure` | `skip`, `retry`, `abort` |
| Validator | `retry.on-validation-failure` | `retry`, `fail`, `skip` |

`continue` logs the failure and proceeds. `skip` proceeds without counting it as a failure. In a
parallel group, `fail` stops scheduling new work, though anything already running finishes. Loops
report `status: success`, `partial`, or `failed` with `completed` and `failed` item lists.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `cli-agent '<name>' not available` | Install the CLI or pass `--cli-agent`. `validate` checks availability, `--dry-run` does not |
| Variable resolves to empty | Undefined variables interpolate to `""`. Check the name and that it is defined before use |
| Loop source missing | The file is produced by an earlier task. `--dry-run` tolerates it, a real run does not |
| Task never runs | Check `skip-if` first, then `when`. `when: ""` skips, and undefined variables are falsy |
| Agent ran but produced nothing | The agent's output is not parsed. Prompts must ask for files, and validators must check them |
| Timeout | Set `cli-agent-config.timeout` (seconds). It is per task |
| Live test fails with `invalid x-api-key` or a 401 | The gateway key is stale or revoked. Update the credential source and rerun |

## Known limitations

- Nested list tasks (`task: [{...}]` inside a task) are rejected by the validator even though
  `spec/YAML_SPEC.md` documents them. Use the mapping form.
- `agent-yaml run --resume` is a no-op. Resumption happens through each loop's `resume: true` plus
  `checkpoint-file`.
- `when` compares interpolated strings for `==` and `!=` unless both sides are native booleans or
  numbers.
- Adapter flags track the CLI versions listed in `docs/CONFIG_SURFACES.md`. Codex 0.153.4 removed
  `--full-auto`, `-a`, and `--search`; the adapter now emits `--dangerously-bypass-approvals-and-sandbox`,
  `-c approval_policy=…`, and `--enable web_search`.
- Claude 2.x removed `--allowed-mcp-server-names`; `mcp-servers` now warns and is ignored.
- MCP detection in `ensure.mcps` is a warning-only stub.
- Tasks named exactly `loop` or `prompt` collide with task meta fields.
- `execute_task_tree` labels top-level tasks with the literal name `task` in debug output.
- In a parallel group with `on-error: fail`, already-scheduled tasks still run before the workflow
  aborts. Cancellation is best-effort.
