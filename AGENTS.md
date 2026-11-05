# AGENTS.md

Agent instructions for `agent-yaml`: a Python CLI that runs declarative YAML workflows by spawning an
AI coding-agent CLI (`opencode`, `claude`, `gemini`, `qwen`, `codex`) once per task.

The import package is `agent_yaml` (`from agent_yaml.executor import execute_single_task`). Do not
rename it.

## Commands

```bash
pip install -e ".[dev]"          # editable install; `agent-yaml` on PATH
pytest -q                        # unit + integration, ~8s, no model, no network
pytest tests/unit -q             # one tier
pytest --live tests/live -n 4    # real OpenCode v2 + gateway/model-name
ruff check src tests             # F/E9 must be clean
agent-yaml validate <wf>.yaml    # parse + schema + CLI availability, no agent calls
agent-yaml run <wf>.yaml --dry-run
agent-yaml run <wf>.yaml --debug # prints exact argv, streams agent output
agent-yaml serve                 # local visual runner (FastAPI + SSE) at 127.0.0.1:8765
```

Live tests need `opencode` v2.x, `op` signed in, and
`op read "op://Agents/GATEWAY_KEY/credential"` to return a valid gateway key. The harness
injects that key as `GATEWAY_API_KEY` into a hermetic OpenCode home (isolated
HOME/XDG/OPENCODE_CONFIG_DIR) that defines only the model gateway and `gateway/model-name`,
so a stored credential is never used. A preflight writes `preflight.txt` through the bash tool, proving
key, model, and tool calling. If the key is rejected (401 / `invalid x-api-key`), the item itself is
stale — do not work around it by exporting a different key.

## Hard rules

1. **Default tests never call a model.** Unit tests mock `execute_single_task`; integration tests use
   the fake `opencode` in `tests/support/fake_opencode.py`. Keep it that way.
2. **Every `examples/*.yaml` and `tasks/*.yaml` must dry-run clean**, enforced by
   `tests/integration/test_examples.py`. The only skips are `tasks/base.yaml` (fragment without
   `directory`) and `tasks/under-development-rfc.yaml` (WIP, invalid YAML) — do not "fix" the WIP file.
3. **Agents communicate through files.** Agent stdout is never parsed. Prompts must ask for files, and
   tests must assert on those files.
4. **Add a feature scenario to `tests/support/scenarios.py`** when adding user-visible behaviour — the
   integration tier (fake agent) and live tier (real model) both run the same scenarios.
5. Test style: plain pytest functions, `@pytest.mark.parametrize`, `tmp_path`, no `unittest.TestCase`,
   no sleeps over ~0.2s. One `agent_yaml` module per `tests/unit/test_<module>.py`.
6. Only put a file in `tests/fixtures/` when two or more tests read it; otherwise generate it in
   `tmp_path`. The suite keeps 4 fixtures on purpose.

## Layout

| Path | What lives there |
|------|------------------|
| `agent_yaml/cli.py` | argparse, `run_workflow()`, dry-run plan, env-file loading, task-tree walk |
| `agent_yaml/parser.py` | YAML parse (`safe_load`) |
| `agent_yaml/validator.py` | schema validation; `VALID_CLI_AGENTS` |
| `agent_yaml/variables.py`, `agent_yaml/utils.py` | reserved/user variables, `{{var}}` interpolation, expressions |
| `agent_yaml/includes.py` | inline + file includes, cycle detection |
| `agent_yaml/executor.py` | single-task subprocess, timeout, debug streaming, env merge |
| `agent_yaml/loops.py` | todo-list/CSV/glob/JSON/JSONL loops, workers, checkpoints |
| `agent_yaml/task_validators.py` | post-task validators |
| `agent_yaml/skip_conditions.py`, `agent_yaml/when_conditions.py` | pre-task gating |
| `agent_yaml/ensure.py` | pre-flight tool checks (MCPs are a warning-only stub) |
| `agent_yaml/events.py`, `agent_yaml/graph.py` | event emission + task-tree graph for the web runner |
| `agent_yaml/web/` | FastAPI interface runner: app, SSE, SQLite store, scheduler, `static/webgl.js` stage-graph renderer, trace UI (`agent-yaml serve`) |
| `agent_yaml/adapters/` | `base.py` + `opencode.py`, `claude.py`, `gemini.py`, `qwen.py`, `codex.py` |
| `tests/` | tiers — see `tests/README.md` |
| `examples/`, `tasks/` | user-facing workflows (dry-run by tests) |
| `spec/` | authoritative specs (`YAML_SPEC.md`, `PROJECT_SPECS.md`, `ADAPTER_SPEC.md`) |

