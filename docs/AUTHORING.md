# Authoring a Workflow

A workflow is one YAML file: a `directory` to work in, an agent CLI to drive, and a `task` tree.
Each task is a single agent invocation, and tasks talk to each other through files. This page is the
authoring checklist; field-level references live in [LOOPS.md](LOOPS.md),
[VALIDATORS.md](VALIDATORS.md), [TEMPLATING.md](TEMPLATING.md) and
[PARALLEL_LOOPS.md](PARALLEL_LOOPS.md).

## Skeleton

```yaml
directory: ~/projects/example-repo-1
cli-agent: claude
cli-agent-config:
  timeout: 900            # seconds, per task
  skip-confirmations: true

on-error: continue

template-variables:
  workspace: "/tmp/run-{{datetime}}"

task:
  - plan:
      prompt: |
        Read {{directory}}/README.md and write the plan to {{workspace}}/plan.md

  - implement:
      when: "{{skip_impl}} == 'true'"
      prompt: |
        Implement the plan in {{workspace}}/plan.md.
        Write a summary to {{workspace}}/summary.md
      validate:
        - file-not-empty: "{{workspace}}/summary.md"
```

Check it before running it:

```bash
agent-yaml validate tasks/my-workflow.yaml   # parse + schema + CLI availability, no agent calls
agent-yaml run tasks/my-workflow.yaml --dry-run
```

---

## Top-Level Fields

| Field | Required | Default | Meaning |
|-------|----------|---------|---------|
| `directory` | yes | — | Working directory for every task; `~` expanded, must exist |
| `cli-agent` | no | `claude` | `opencode`, `claude`, `gemini`, `qwen`, `codex` |
| `cli-agent-config` | no | — | Adapter options (`model`, `timeout`, `skip-confirmations`, `additional-dirs`, …) |
| `on-error` | no | `fail` | `fail`, `continue`, `skip`; overridable per task |
| `environment` | no | — | Workflow-level env vars, inherited by tasks |
| `template-variables` | no | — | User variables; may reference reserved/user/env vars |
| `includes` | no | — | Reusable prompt fragments (inline or file) |
| `ensure` | no | — | Pre-flight `tools` / `mcps` checks |
| `task` | yes | — | The task tree |

`cli-agent-config` is merged with any per-task `cli-agent-config`, so a workflow-level `timeout`
applies unless a task overrides it. Adapter-specific keys are listed in
[ADAPTER_TROUBLESHOOTING.md](ADAPTER_TROUBLESHOOTING.md).

---

## The Task Tree

- A **list** under `task:` runs sequentially.
- A **mapping** inside a task runs its keys **in parallel** (thread per key).
- A task body holds one of `prompt`, `task` (nested mapping), `loop`, or `include`.

```yaml
task:
  - gather:
      prompt: "Write facts to {{workspace}}/facts.md"

  - independent-checks:      # mapping => these two run concurrently
      lint:
        prompt: "Lint, write {{workspace}}/lint.md"
      typecheck:
        prompt: "Typecheck, write {{workspace}}/typecheck.md"

  - summarise:
      prompt: "Read every *.md in {{workspace}} and write summary.md"
```

Nested lists (`task: [ ... ]` inside a task) are **rejected by the validator** even though the spec
documents them — use the mapping form.

---

## Agents Communicate Through Files

This is the single most important rule: **agent stdout is never parsed**. Nothing reads what the
agent prints. A step that only "reports" its result loses that result.

Write prompts that demand artifacts:

```yaml
- discover:
    prompt: |
      Find all open PRs labelled docstring.
      Write them as CSV with the header "number,title,branch,url" to {{workspace}}/prs.csv
      Report: "discovered"      # human-readable only; nothing parses this
```

Consequences that follow from it:

- Every handoff needs an explicit path, and later tasks must be told to read that path.
- Assert the artifact with `validate:` so a silent no-op fails loudly (see
  [VALIDATORS.md](VALIDATORS.md)).
- Use `skip-if: file-exists:` to make a task idempotent across re-runs.
- Prefix long prompts with the exact command or file the agent must produce; do not rely on the agent
  "remembering" earlier steps, since each task is a fresh process.

