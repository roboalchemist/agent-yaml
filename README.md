# agent-yaml

Write out your workflows in yaml and then run them under a harness of your choice.

## Why it exists

Each model and framework provider is trying to provide a way to interact with their harness, without providing what is usually needed: a definable, repeatable flow-chart style workflow to accomplish some repeated task. 

The yaml contains the prompts, where each loop gets its items, and the checks a step has to pass
before the next one starts. Run it again next month in the latest harness/model of the day and run the same workflow.

agent-yaml lets one define their workflows irregardless of the harness or model of the day, by breaking down what most boring workflows tend to be (or could most easily be) comprised of:
- a working directory
- prompts made with templates
- looping over something
- validating checks
- composable templating of the above 

Each step is one subprocess call, with contracts between steps being files on the disk. 

Model output stays opaque and is never parsed.
If you want to parse it, write it to a file and parse that.
Validators run against written files to form checkpoints. 

## Install

No PyPI release yet. Install from the repository:

```bash
pip install "git+https://github.com/roboalchemist/agent-yaml.git"
agent-yaml --help
```

Python 3.8+, tested on 3.9, 3.11 and 3.12, plus at least one supported agent CLI on `PATH`
(`opencode`, `claude`, `codex`, `pi`, `vtcode`, or `antigravity`).

## Quick start

```yaml
# hello.yaml
directory: /tmp/hello
cli-agent: opencode
cli-agent-config:
  skip-confirmations: true
  model: provider/model-name

task:
  - write-file:
      prompt: "Create hello.txt containing exactly: hello from agent-yaml"
```

```bash
mkdir -p /tmp/hello
agent-yaml validate hello.yaml        # parse and schema check, no agent calls
agent-yaml run hello.yaml --dry-run   # print the exact command that would run
agent-yaml run hello.yaml             # run it
```

A dry run for that file prints the command it would execute, including the translated flags, so you
can spot a wrong model or a rejected option before spending tokens:

```
[DRY RUN] Task 'write-file' would execute:
  Command: opencode run --standalone --auto -- Create hello.txt containing exactly: ...
  Working directory: /tmp/hello
```

## A real workflow

This is the shape of the workflows in `examples/` and `tasks/`: a CSV loop, a validator per item,
retries on validation failure, and a checkpoint so an interrupted run can continue.

```yaml
directory: ~/projects/reports
cli-agent-config:
  model: openai/gpt-5

task:
  - summarize-rows:
      loop:
        type: csv
        source: "{{directory}}/rows.csv"
        workers: 4
        retry: {max-attempts: 3, on-failure: retry}
        checkpoint-file: "{{directory}}/state/summaries.json"
        resume: true
      prompt: |
        Summarize row {{loop.index}}/{{loop.total}} ({{loop.item.name}}) and write
        {{directory}}/out/{{loop.item.name}}.md
      validate:
        - file-not-empty: "{{directory}}/out/{{loop.item.name}}.md"
```

Run it, then rerun the same command after an interruption. Finished items are skipped.

## Primitives

A workflow is built from a fixed vocabulary. The forms are the same on every adapter, and only the
CLI-specific options change.

**Workflow fields**

| Field | Type | Notes |
|-------|------|-------|
| `directory` | string | Required. Working directory for every task |
| `cli-agent` | string | `opencode`, `claude`, `codex`, `pi`, `vtcode`, `antigravity` (default `claude`) |
| `environment` | map | Env vars inherited by every task |
| `template-variables` | map | User variables, resolved in dependency order |
| `includes` | map | Reusable prompt fragments, inline or from a file |
| `ensure` | map | Pre-flight `tools` and `mcps` checks |
| `task` | list | The task tree (required) |

`cli-agent-config` holds adapter options: `model`, `timeout`, `skip-confirmations`,
`additional-dirs`, `mcp-config-file`, `raw-args`, and the per-adapter equivalents.

**Task fields**

| Field | Type | Notes |
|-------|------|-------|
| `prompt` | string | Text sent to the agent CLI |
| `task` | list or map | Nested tasks: a list runs in order, a map runs its keys concurrently |
| `include` | list | Names of top-level includes appended to the prompt |
| `loop` | map | Runs the task once per item |
| `validate` | list | Validators checked after the task exits 0 |
| `retry` | map | `max-attempts`, `on-validation-failure` (`retry`, `fail`, `skip`) |
| `skip-if` | map | `file-exists` or `file-contains`, evaluated before the task |
| `when` | string | Expression gate. An empty string skips the task |
| `env` | map | Task-level environment variables |
| `directory` | string | Task working directory, relative to the workflow `directory` |
| `cli-agent-config` | map | Per-task adapter options |
| `on-error` | string | `fail`, `continue`, `skip` |

**Loops**

| `type` | Iterates over | Required |
|--------|---------------|----------|
| `todo-list` | pending `- [ ]` items in a markdown file | `source` |
| `csv` | rows of a CSV | `source` |
| `json` | array in a JSON file, optionally nested | `source` |
| `jsonl` | one JSON object per line | `source` |
| `glob` | files matching a pattern | `pattern` |

All loops share these options:

| Option | Notes |
|--------|-------|
| `checkpoint-file` | JSON progress file, template variables expanded |
| `resume` | Continue after the last completed item |
| `retry` | `{max-attempts, on-failure}` with `skip`, `retry`, or `abort` |
| `workers` | Items run concurrently. Applies to `csv`, `json`, and `jsonl` only |
| `directory-pool` | Existing directories assigned round-robin to workers |
| `git-worktrees` | One worktree per worker: `base`, `branch-field`, `name-template`, `cleanup` |

Type-specific filters: `columns` and `filter` for `csv`, `path` and `filter` for `json`.