## Execution model

- A **list** under `task:` is sequential; a **mapping** inside a task runs its keys in parallel
  (`ThreadPoolExecutor`).
- Task meta fields: `prompt`, `task`, `loop`, `include`, `on-error`, `directory`, `cli-agent-config`,
  `validate`, `retry`, `skip-if`, `env`, `when`.
- Precedence for env: system < `--env-file` < workflow `environment:` < task `env:` < `--var`.
- Reserved variables (`{{directory}}`, `{{gitroot}}`, `{{datetime}}`, `{{user}}`, `{{env.NAME}}`) cannot
  be overridden. Undefined variables interpolate to `""`.
- Post-task order: task exits 0 → validators run → on validator failure `retry.on-validation-failure`
  (`retry`/`fail`/`skip`) applies. `skip-if` runs first, then `when`.

## OpenCode adapter (v2)

- Invocation: `opencode run [--standalone|--server URL] [--auto] [--model provider/model] ... -- <prompt>`.
- Use `--standalone` for tests/CI: the background service may not expose the model you need.
- The prompt must come after `--`; a prompt beginning with `-` otherwise prints help and exits 0.
- `skip-confirmations: true` → `--auto`; `additional-dirs` is ignored with a warning (configure dirs in
  `opencode.json`); `output-format: json` → `--format json`; `stream-json` is ignored with a warning.
- Prefer full `provider/model` ids (e.g. `gateway/model-name`); a few short Anthropic
  aliases (`haiku-5.5`, `sonnet-5.5`, `opus-5.5`) are also translated.

## Interface runner (`agent-yaml serve`)

- Catalog: `/api/workflows/discover` lists every `examples/*.yaml` and `tasks/*.yaml` with agent,
  directory, stage count and description; selecting one imports it and renders the graph.
- The stage graph is WebGL2 (`agent_yaml/web/static/webgl.js`). Keep node ids in events equal to graph node
  ids or the highlight/focus breaks. DOM/SVG fallback exists for browsers without WebGL2.
- Callbacks are emitted through `agent_yaml/events.py` and streamed over SSE (`/api/runs/{id}/stream`).
  Event vocabulary: `workflow_*`, `loop_*` (+ per-item `loop_item_*`), `task_*`, `validators_*`,
  `run_finished`. Never emit the same id twice in the stream (runtime dedupes by id).
- Nodes are colored from event `status`; `task_started` also increments the attempt counter.
- Trace rows support filters, follow-scroll, follow-stage, and click-to-focus; loop rows carry
  `index`, `total`, `item_id` from the loop callbacks.

## Loop gotchas (verified by unit tests)

- CSV: `skip-header: true` **with** `columns` skips the header and keeps all data rows. `skip-header`
  without `columns` makes the first data row the fieldnames. `columns` without `skip-header` keeps the
  header as data row 1. These are documented behaviours — assert them, don't "fix" them silently.
- `checkpoint-file` supports `{{variables}}` in all four loop types and is expanded to an absolute path.
- Parallel loops complete in nondeterministic order — compare sets/sorted lists.
- `directory-pool` must point at existing directories and sets each task's cwd; it cannot be combined
  with `git-worktrees`. Worktree tests must isolate git config and clean up worktrees.

## Known limitations (do not rediscover)

- Nested list tasks (`task: [...]` inside a task) are rejected by the validator though the spec
  documents them; use the mapping form.
- `run --resume` is a no-op; resumption is per-loop `resume: true` + `checkpoint-file`.
- `when` interpolates variables natively (booleans stay booleans) — `when: "not {{force}}"` works.
- Codex adapter flags (`--full-auto`, `-a`, `--search`) are rejected by codex-cli 0.153.4; the Claude
  adapter emits `--allowed-mcp-server-names`, which current `claude` rejects.
- Tasks named exactly `loop` or `prompt` collide with meta fields.

## Docs to keep in sync

`README.md` (how the system works), `tests/README.md` (tiers, conventions, live setup),
`examples/README.md` (per-example notes), `spec/` (authoritative reference). Update them when behaviour
changes; do not duplicate the spec into the README.
