# CLAUDE.md

Working notes for Claude Code in this repository. The canonical agent guide is
[AGENTS.md](AGENTS.md); user-facing documentation is [README.md](README.md) and the test-tier guide is
[tests/README.md](tests/README.md). Keep this file short — it is an orientation, not a spec.

## What this is

`agent-yaml` runs declarative YAML workflows by spawning an AI coding-agent CLI once per task
(`opencode`, `claude`, `gemini`, `qwen`, `codex`). The Python package is literally named `src` — do not
rename it.

```bash
pip install -e ".[dev]"
pytest -q                        # unit + integration, ~8s, no model/network
pytest --live tests/live -n 4    # real OpenCode v2 + gateway/model-name
ruff check src tests
```

## Architecture in one screen

```
cli.py ─ parser.py ─ validator.py ─ includes.py ─ variables.py
   └─ executor.py ─ adapters/*.py ─ agent CLI (one subprocess per task)
        └─ loops.py (todo/csv/glob/json/jsonl, workers, checkpoints)
        └─ task_validators.py, skip_conditions.py, when_conditions.py, ensure.py
   └─ events.py ─ web/ (agent-yaml serve: FastAPI + SSE visual runner)
```

`agent-yaml serve` runs the interface runner (`src/web/`: FastAPI app, run manager, SQLite store,
scheduler, and `static/webgl.js` — a WebGL2 stage-graph renderer with a DOM label layer).
`src/graph.py` builds the node graph, `src/events.py` emits callbacks that the UI streams over SSE
and renders in the trace panel. Keep event `node_id`s equal to graph node ids; do not remove the
emissions in `src/cli.py` / `src/executor.py` / `src/loops.py`.

- **Task tree**: a list under `task:` is sequential; mapping keys inside a task run in parallel
  (`ThreadPoolExecutor`). Task meta fields: `prompt`, `task`, `loop`, `include`, `on-error`,
  `directory`, `cli-agent-config`, `validate`, `retry`, `skip-if`, `env`, `when`.
- **Files, not stdout**: the agent's output is never parsed. Prompts ask for files; validators and
  tests assert on files.
- **Variables**: reserved (`{{directory}}`, `{{gitroot}}`, `{{datetime}}`, `{{user}}`, `{{env.NAME}}`)
  then user variables in dependency order; `interpolate_variables()` in `src/utils.py` does
  dot-notation replacement. Undefined → `""`.
- **Env precedence**: system < `--env-file` < workflow `environment:` < task `env:` < `--var`.
- **Ordering**: `skip-if` → `when` → task execution → validators (with `retry.on-validation-failure`).
- **Loops**: shared `workers`, `retry`, `checkpoint-file` (template-expanded), `resume`,
  `directory-pool`, `git-worktrees`. CSV `skip-header`/`columns` quirks are intentional and asserted.
- **OpenCode adapter**: `opencode run [--standalone] [--auto] [--model provider/model] ... -- <prompt>`.
  Always `--` before the prompt; use `--standalone` (the background service may lack the model).

## Testing map

| Tier | Where | Agent |
|------|-------|-------|
| unit | `tests/unit/test_<module>.py` | mocked (`patch("src.executor.execute_single_task")`) |
| integration | `tests/integration/` | fake `opencode` (`tests/support/fake_opencode.py`) running the prompt's `bash` block |
| live | `tests/live/` (`--live`) | real OpenCode v2 + `gateway/model-name`, key from 1Password |

Add user-visible behaviour as a scenario in `tests/support/scenarios.py`; both integration and live
tiers run it. Conventions: plain pytest, `parametrize`, `tmp_path`, no `unittest.TestCase`, no long
sleeps. Live runs are hermetic (isolated HOME/XDG/OPENCODE_CONFIG_DIR) and read
`op://Agents/GATEWAY_KEY/credential` at run time.

## Things that will bite

- Nested list tasks (`task: [...]` inside a task) are rejected by the validator — use the mapping form.
- `run --resume` is a no-op; resume per loop with `resume: true` + `checkpoint-file`.
- Tasks named exactly `loop` or `prompt` collide with meta fields.
- Codex adapter flags and Claude's `--allowed-mcp-server-names` are rejected by current CLIs.
- `tasks/under-development-rfc.yaml` is intentionally broken WIP; `tests/integration/test_examples.py`
  skips it (and `tasks/base.yaml`, a fragment without `directory`).
- Examples and `tasks/*.yaml` are dry-run on every `pytest`; a broken workflow fails the suite.

## Where the truth lives

Behaviour: `src/`. Format: `spec/YAML_SPEC.md`, `spec/ADAPTER_SPEC.md`, `spec/PROJECT_SPECS.md`.
Usage: `README.md`. Tests: `tests/README.md`. Examples: `examples/` and `examples/README.md`.
