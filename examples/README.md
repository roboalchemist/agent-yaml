# agent-yaml examples

Runnable workflows covering every feature. Every file here **dry-runs clean in the test suite**
(`tests/integration/test_examples.py`), so they are the canonical usage reference.

`directory: /tmp` combined with `template-variables` keeps each run's output under
`{{directory}}/agent-yaml-test-NN`, so runs do not collide.

## Run one

```bash
agent-yaml validate examples/01-basic.yaml        # parse + schema + CLI check
agent-yaml run examples/01-basic.yaml --dry-run   # print the plan, no agent calls
agent-yaml run examples/01-basic.yaml             # execute
agent-yaml run examples/01-basic.yaml --debug     # print exact argv and stream output
```

Override the target directory in a sandbox:

```bash
agent-yaml run examples/05-csv-loop.yaml --directory /tmp/scratch --dry-run
```

Requires an agent CLI on `PATH` (`opencode` for most examples) and a model for the provider demos
(e.g. `--model gateway/model-name`).

## Core execution

| Example | Shows |
|---------|-------|
| `01-basic.yaml` | single task, template variables, `{{datetime}}` |
| `02-sequential.yaml` | sequential array tasks, custom variables and interpolation |
| `03-parallel.yaml` | parallel mapping keys, include concatenation |
| `07-comprehensive.yaml` | everything: parallel + sequential, loops, includes, variables, error handling |
| `08-advanced-features.yaml` | `{{gitroot}}`, `ensure`, checkpoint/resume, `--var` override |

## Loops

| Example | Shows |
|---------|-------|
| `04-todolist-loop.yaml` | todo-list loop, `mark-in-progress` / `mark-complete`, checkpoint + resume |
| `05-csv-loop.yaml` | CSV loop, explicit `columns` with `skip-header`, filtering |
| `06-glob-loop.yaml` | glob loop, pattern matching, `on-error: continue` |
| `12-loop-filtering.yaml` | CSV filter, glob `exclude`, glob `sort` |
| `27-json-loop-basic.yaml` | JSON array of objects |
| `28-json-loop-nested.yaml` | nested array extraction with `path` dot notation |
| `29-json-loop-filter.yaml` | multi-condition filters (`AND` / `OR`), nested keys |
| `30-jsonl-loop.yaml` | JSON Lines input |
| `31-json-comprehensive-test.yaml` | JSON loops across features |
| `32-json-checkpoint-test.yaml` | JSON checkpoint + resume |
| `33-json-parallel-workers.yaml` | JSON loop with concurrent `workers` |
| `34-json-error-handling.yaml` | JSON loop retry / skip behaviour |
| `35-json-with-validators.yaml` | JSON loop outputs validated after each item |
| `36-jsonl-real-world.yaml` | log processing in JSONL |

## Validators

| Example | Shows |
|---------|-------|
| `13-validators.yaml` | `file-exists`, `file-not-empty`, `contains` |
| `14-validators-negative.yaml` | failure when the file is never created |
| `15-validators-file-not-empty-negative.yaml` | failure when the file is empty |
| `16-validators-contains-negative.yaml` | failure when expected text is missing |
| `17-validators-with-retry.yaml` | retry on validation failure |
| `18` / `19` / `20` | `json-valid` / `yaml-valid` / `command` validators |
| `21` / `22` / `23` | the same three, negative cases |
| `24` / `25` / `26` | the same three, with retry |

The negative examples are expected to exit non-zero; that is the point.

## Conditionals, environment, providers

| Example | Shows |
|---------|-------|
| `30-skip-if-conditions.yaml` | `skip-if` file conditions for idempotent workflows |
| `39-when-conditions.yaml` | `when` expressions (`and`, `or`, `not`, comparisons) |
| `37-environment-variables.yaml` | workflow vs task `env:` precedence |
| `38-env-interpolation.yaml` | `{{env.VAR}}` interpolation |
| `11-codex.yaml` | `cli-agent: codex` |

## Output and cleanup

Each example writes under `{{directory}}/agent-yaml-test-NN` (or the path named in its
`template-variables`). Logs, if any, land beside the outputs. To reset:

```bash
rm -rf /tmp/agent-yaml-test-*
```

## Notes

- `tasks/` (one directory up) holds larger real-world workflows rather than feature demos; the test
  suite dry-runs those as well.
- Prompt conventions: every task asks the agent to create or modify **files**, because agent output is
  never parsed — validators and tests assert on the files.
