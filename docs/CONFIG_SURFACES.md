# Config Surfaces by Harness

`cli-agent-config` is the adapter's option bag. The same key can mean different things on different
CLIs, and some keys only exist on one harness. This page is the full matrix: one row per surface, one
column per harness. It is audited against the installed CLI versions (`opencode` 2.0.25, `claude`
2.1.302, `codex` 0.153.4, `pi` 1.5.0, `vtcode` 0.181.4, `agy` 1.5.1) and their `--help` output.

Workflow-level `cli-agent-config` applies to every task; a task-level `cli-agent-config` merges over
it (task values win) before the adapter builds the command.

## Matrix

| Surface | opencode | claude | codex | pi | vtcode | antigravity |
|---------|----------|--------|-------|----|--------|-------------|
| `model` | `--model` | `--model` | `--model` | `--model` | `--model` | `--model` |
| `provider` | ignored | ignored | `--oss` (ollama/lmstudio) | `--provider` | `--provider` | rejected |
| `session-id` | `--session` | `--session-id` | `resume` | `--session-id` | `--session-id` | `--conversation` |
| `continue` | `--continue` | `--continue` | `resume` (`--last`) | `--continue` | `resume` (`--last`) | `--continue` |
| `title` | `--title` | `--name` | ignored | `--name` | rejected | rejected |
| `agent` | `--agent` | `--agent` | ignored | rejected | rejected | `--agent` |
| `permissions` | `--agent` (when `agent` unset) | `--permission-mode` | `--sandbox` (plan → read-only) | rejected | rejected | `--mode` (plan → plan) |
| `output-format` | `--format` | `--output-format` | `--json` | `--mode` | `--json` | `--output-format` |
| `skip-confirmations` | `--auto` | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | `--approve` | `--dangerously-skip-permissions` | `--dangerously-skip-permissions` |
| `debug` | `--print-logs` | `--debug` | ignored + warning | `--verbose` | `--verbose` | rejected |
| `raw-args` | passthrough | passthrough | passthrough | passthrough | passthrough | passthrough |
| `additional-dirs` | ignored + warning | `--add-dir` (each) | `--add-dir` (each) | ignored + warning | ignored + warning | `--add-dir` (each) |
| `mcp-servers` | ignored + warning | ignored + warning | ignored | ignored + warning | ignored + warning | ignored + warning |
| `mcp-config-file` | ignored + warning | `--mcp-config` | ignored | ignored + warning | ignored + warning | ignored + warning |
| `tools` | ignored | `--tools` | ignored | `--tools` | `--allowed-tools` | rejected |
| `exclude-tools` | ignored | `--disallowed-tools` | ignored | `--exclude-tools` | `--disallowed-tools` | rejected |
| `thinking` | ignored | ignored | ignored | `--thinking` | rejected | rejected |
| `no-tools` | ignored | `--tools` (empty) | ignored | `--no-tools` | rejected | rejected |
| `session` | ignored | `--no-session-persistence` (when false) | `--ephemeral` (when false) | no `--no-session` (when true) | rejected | rejected |
| `no-extensions` | ignored | ignored | ignored | `--no-extensions` | rejected | rejected |
| `web-search` | ignored | ignored | `--enable` web_search | rejected | rejected | rejected |
| `server` | `--server` | ignored | ignored | rejected | rejected | rejected |
| `standalone` | no `--standalone` (when false) | ignored | ignored | rejected | rejected | rejected |
| `security-level` | ignored | ignored | ignored | rejected | `--security-level` | rejected |
| `max-tool-calls` | ignored | ignored | ignored | rejected | `--max-tool-calls` | rejected |
| `quiet` | ignored | ignored | ignored | rejected | `--quiet` | rejected |
| `effort` | ignored | `--effort` | `-c` model_reasoning_effort | rejected | rejected | `--effort` |
| `sandbox` | ignored | ignored | `--sandbox` (mode string) | rejected | rejected | `--sandbox` (boolean) |
| `json-schema` | ignored | `--json-schema` | `--output-schema` | rejected | rejected | `--json-schema` |
| `last-message-file` | ignored | ignored | `-o` | rejected | `--last-message-file` | rejected |
| `system-prompt` | ignored | `--system-prompt` | ignored | `--system-prompt` | rejected | rejected |
| `append-system-prompt` | ignored | `--append-system-prompt` | ignored | `--append-system-prompt` | rejected | rejected |
| `settings` | ignored | `--settings` | ignored | rejected | rejected | `--settings` |
| `disable-slash-commands` | ignored | `--disable-slash-commands` | ignored | rejected | rejected | `--disable-slash-commands` |
| `max-budget` | ignored | `--max-budget-usd` | ignored | rejected | rejected | rejected |
| `fallback-model` | ignored | `--fallback-model` | ignored | rejected | rejected | rejected |
| `project` | ignored | ignored | ignored | rejected | rejected | `--project` |
| `log-file` | ignored | ignored | ignored | rejected | rejected | `--log-file` |
| `log-level` | `--log-level` | ignored | ignored | rejected | `--log-level` | rejected |
| `color` | ignored | ignored | ignored | rejected | `--color` | rejected |
| `files` | `--file` | ignored | ignored | rejected | rejected | rejected |
| `images` | ignored | ignored | `-i` | rejected | rejected | rejected |
| `enable` | ignored | ignored | `--enable` | rejected | rejected | rejected |
| `ignore-user-config` | ignored | ignored | `--ignore-user-config` | rejected | rejected | rejected |
| `ignore-rules` | ignored | ignored | `--ignore-rules` | rejected | rejected | rejected |
| `events-file` | ignored | ignored | ignored | rejected | `--events` | rejected |
| `max-concurrent-ops` | ignored | ignored | ignored | rejected | `--max-concurrent-ops` | rejected |
| `api-rate-limit` | ignored | ignored | ignored | rejected | `--api-rate-limit` | rejected |
| `config-overrides` | ignored | ignored | `-c` | rejected | `-c` | rejected |
| `session-dir` | ignored | ignored | ignored | `--session-dir` | rejected | rejected |
| `no-context-files` | ignored | ignored | ignored | `--no-context-files` | rejected | rejected |
| `no-mcp` | ignored | ignored | ignored | `--no-mcp` | rejected | rejected |
| `no-builtin-tools` | ignored | ignored | ignored | `--no-builtin-tools` | rejected | rejected |
| `skills` | ignored | ignored | ignored | `--skill` | rejected | rejected |
| `extensions` | ignored | ignored | ignored | `-e` | rejected | rejected |
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