**Validators**

| Validator | Config | Passes when |
|-----------|--------|-------------|
| `file-exists` | string path | The path exists |
| `file-not-empty` | string path | The path exists and is not empty |
| `contains` | `{file, text}` | The file contains the text |
| `json-valid` | string path | The file parses as JSON |
| `yaml-valid` | string path | The file parses as YAML |
| `command` | `{cmd, file?, timeout?}` | The command exits 0 |

Validators run after a task exits 0. A failure follows `retry.on-validation-failure`.

**Variables**

| Variable | Value |
|----------|-------|
| `{{directory}}` | Absolute workflow directory |
| `{{gitroot}}` | Nearest ancestor with `.git/`, else `{{directory}}` |
| `{{datetime}}` | ISO-8601 timestamp, fixed for the run |
| `{{user}}` | `USER`, `USERNAME`, or `LOGNAME`, else `unknown` |
| `{{env.NAME}}` | Environment variable from the merged environment |
| `{{loop.index}}` | 0-based item index |
| `{{loop.total}}` | Number of items |
| `{{loop.remaining}}` | Items left |
| `{{loop.item}}` | Current item. Fields depend on the loop type |
| `{{loop.worker.id}}` | Worker id for parallel loops |
| `{{loop.worker.directory}}` | Worker directory with `directory-pool` or `git-worktrees` |

User variables are defined in `template-variables` and can reference each other. `--var key=value`
overrides them, and `{{env.NAME}}` reads the merged environment.

## How a run works

1. **Parse** (`agent_yaml/parser.py`) the YAML with `yaml.safe_load`.
2. **Validate** (`agent_yaml/validator.py`) required fields, task-tree shape, loop, validator, skip-if,
   when, and retry configuration, plus adapter option names.
3. **Resolve includes** (`agent_yaml/includes.py`) and **variables** (`agent_yaml/variables.py`,
   `agent_yaml/utils.py`). Reserved variables are injected, user variables resolve in dependency order,
   and cycles are rejected.
4. **Check prerequisites** (`agent_yaml/ensure.py`) with `shutil.which` before anything runs.
5. **Execute** (`agent_yaml/executor.py`) the task tree. Array items run in order, mapping keys run
   concurrently in a `ThreadPoolExecutor`, and each task is one `subprocess.run` with a timeout.
6. **Validate output**, then run the loop's next item or checkpoint its progress.

## Visual runner

`agent-yaml serve` starts a local console for browsing, running, and watching workflows:

```bash
agent-yaml serve --host 127.0.0.1 --port 8765
```

It discovers `*.yaml` under `examples/` and `tasks/`, draws the stage graph on a WebGL2 canvas,
streams execution events over SSE, and stores runs plus interval/cron schedules in SQLite. Details
and the HTTP API are in [docs/INTERFACE_RUNNER.md](docs/INTERFACE_RUNNER.md).

## Pick your agent

| Adapter | Skip confirmations | Model flag |
|---------|--------------------|------------|
| `opencode` | `--auto` | `--model provider/model` |
| `claude` | `--dangerously-skip-permissions` | `--model` (aliases translated) |
| `codex` | `--full-auto` | `-m` |
| `pi` | `--approve` | `--model provider/id` |
| `vtcode` | `--dangerously-skip-permissions` | `--model` |
| `antigravity` | `--dangerously-skip-permissions` | `--model` |

Common options (`model`, `timeout`, `skip-confirmations`, `additional-dirs`, `mcp-config-file`,
`debug`, `raw-args`, `output-format`) map to each CLI. See
[docs/ADAPTER_TROUBLESHOOTING.md](docs/ADAPTER_TROUBLESHOOTING.md) for the full per-adapter table
and [spec/ADAPTER_SPEC.md](spec/ADAPTER_SPEC.md) for the contract.

## Docs

- [docs/](docs/README.md) is the field-level reference: authoring, templating, loops, parallel
  loops, validators, interface runner, adapters.
- [docs/CLI.md](docs/CLI.md) covers every flag, exit code, environment precedence, and retry
  behaviour.
- [examples/](examples/README.md) has 40 runnable workflows, all dry-run by the test suite.
- [spec/](spec/) holds the authoritative schema and adapter specs.

## Development

```bash
pip install -e ".[dev]"   # pytest, ruff, coverage
pytest -q                 # hermetic, no model calls
ruff check agent_yaml tests
pip install -e ".[docs]"  # mkdocs
mkdocs serve              # preview docs/ at http://127.0.0.1:8000
```

The test suite is three tiers: unit (agent mocked), integration (a fake `opencode` that runs the
prompt's `bash` block), and live (`pytest --live`, a real model behind an OpenAI-compatible
gateway). See [tests/README.md](tests/README.md).

## What it doesn't do

- It does not parse or judge model output. If a step needs to prove something, give it a validator.
- MCP detection in `ensure.mcps` is a warning-only stub.
- Nested list tasks (`task: [...]` inside a task) are rejected by the validator even though
  `spec/YAML_SPEC.md` documents them. Use the mapping form.
- `agent-yaml run --resume` is a no-op. Resumption happens through each loop's `resume: true` plus
  `checkpoint-file`.
- The Codex adapter emits flags that recent `codex-cli` releases reject. The Claude adapter sends
  `--allowed-mcp-server-names`, which current `claude` builds reject. Both are listed with
  workarounds in [docs/ADAPTER_TROUBLESHOOTING.md](docs/ADAPTER_TROUBLESHOOTING.md).
- Cancellation is best effort: in a parallel group with `on-error: fail`, tasks already scheduled
  still run before the workflow aborts.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and pull requests are welcome.

## License

[MIT](LICENSE) © 2026 Joe Schlesinger
