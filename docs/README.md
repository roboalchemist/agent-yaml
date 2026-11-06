# Docs

Deep-dive pages for agent-yaml. The root [README](../README.md) is the tour and the quick reference;
these pages are the field-level detail, each mapped to the source module it documents. The
authoritative field-by-field specification remains [`spec/`](../spec).

## Start Here

| If you want to… | Read |
|-----------------|------|
| Write your first workflow | [AUTHORING.md](AUTHORING.md) |
| Look up a flag or exit code | [CLI.md](CLI.md) |
| Understand `{{variables}}`, Jinja2, and `when` | [TEMPLATING.md](TEMPLATING.md) |
| Iterate over CSV, JSON, files, or checkboxes | [LOOPS.md](LOOPS.md) then [PARALLEL_LOOPS.md](PARALLEL_LOOPS.md) |
| Verify what a task produced | [VALIDATORS.md](VALIDATORS.md) |
| Run parallel loop workers with worktrees or directory pools | [PARALLEL_LOOPS.md](PARALLEL_LOOPS.md) |
| Use or extend `agent-yaml serve` | [INTERFACE_RUNNER.md](INTERFACE_RUNNER.md) |
| Debug a CLI that rejects flags or ignores config | [ADAPTER_TROUBLESHOOTING.md](ADAPTER_TROUBLESHOOTING.md) |
| Check which `cli-agent-config` key works on which harness | [CONFIG_SURFACES.md](CONFIG_SURFACES.md) |

## All Pages

| Page | Covers | Source of truth |
|------|--------|-----------------|
| [CLI.md](CLI.md) | Commands, flags, exit codes, environment precedence, retries, troubleshooting, known limitations | `agent_yaml/cli.py` |
| [AUTHORING.md](AUTHORING.md) | Workflow skeleton, top-level fields, task tree, includes, `ensure`, CLI overrides, failure handling, authoring checklist | `agent_yaml/cli.py`, `agent_yaml/executor.py`, `agent_yaml/includes.py`, `agent_yaml/ensure.py` |
| [TEMPLATING.md](TEMPLATING.md) | The two interpolation paths, hyphen/undefined traps, available variables, Jinja2 features, whitespace, `when` semantics, env precedence | `agent_yaml/utils.py`, `agent_yaml/variables.py`, `agent_yaml/when_conditions.py` |
| [LOOPS.md](LOOPS.md) | All five loop types, field reference, the `skip-header` × `columns` matrix, JSON filters, checkpoints and resuming | `agent_yaml/loops.py`, `agent_yaml/validator.py` |
| [PARALLEL_LOOPS.md](PARALLEL_LOOPS.md) | `workers`, `directory-pool`, `git-worktrees`, worker variables, performance and error behaviour | `agent_yaml/loops.py` |
| [VALIDATORS.md](VALIDATORS.md) | Six validator kinds, path resolution, `command` details, retry strategies, execution order, events | `agent_yaml/task_validators.py`, `agent_yaml/executor.py` |
| [INTERFACE_RUNNER.md](INTERFACE_RUNNER.md) | `serve` flags, HTTP API, SSE contract, event vocabulary, node-id invariant, SQLite schema, scheduler | `agent_yaml/web/*`, `agent_yaml/events.py`, `agent_yaml/graph.py` |
| [ADAPTER_TROUBLESHOOTING.md](ADAPTER_TROUBLESHOOTING.md) | Symptom → cause → fix, per-adapter flag mapping, known-breaking flags, adding an adapter | `agent_yaml/adapters/*` |
| [CONFIG_SURFACES.md](CONFIG_SURFACES.md) | Every `cli-agent-config` key × harness: mapped flag, ignored, warned, or rejected | `agent_yaml/adapters/*`, `agent_yaml/validator.py` |
| [docstring-workflow-validators.md](docstring-workflow-validators.md) | Worked example: the validator stack in `tasks/docstring-pr-review.yaml` | that workflow |

## Related Documentation

| Location | Contents |
|----------|----------|
| [`spec/YAML_SPEC.md`](../spec/YAML_SPEC.md) | Authoritative workflow schema reference |
| [`spec/ADAPTER_SPEC.md`](../spec/ADAPTER_SPEC.md) | Cross-adapter mapping tables (lags the code in places) |
| [`spec/CLI_INTERFACE_SPECS.md`](../spec/CLI_INTERFACE_SPECS.md) | Command-line contract |
| [`spec/PROJECT_SPECS.md`](../spec/PROJECT_SPECS.md) | Project goals and architecture |
| [`tests/README.md`](../tests/README.md) | Test tiers, conventions, live-test setup |
| [`examples/README.md`](../examples/README.md) | What each numbered example demonstrates |
| [`AGENTS.md`](../AGENTS.md) | Instructions for coding agents working in this repo |

## Conventions

- Every YAML snippet in these pages parses. Snippets that are complete workflows (a `directory` plus a
  `task` tree with no illustrative placeholders) are also checked with `agent-yaml validate`; fragments
  that reference variables produced at runtime are illustrative only.
- Claims are traced to a source module; the "Source of truth" line at the bottom of each page names
  it. When code and docs disagree, the code wins — fix the page.
- New behaviour belongs in the page that owns the subsystem, plus one line in this index.

## Serving These Pages

`docs/` is the source for a MkDocs site (`mkdocs.yml` at the repo root):

```bash
pip install -e ".[docs]"
mkdocs serve     # http://127.0.0.1:8000
mkdocs build     # static site in site/, which is gitignored
```

Links in this index point at repo files outside `docs/` (`spec/`, `tests/`, `examples/`,
`AGENTS.md`). Those resolve when browsing on GitHub and have no target in the rendered site, so the
MkDocs config does not treat unresolved external links as errors.
