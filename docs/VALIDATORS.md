# Task Validators

Validators check what a task actually produced after the agent CLI exits 0. They are the difference
between "the agent said it was done" and "the artifact is on disk, parses, and contains the right
text". Six kinds exist (`src/validator.py:567`), each a single-key mapping in a task's `validate`
list.

## Basic Usage

```yaml
task:
  - write-report:
      prompt: |
        Write the report to {{workspace}}/report.md
      validate:
        - file-exists: "{{workspace}}/report.md"
        - file-not-empty: "{{workspace}}/report.md"
        - contains:
            file: "{{workspace}}/report.md"
            text: "## Summary"
```

Behaviour:

- Validators run **only when the task exits 0**. A non-zero exit goes straight to error handling.
- **All validators run**, even after one fails, so a single pass reports every problem at once
  (`src/task_validators.py:488`).
- The task's result then carries `validation: {all_passed, results, failed_count, total_count}`.
- `validate: []` is a schema error; drop the field instead.

---

## The Six Validators

| Validator | Config | Passes when |
|-----------|--------|-------------|
| `file-exists` | string path | the path exists (file or directory) |
| `file-not-empty` | string path | the path exists and has size > 0 |
| `contains` | `{file, text}` | the file contains `text` as a substring |
| `json-valid` | string path | the whole file parses as JSON |
| `yaml-valid` | string path | the whole file parses with `yaml.safe_load` |
| `command` | `{cmd, file?, timeout?}` | the command exits 0 |

### Paths resolve against the agent-yaml process cwd

Validator paths are **not** resolved against the workflow `directory` and validators do not `cd`
into it (`src/task_validators.py:32`). Either use absolute paths (the usual pattern is
`{{directory}}/...` or `{{workspace}}/...`) or run agent-yaml from the directory the validators
assume.

### `command` details

```yaml
validate:
  - command:
      cmd: "python3 {{directory}}/scripts/check_docstrings.py {file}"
      file: "{{directory}}/example-service/docs/out.md"
      timeout: 60
```

- Runs through the shell (`shell=True`), so pipes and `&&` work.
- `{file}` is replaced with the absolute, `~`-expanded, template-interpolated path — after the
  command string itself is interpolated.
- If `file` is given, a missing file fails the validator before the command runs.
- `timeout` is in seconds (default 30, `src/task_validators.py:46`); a timeout is a failure.
- Only the exit code matters. stdout/stderr are captured and truncated to 200 characters in the
  result details, so print diagnostics from the script for debugging.

---

## Validation Failure and Retry

A failed validation is handled by the task's `retry` block:

```yaml
task:
  - write-report:
      prompt: "Write {{workspace}}/report.md"
      validate:
        - file-not-empty: "{{workspace}}/report.md"
        - contains:
            file: "{{workspace}}/report.md"
            text: "## Summary"
      retry:
        max-attempts: 3
        on-validation-failure: retry
```

| Field | Values | Default |
|-------|--------|---------|
| `max-attempts` | integer ≥ 1 | `1` (no retry) |
| `on-validation-failure` | `retry`, `fail`, `skip` | `fail` |

How each strategy behaves (`src/executor.py:733`):

| `on-validation-failure` | Behaviour |
|-------------------------|-----------|
| `retry` | Re-runs the **whole task** (fresh agent invocation) until `max-attempts`. When attempts are exhausted it falls back to the task's `on-error` strategy: `fail` raises, `continue` records a failed task and keeps going, `skip` marks it skipped. |
| `fail` | Raises immediately; the surrounding `on-error` decides whether the workflow stops. |
| `skip` | Marks the task `skipped` — later tasks still see the (invalid) artifact, so gate them with `skip-if`. |

Retries re-run the agent, not just the validator, so a prompt that does not say "fix what the
validator complained about" will usually fail the same way. Mention the requirement explicitly:

```yaml
prompt: |
  Write {{workspace}}/report.md.
  It MUST start with a "## Summary" section — a validator checks for that heading.
```

`retry` validation rejects unknown fields and `max-attempts < 1` (`src/validator.py:672`).

---

## Execution Order Inside One Task

```
skip-if  →  when  →  agent CLI  →  exit code 0?  →  validators  →  retry.on-validation-failure
                                   exit code != 0 → on-error
```

- `skip-if` is checked first, then `when` (`src/executor.py:179`, `src/executor.py:221`); see
  [TEMPLATING.md](TEMPLATING.md) for `when` semantics.
- `--dry-run` does **not** execute validators — the run only reports that N validators are declared.
- Validators are per task; there is no workflow-level `validate` block.

---

## Observability

In the CLI you get, per task:

```
Running 3 validator(s) for task 'write-report'...
✅ All validators passed for task 'write-report'
```

On failure the message names the failing count and each validator's `error_message` (file path,
JSON/YAML line and column, exit code, or timeout).

In the interface runner (`agent-yaml serve`) a task with validators emits `validators_started` and
`validators_completed` — with `total` and a `payload` holding the full result — and failed
validation emits `task_failed` with `payload.validation`. Retries emit `task_retrying` with the
attempt number. See [INTERFACE_RUNNER.md](INTERFACE_RUNNER.md).

---

## Examples in This Repo

| Pattern | Example |
|---------|---------|
| Passing validators of each kind | `examples/13-validators.yaml`, `examples/18-*`, `examples/19-*`, `examples/20-*` |
| Failing validators of each kind | `examples/14-*` through `examples/17-*`, `examples/21-*` through `examples/23-*` |
| Retry on failure | `examples/17-validators-with-retry.yaml`, `examples/24-*` through `examples/26-*` |
| Validators inside JSONL loops | `examples/35-json-with-validators.yaml` |

The `*-negative.yaml` examples are expected to fail validation; they exist to exercise the failure
paths, so do not "fix" them.

---

## Limitations

1. **Paths ignore the task directory** — the most common cause of "validator says the file is
   missing".
2. **No fail-fast.** Every validator runs, including the expensive `command` ones.
3. **No content assertions beyond substring match** — no regex, no JSON pointer, no line ranges. Use
   a `command` validator with a small script for anything richer.
4. **`contains` reads the whole file as text**; binary artifacts should use `file-not-empty` or a
   command.
5. **`command` runs with `shell=True`** and the workflow's merged environment — treat a workflow
   file as code you trust.
6. **Validators only run on exit 0.** An agent that exits non-zero with a perfectly good artifact
   still fails before validation.

---

## Best Practices

1. **Pair `file-exists` with `file-not-empty`** — agents happily create zero-byte files.
2. **Assert on a structural marker** (`contains` for a heading, `json-valid`/`yaml-valid` for
   structured output) rather than trusting prose.
3. **Put the assertion in the prompt too**, so a retry can actually succeed.
4. **Use `retry` for flaky generations, `fail` for correctness gates** you would rather see stop the
   run.
5. **Keep `command` validators fast and deterministic**; they run on every attempt.

---

Source of truth: `src/task_validators.py` (validator implementations, `run_validators`),
`src/executor.py` (ordering, retry, events), `src/validator.py:546` (schema).
Related: `docs/docstring-workflow-validators.md` for a real workflow built on these.