---

## Includes

Inline fragments:

```yaml
includes:
  use-subagents: "Use sub-agents in parallel."
  always-validate: "Validate all changes before finishing."

task:
  - review:
      prompt: "Review the diff."
      include: [use-subagents, always-validate]
```

- A name defined under `includes:` is an inline fragment; any other string is treated as a **file
  path** and a missing file is an error.
- Included content is appended to the prompt **before** interpolation, so `{{variables}}` inside a
  fragment resolve against the task's variables.
- Include cycles are rejected.

---

## Pre-flight `ensure`

```yaml
ensure:
  tools:
    - gh
    - git
  mcps:
    - notion
```

`tools` are checked with `shutil.which` before the first task; all missing tools are reported
together. `mcps` detection is **not implemented** — each entry logs a warning and passes
(`agent_yaml/ensure.py`).

---

## Variables and Environment at the CLI

```bash
agent-yaml run tasks/my-workflow.yaml \
  --var pr_number=123 \
  --var pr_branch=fix-docstrings \
  --env-file .env.local \
  --directory ~/projects/example-repo-3 \
  --cli-agent opencode \
  --model gateway/model-name
```

- `--var` overrides any `template-variables` entry and arrives as a **string** — relevant for `when`
  comparisons (see [TEMPLATING.md](TEMPLATING.md)).
- `--env-file` may be repeated; later files win. Precedence: system env < `--env-file` < workflow
  `environment:` < task `env:` < `--var`.
- `--directory`, `--cli-agent` and `--model` override the file for every task, which is how the same
  workflow runs on a different repo, agent, or model without edits.

---

## Failure Handling

`on-error` exists at workflow and task level (task wins):

| Value | Behaviour |
|-------|-----------|
| `fail` | Stop the workflow and exit non-zero |
| `continue` | Log the failure, keep going |
| `skip` | Treat the task as skipped and keep going |

`on-error: continue` is the right default for per-item work (a loop where one item fails) and the
wrong default for a linear pipeline where later steps depend on the failed artifact. Validation
failures follow the same strategy when `retry.on-validation-failure` is exhausted.

---

## Known Traps

1. **A task named `loop` or `prompt` collides with meta fields.** Any task name is a mapping key, but
   those two names shadow the task body keys — rename them (`run-loop`, `write-prompt`).
2. **`prompt: {{var}}` is invalid YAML** — `{{` starts a flow mapping. Quote it or use a block
   scalar.
3. **`run --resume` is a no-op.** Resumption is per loop via `resume: true` + `checkpoint-file`.
4. **`--dry-run` evaluates `skip-if` and `when`** but runs neither the agent nor the validators, so a
   gate can hide tasks you expected to see in the plan.
5. **Undefined variables render as empty strings** — a typo produces an empty prompt rather than an
   error.
6. **Parallel mapping keys share the same working directory**, so two tasks writing the same file
   will race. Give each its own output path, or use a loop with `directory-pool`/`git-worktrees`
   ([PARALLEL_LOOPS.md](PARALLEL_LOOPS.md)).

---

## Checklist Before Committing a Workflow

1. `agent-yaml validate <file>` is clean.
2. `agent-yaml run <file> --dry-run` shows the task tree, loop counts, and variables you expect.
3. Every handoff names an absolute path built from `{{directory}}` or `{{workspace}}`.
4. Long or destructive tasks have `validate:` plus an idempotent `skip-if:`.
5. `--debug` shows the argv you expect (`agent-yaml run <file> --debug`) — especially after changing
   `cli-agent` or `model`.
6. The file lives in `tasks/` (real workflows) or `examples/` (teaching examples) so CI dry-runs it
   (`tests/integration/test_examples.py`).

---

Source of truth: `agent_yaml/cli.py` (`run_workflow`, CLI flags), `agent_yaml/executor.py` (task execution,
`on-error`, env merge), `agent_yaml/includes.py`, `agent_yaml/ensure.py`, `agent_yaml/validator.py`.
Related: `spec/YAML_SPEC.md` (authoritative field reference) and `examples/01-basic.yaml` for the
smallest complete workflow.
