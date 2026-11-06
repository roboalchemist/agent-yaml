# Config Surfaces by Harness

`cli-agent-config` is the adapter's option bag. The same key can mean different things on different
CLIs, and some keys only exist on one harness. This page is the full matrix: one row per surface, one
column per harness.

Workflow-level `cli-agent-config` applies to every task; a task-level `cli-agent-config` merges over
it (task values win) before the adapter builds the command.

## Matrix

| Surface | opencode | claude | codex | pi | vtcode | antigravity |
|---------|----------|--------|-------|----|--------|-------------|
| `model` | `--model` | `--model` | `--model` | `--model` | `--model` | `--model` |
| `provider` | ignored | ignored | ignored | `--provider` | `--provider` | rejected |
| `session-id` | `--session` | `--session-id` | ignored | `--session-id` | `--session-id` | `--conversation` |
| `continue` | ignored | ignored | ignored | `--continue` | `resume` (`--last` or id) | `--continue` |
| `title` | `--title` | ignored | ignored | `--name` | rejected | rejected |
| `agent` | `--agent` | ignored | ignored | rejected | rejected | `--agent` |
| `permissions` | `--agent` (when `agent` unset) | `--permission-mode` | `-a` | rejected | rejected | rejected |
| `output-format` | `--format` | `--output-format` | ignored + warning | `--mode` | `--json` | `--output-format` |
| `skip-confirmations` | `--auto` | `--dangerously-skip-permissions` | `--full-auto` | `--approve` | `--dangerously-skip-permissions` | `--dangerously-skip-permissions` |
| `debug` | `--print-logs` | `--debug` (also `--verbose`, stream-json) | `-c` debug=true | `--verbose` | `--verbose` | rejected |
| `raw-args` | passthrough | passthrough | passthrough | passthrough | passthrough | passthrough |
| `additional-dirs` | ignored + warning | `--add-dir` (each) | `-C` (first only) | ignored + warning | ignored + warning | `--add-dir` (each) |
| `mcp-servers` | ignored + warning | `--allowed-mcp-server-names` | ignored | ignored + warning | ignored + warning | ignored + warning |
| `mcp-config-file` | ignored + warning | `--mcp-config` | ignored | ignored + warning | ignored + warning | ignored + warning |
| `tools` | ignored | `--tools` | ignored | `--tools` | rejected | rejected |
| `exclude-tools` | ignored | ignored | ignored | `--exclude-tools` | rejected | rejected |
| `thinking` | ignored | ignored | ignored | `--thinking` | rejected | rejected |
| `no-tools` | ignored | ignored | ignored | `--no-tools` | rejected | rejected |
| `session` | ignored | ignored | ignored | no `--no-session` | rejected | rejected |
| `no-extensions` | ignored | ignored | ignored | `--no-extensions` | rejected | rejected |
| `web-search` | ignored | ignored | `--search` | rejected | rejected | rejected |
| `server` | `--server` (replaces `--standalone`) | ignored | ignored | rejected | rejected | rejected |
| `standalone` | no `--standalone` (default true) | ignored | ignored | rejected | rejected | rejected |
| `security-level` | ignored | ignored | ignored | rejected | `--security-level` | rejected |
| `max-tool-calls` | ignored | ignored | ignored | rejected | `--max-tool-calls` | rejected |
| `quiet` | ignored | ignored | ignored | rejected | `--quiet` | rejected |
| `effort` | ignored | ignored | ignored | rejected | rejected | `--effort` |
| `sandbox` | ignored | ignored | ignored | rejected | rejected | `--sandbox` |
| `timeout` | executor | executor | executor | executor | executor | `--print-timeout` |

## Legend

| Cell | Meaning |
|------|---------|
| `--flag` | Mapped to that CLI flag |
| ignored | Accepted by the adapter, no effect, no warning |
| ignored + warning | Accepted, no effect, adapter logs a warning naming the option |
| rejected | `agent-yaml validate` fails with `Unknown <harness> option '<key>'` |
| passthrough | Appended to argv verbatim, before the prompt |
| executor | Not a CLI flag: the executor applies the subprocess timeout |
| no `--flag` | The option removes that flag rather than adding one |

Only `pi`, `vtcode`, and `antigravity` validate their option bag strictly. `opencode`, `claude`, and
`codex` accept arbitrary keys and silently ignore anything their adapter does not read, so a typo
only shows up as a no-op. Use one of the strict harnesses when you want a typo caught at validate
time.

## Per-Harness Notes

| Harness | Notes |
|---------|-------|
| `opencode` | `permissions: [x]` is a fallback for `agent: x` and only applies when `agent` is unset. `--standalone` is on by default; `standalone: false` removes it, and `server` replaces it. Model ids are `provider/model[#variant]`; a bare id logs a warning. |
| `claude` | `tools` replaces the default `--tools default`. `debug: true` implies `--output-format stream-json` and `--verbose`. `mcp-servers` and `mcp-config-file` are real Claude flags. |
| `codex` | Only the first `additional-dirs` entry becomes `-C`; extras log a warning. `output-format` is warned and dropped. `web-search` is Codex-only. There is no session flag. |
| `pi` | Sessions are ephemeral by default (`--no-session`); `session: true` keeps them, `session-id`/`continue` replace the flag. `tools` accepts a string or a list. `provider` is a first-class flag. |
| `vtcode` | Runs `vtcode exec`; `continue` switches to `vtcode exec resume --last` (or `resume <session-id>`). `security-level`, `max-tool-calls`, and `quiet` are vtcode-only. Needs `[automation.full_auto]` in the workspace `vtcode.toml`. |
| `antigravity` | Runs `agy -p`. `effort`, `sandbox`, `agent`, and `additional-dirs` are supported; `timeout` also becomes `--print-timeout`. Model slugs come from `agy models` and differ per account. |

## Timeout

`timeout` is always enforced by the executor: it is the subprocess deadline, not an adapter flag.
`antigravity` additionally passes `--print-timeout Ns`, so the CLI stops its own turn before the
executor kills the process.

## Live Coverage

The mapping cells are verified offline against the adapters by the test below. Live inference has
been run for `pi`, `vtcode`, and `antigravity` through their matrices
(`scripts/validate_pi_params.py`, `scripts/validate_vtcode_params.py`,
`scripts/validate_antigravity_params.py`). `opencode`, `claude`, and `codex` mapping cells are
unit-verified only in this repo; their CLIs are third-party and change between releases.

## How This Table Is Checked

`tests/unit/test_config_surface_matrix.py` parses the matrix above, builds a command for every
surface × harness pair, and asserts the cell matches the adapter's behaviour (flag present, argv
unchanged with or without a warning, or a validation error). Changing an adapter without updating
this page fails that test.

```bash
pytest tests/unit/test_config_surface_matrix.py
```