Every harness validates its option bag strictly: an unknown key fails `agent-yaml validate` with
the adapter's full allowed list. Keys another harness owns appear in the matrix as `ignored`, so
they validate but do nothing; a real typo is rejected instead of silently ignored. `raw-args` is the
escape hatch for a flag the adapter does not model yet.

`sandbox` is deliberately two types: a boolean on `antigravity` (turn on the terminal sandbox) and a
mode string on `codex` (`read-only`, `workspace-write`, `danger-full-access`).

## Per-Harness Notes

| Harness | Notes |
|---------|-------|
| `opencode` | `permissions: [x]` is a fallback for `agent: x` and only applies when `agent` is unset. `--standalone` is on by default; `standalone: false` removes it, and `server` replaces it. Model ids are `provider/model[#variant]`; a bare id logs a warning. `thinking` is not mapped: OpenCode's flag is a display toggle, not a reasoning level. |
| `claude` | `tools` replaces the default `--tools default`; `no-tools` sends `--tools ""`. `debug: true` implies `--output-format stream-json` and `--verbose`. `mcp-servers` warns: Claude 2.x has no per-server CLI allow flag, so scope servers in the MCP config. Legacy names `sonnet-4.5`/`opus-4` translate to the `sonnet`/`opus` aliases. |
| `codex` | `skip-confirmations` uses the approvals-and-sandbox bypass; `permissions` maps either a sandbox mode or `-c approval_policy=…`. `continue`/`session-id` switch to `codex exec resume`, which has no `--sandbox` or `--add-dir`, so those warn and drop on resume. `debug` has no headless equivalent and warns. `web-search` is `--enable web_search`. |
| `pi` | Sessions are ephemeral by default (`--no-session`); `session: true` keeps them, `session-id`/`continue` replace the flag, and `session: false` (explicit) adds `--no-approve`. `provider` requires `model` (the CLI rejects `--provider` alone). `debug` maps to `--verbose`, which pi only uses in the interactive TUI. |
| `vtcode` | Runs `vtcode exec`; `continue` switches to `vtcode exec resume --last` (or `resume <session-id>`), which lacks `--json`, `--events`, and `--last-message-file`, so those warn and drop on resume. `security-level`, `max-tool-calls`, `max-concurrent-ops`, `api-rate-limit`, `quiet`, and `config-overrides` are vtcode-only. Needs `[automation.full_auto]` in the workspace `vtcode.toml`. |
| `antigravity` | Runs `agy -p`. `permissions` maps to `--mode` (`plan`, `accept-edits`, `auto`) or `--dangerously-skip-permissions` for yolo/never. `effort`, `sandbox`, `agent`, `json-schema`, `settings`, `project`, `log-file`, and `disable-slash-commands` are supported; `timeout` also becomes `--print-timeout`. `json-schema` requires `output-format: json` or `stream-json` (validated). Model slugs come from `agy models` and differ per account. |

