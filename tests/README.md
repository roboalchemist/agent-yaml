# agent-yaml tests

Three tiers, one rule: **the default run never touches a model.**

| Tier | Directory | The agent is… | Speed | Gated by |
|------|-----------|---------------|-------|----------|
| Unit | `tests/unit/` | mocked (`execute_single_task` patched; adapters are `Mock`) | < 1s | always runs |
| Integration | `tests/integration/` | a deterministic fake `opencode` that executes the prompt's ```` ```bash ```` block | ~4s | always runs |
| Live | `tests/live/` | real OpenCode v2 + a real model behind an OpenAI-compatible gateway | minutes | `pytest --live` |

```bash
pytest                                   # unit + integration (default)
pytest tests/unit                        # one tier
pytest tests/unit/test_loops.py -k csv   # one area
pytest --live tests/live -n 4            # real model (needs opencode + a gateway key)
```

The full default run is ~8s (1274 tests). A baseline before the restructure was 852 tests in 32s,
30 seconds of which was a single command-validator timeout test.

## Layout

```
tests/
├── conftest.py            # --live gating, fixtures_dir, mock_adapter, fake_opencode
├── support/
│   ├── helpers.py         # REPO_ROOT, EXAMPLES_DIR, bash_prompt(), file readers
│   ├── fake_opencode.py   # the fake agent: runs the prompt's ```bash block, logs argv/cwd
│   └── scenarios.py       # 13 workflow scenarios shared by integration AND live
├── unit/                  # one src module per file (incl. test_graph.py + test_web_runtime.py for the web runner)
├── integration/
│   ├── test_scenarios.py  # every support/scenarios.py scenario through the real CLI
│   ├── test_cli.py        # run_workflow() / main() behaviour
│   └── test_examples.py   # every examples/*.yaml and tasks/*.yaml dry-runs
├── live/
│   ├── conftest.py        # 1Password key, hermetic OpenCode home, preflight
│   └── test_scenarios.py  # the same 13 scenarios on the real model
└── fixtures/              # todos.md / todos-all-complete.md / todos-empty.md + empty-workflow.yaml
```

## Shared infrastructure

`tests/conftest.py`

- `--live` turns live tests on; without it every test in `tests/live/` is skipped by marker.
- `fixtures_dir` — path to `tests/fixtures`.
- `mock_adapter` — `Mock(spec=BaseAdapter)` returning `["agent", "--", "prompt"]`.
- `fake_opencode` — puts a fake `opencode` on `PATH` that runs the ```` ```bash ```` block found in the
  prompt, with the inherited cwd/env, and records each call (`{"argv", "cwd", "prompt"}`) to a log.
  Read it with `.calls()`.

`tests/support/scenarios.py` — each `Scenario` has a `build(workdir)` (returns a workflow dict with
absolute paths under `workdir`), a `check(workdir, rc, stderr)`, and the exact number of expected
agent calls. The integration tier runs them against the fake and asserts `agent_calls`; the live tier
runs the identical workflows against the real model through the gateway and only asserts the files
left behind. **Add a feature scenario here and both tiers gain coverage at once.**

## Unit tier conventions

- pytest functions and `@pytest.mark.parametrize` — no `unittest.TestCase`, no `setup_method`.
- `tmp_path` for every filesystem test; never write into the repo.
- Mock the agent, not the code under test: `patch("src.executor.execute_single_task")`. `loops.py`
  imports it lazily inside each `execute()`, so patching the executor attribute is enough.
- No sleeps longer than ~0.2s. A command validator with a delay must set `timeout: 1`.
- One `src` module per file (`src/loops.py` → `tests/unit/test_loops.py`, …).

## Integration tier conventions

- Go through the real entry point (`run_workflow`/`python -m src.cli`) so argparse, validation,
  includes, variables, loops and adapter wiring all run.
- Let the fake agent do the filesystem work; assert on the files and on `fake_opencode.calls()`.
- Every `examples/*.yaml` and `tasks/*.yaml` must dry-run clean. `tasks/base.yaml` (a copy-paste
  fragment with no `directory`) and `tasks/under-development-rfc.yaml` (WIP, invalid YAML at line 91)
  are skipped with reasons in `test_examples.py`.

## Live tier

`pytest --live` reads the gateway key **at run time** and proves the credential is the one used.
Export it directly, or let the harness read it from 1Password:

```bash
export GATEWAY_API_KEY=...                            # used as-is
# or: AGENT_YAML_LIVE_KEY_REF=op://Vault/Item/field   # read with `op read`
```

Every agent call runs in a fresh OpenCode home: `HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`,
`XDG_CONFIG_HOME` and `OPENCODE_CONFIG_DIR` point at a session temp dir whose `opencode.json`
defines only the gateway provider (`@ai-sdk/openai-compatible`, `AGENT_YAML_LIVE_BASE_URL`) and the
live model with `apiKey: "{env:GATEWAY_API_KEY}"`. Your stored credentials, plugins, skills and
default model never apply. `XDG_CACHE_HOME` stays real so OpenCode does not re-download providers.

A session-scoped preflight proves the key, the model, and tool calling in one shot: it asks the agent
to run `echo PONG > preflight.txt` with bash and fails readably if the file is missing. Each scenario
then runs `python -m src.cli run <workflow> --cli-agent opencode --model <live model>
--directory <tmp>` with `cwd=<tmp>`.

Overrides:

| Variable | Default |
|----------|---------|
| `AGENT_YAML_LIVE_PROVIDER` | `gateway` |
| `AGENT_YAML_LIVE_MODEL` | `model-name` (model id served by that provider) |
| `AGENT_YAML_LIVE_KEY_REF` | `op://Agents/GATEWAY_KEY/credential` (only when `GATEWAY_API_KEY` is unset) |
| `AGENT_YAML_LIVE_BASE_URL` | `http://127.0.0.1:4000/v1` |

Requirements: `opencode` v2.x on `PATH`, a reachable gateway, and a key (see above). The model talks to
the world through the prompt's ```` ```bash ```` block, which is why a real model can fail a scenario
that the fake passes (e.g. by mangling shell quoting). Those failures are real model-reliability
signal; fix them in the scenario (heredocs instead of heavy quoting) or make the assertion tolerant
(retry attempts `>= 2`).

## Fixtures policy

`tests/fixtures/` holds only files that more than one test reads. The old suite had 39 fixtures, 25 of
them orphaned; after the restructure 4 remain. Prefer inline `tmp_path` data — a file only becomes a
fixture when two tiers share it.

## Compatibility notes (deliberate, documented quirks)

- CSV `skip-header: true` without `columns` makes the first data row the fieldnames (row 2 is lost).
  `skip-header: true` **with** `columns` is the correct headerless-file combination. `columns` alone
  keeps the header line as a data row. These behaviours are asserted in `tests/unit/test_loops.py`.
- `checkpoint-file` supports template variables (`{{output-dir}}/state.json`) in all four loop types
  and is expanded to an absolute path before use.
- `tasks/` workflows are real user workflows and may use provider-specific agents; the integration
  tier only dry-runs them.