## Deliberately Not Exposed

These CLI capabilities are real but stay out of `cli-agent-config`. Anything interactive would hang
or corrupt a one-shot subprocess; anything secret would land in argv or process listings.

| Harness | Capability | Why not |
|---------|------------|---------|
| `opencode` | `--wizard`, `--completions` | Interactive setup / shell completion, not a run input |
| `opencode` | `--fork`, `--thinking` | `--fork` takes a session id (pi-shaped, not boolean); `--thinking` is a display toggle, not a reasoning level |
| `opencode` | `--prompt` | Top-level flag, rejected by `opencode run`; the adapter passes the prompt positionally after `--` |
| `claude` | `--input-format`, `--replay-user-messages` | Require a stdin driver; workflows run one prompt with closed stdin |
| `claude` | `--agents`, `--setting-sources`, `--plugin-dir`, `--debug-file`, `--fork-session`, `--autocompact`, `--permission-prompts`, `--bare` | Advanced policy/plugin knobs that belong to the operator's Claude install, not a portable workflow |
| `claude` | `--bg`, `--cloud`, `--remote-control`, `--ide`, `--chrome`, `--brief` | Interactive/cloud session management |
| `codex` | `--profile`, `--strict-config` | Machine-local config layering and hygiene checks |
| `codex` | `--color` | Output cosmetics; the executor captures raw output |
| `codex` | `--dangerously-bypass-hook-trust` | Unsafe unless hooks are pre-vetted |
| `codex` | `--thread-source`, `--remote*`, subcommands (`review`, `fork`, `apply`, `mcp-server`, `cloud`) | Runtime/session tooling outside the one-shot exec model |
| `pi` | `--api-key`, `--export`, `--resume`, `--models`, `--theme`, `--tui-mode` | Secrets in argv, post-hoc export, or interactive pickers |
| `pi` | `--fork` | Takes a session id and conflicts with the default `--no-session`; use `session-id`/`continue` |
| `pi` | `--offline`, `PI_TELEMETRY` | Covered by workflow/task `env` |
| `vtcode` | `--api-key-env`, `--workspace` | Secret indirection proved fragile in probing; the executor already sets the working directory |
| `vtcode` | `--full-access`, `--dangerously-*` beyond skip | Disable the sandbox; not a safe default |
| `vtcode` | `--ide`, `--show-file-diffs`, `--theme`, `--chrome`, `--no-chrome`, `--fork-session`, `--summarize`, `--all`, `--research-preview`, `--codex-experimental` | Interactive, side-effecting, or experimental gates |
| `vtcode` | `--dry-run`, `--print`, `--full-auto` | `agent-yaml --dry-run` and the executor already cover them; `exec` is already non-interactive |
| `antigravity` | `--new-project` | Mutating side effect; prefer `project` |
| `antigravity` | `--remote-agent`, `--remote-control` | Background/remote infrastructure, unsafe in batch runs |
| `antigravity` | `--input-format`, `-i/--prompt-interactive` | Needs a stdin driver or an interactive session |
| `antigravity` | subcommands (`acp`, `mic-serve`, `install`, `update`, `plugin*`) | Session/bootstrap tooling, not turn config |

## Live Coverage

The mapping cells are verified offline against the adapters by the test below. Every harness has a
live matrix built on the shared runner (`scripts/harness_matrix.py`): `validate_pi_params.py`,
`validate_vtcode_params.py`, `validate_antigravity_params.py`, `validate_opencode_params.py`,
`validate_claude_params.py`, `validate_codex_params.py`. The pi, vtcode, antigravity, and opencode
matrices have been run live here; the claude and codex matrices need an authenticated account
(Claude OAuth session, Codex credits) and are coverage-checked but not run in this environment.

## How This Table Is Checked

`tests/unit/test_config_surface_matrix.py` parses the matrix above, builds a command for every
surface × harness pair, and asserts the cell matches the adapter's behaviour (flag present, argv
unchanged with or without a warning, or a validation error). Changing an adapter without updating
this page fails that test.

```bash
pytest tests/unit/test_config_surface_matrix.py
```

Run a harness's live matrix (one shared runner, same flags for all six):

```bash
python scripts/validate_pi_params.py          --model <provider/model>
python scripts/validate_claude_params.py      --model <model>
python scripts/validate_codex_params.py       --model <model>
python scripts/validate_opencode_params.py    --model <provider/model>
python scripts/validate_vtcode_params.py      --model <provider/model>
python scripts/validate_antigravity_params.py --model <model slug>
```

Each matrix takes `--only`, `--tag`, `--timeout`, and `--verbose`, and prints the number of surfaces
covered plus a pass/fail line per case.
