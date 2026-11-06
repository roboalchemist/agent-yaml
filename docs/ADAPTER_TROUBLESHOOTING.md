# Adapter Troubleshooting

agent-yaml never speaks to a model directly — every task is one subprocess invocation of a CLI
(`opencode`, `claude`, `codex`, `pi`, `vtcode`, `agy`). Each adapter translates the same
`cli-agent-config` keys into that CLI's flags, and when a CLI changes its flags the adapter breaks in
ways that look like workflow bugs. This page is the symptom → cause → fix guide; for the full
key × harness support matrix see [CONFIG_SURFACES.md](CONFIG_SURFACES.md).

## First Move: Look at the argv

```bash
agent-yaml run tasks/my-workflow.yaml --debug
```

`--debug` prints the exact argv before each invocation (`[DEBUG] Task 'review': …`) and streams the
agent's output. Most adapter problems are visible immediately: an unexpected flag, a missing
`--model`, a prompt being passed as a flag.

```bash
agent-yaml validate tasks/my-workflow.yaml --cli-agent codex
```

`validate` also checks that the selected CLI exists on `PATH` (`CLINotFoundError`) and that the
`cli-agent` value is one of the five supported names (`UnsupportedCLIError`).

---

## Symptom → Cause → Fix

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Task "succeeds" instantly, does nothing | Prompt began with `-`, so the CLI printed help and exited 0. OpenCode's adapter guards this with `--`, others pass the prompt positionally. | Prefix the prompt with text, never a flag-like token (`Don't…`, `--…`). |
| `error: unknown option '--full-auto'` (codex) | You are on an adapter release older than codex-cli 0.153.4. | Update agent-yaml; the current adapter emits `--dangerously-bypass-approvals-and-sandbox`, `-c approval_policy=…`, and `--enable web_search`. |
| `mcp-servers` is ignored (claude) | Claude 2.x removed `--allowed-mcp-server-names`. | Scope servers in the MCP config file (`mcp-config-file`); the adapter warns instead of emitting a dead flag. |
| Agent sees none of the workflow `environment:` values (OpenCode) | Running against the shared background server instead of a private one. | Keep `standalone` unset/true (the adapter passes `--standalone` by default); do not set `server`. |
| Model ignored / provider error (OpenCode) | Model passed without `provider/` prefix. | Use `gateway/model-name`, `anthropic/claude-haiku-5-5`, … The adapter warns when `/` is missing. |
| `additional-dirs` silently ignored (OpenCode) | `opencode run` has no equivalent flag. | Configure directories in `opencode.json`; the adapter logs a warning. |
| `output-format: stream-json` ignored (OpenCode) | No equivalent. | Use `json`, or drop it; Claude supports `stream-json`. |
| Timeout kills a run mid-way | `cli-agent-config.timeout` is per task, and parallel loop workers share it. | Raise `timeout`, or split the task. |
| `codex exec` fails outside a git repo | Codex refuses to run without one. | Already handled: the adapter always passes `--skip-git-repo-check`. |
| Only one `additional-dirs` entry applies (codex) | Codex supports a single `-C`. | The adapter uses `additional-dirs[0]` and warns about the rest. |
| Missing CLI at validate time | Not installed / wrong PATH. | `which opencode` / `claude` / `codex` / `pi` / `vtcode` / `agy`; install or adjust PATH. |

---

## Per-Adapter Mapping

### OpenCode

| Config | Emission |
|--------|----------|
| *(default)* | `--standalone` (private server, inherits env and cwd) |
| `server: URL` | `--server URL` (replaces `--standalone`) |
| `skip-confirmations: true` | `--auto` |
| `model` | `--model provider/model[#variant]`; aliases `haiku-5.5`, `sonnet-5.5`, `opus-5.5` are translated |
| `agent` / `permissions: [x]` | `--agent x` (`agent` wins over `permissions`) |
| `output-format: json` | `--format json`; `default` and `text` add nothing |
| `session-id` / `continue` / `title` | `--session` / `--continue` / `--title` |
| `files` | `--file PATH` (repeated) |
| `log-level` | `--log-level all|trace|debug|info|warn|error|fatal|none` |
| `debug: true` | `--print-logs` (server logs while `--standalone` is active) |
| prompt | last argument, after `--` |
| `additional-dirs`, `mcp-servers`, `mcp-config-file` | **ignored with a warning** — configure in `opencode.json` |

Requires OpenCode v2.x (`--standalone`/`--auto` do not exist in v1).

### pi

| Config | Emission |
|--------|----------|
| *(always)* | `pi -p` (print mode, one prompt and exit) |
| `skip-confirmations: true` | `--approve` (trust project-local files) |
| `skip-confirmations: false` | `--no-approve` (explicit opt-out) |
| `provider` / `model` | `--provider` / `--model`; `provider/id` and `id:thinking` pass through |
| `thinking` | `--thinking off|minimal|low|medium|high|xhigh|max` |
| `tools` (list or string) | `--tools read,bash` |
| `no-tools` / `exclude-tools` | `--no-tools` / `--exclude-tools name,name` |
| `output-format: json` | `--mode json`; `text` is the default (`rpc` is a long-lived stdin protocol, not a one-shot output format) |
| `session-id` | `--session-id ID` (creates the session when it does not exist) |
| `continue: true` | `--continue` (session-id wins) |
| *(default when no session)* | `--no-session`, so each task is ephemeral |
| `session: true` | keep persistence instead of `--no-session` |
| `session-dir` | `--session-dir DIR` |
| `system-prompt` / `append-system-prompt` | `--system-prompt` / `--append-system-prompt` (repeated) |
| `extensions` / `skills` | `-e NAME` / `--skill PATH` (repeated) |
| `no-builtin-tools` / `no-context-files` / `no-mcp` | matching flags |
| `title` | `--name NAME` |
| `debug: true` | `--verbose` (accepted; pi only uses it in the interactive TUI) |
| `no-extensions: true` | `--no-extensions` |
| prompt | last argument, after `--` |
| `additional-dirs`, `mcp-servers`, `mcp-config-file` | **ignored with a warning** — tasks run in the workflow directory, MCP servers use `pi mcp` |

The adapter feeds an empty stdin instead of `/dev/null`, because print mode can hang on `/dev/null`
in some pi versions.

pi reads custom OpenAI-compatible providers from `~/.pi/agent/models.json`. That is the way to point
it at a gateway or a self-hosted endpoint:

```json
{
  "providers": {
    "gateway": {
      "baseUrl": "https://gateway.example.com/v1",
      "api": "openai-completions",
      "apiKey": "GATEWAY_API_KEY",
      "models": [{ "id": "vendor/model-name" }]
    }
  }
}
```

The provider name becomes the first segment of the model reference:

```yaml
cli-agent: pi
cli-agent-config:
  model: gateway/vendor/model-name
```

`apiKey` accepts an environment variable name, a `!command` that prints the key, or a literal value.
`--provider gateway --model vendor/model-name` is the same selection written as two flags.

Every option above is validated at parse time. Unknown keys, wrong types, and values pi would reject
(an unsupported `thinking` level or `output-format`) fail `agent-yaml validate` with the allowed
list, before any model call. `session-id` maps to `--session-id`, which creates the session when it
does not exist, unlike pi's `--session`, which fails with "No session found matching".

To re-check the mapping against live inference across every option, run the matrix:

```bash
PI_VALIDATION_MODEL=provider/model python scripts/validate_pi_params.py
```

It exercises each option (with behavior checks for tool allowlists, sessions, and the JSON output
mode), prints a pass/fail line per case, and fails when an option the validator accepts is missing
from the matrix.

### Claude

| Config | Emission |
|--------|----------|
| `skip-confirmations: true` | `--dangerously-skip-permissions` |
| `additional-dirs` | `--add-dir=DIR` (repeated) |
| `model` | `--model`; legacy `sonnet-4.5` / `opus-4` map to the `sonnet` / `opus` aliases |
| `mcp-config-file` | `--mcp-config PATH` |
| `permissions: [x]` | `--permission-mode x` (first entry wins) |
| `session-id` / `continue` | `--session-id` / `--continue` |
| `agent` / `title` / `effort` | `--agent` / `--name` / `--effort` |
| `tools` / `no-tools` / `exclude-tools` | `--tools` / `--tools ""` / `--disallowed-tools a,b` |
| `session: false` | `--no-session-persistence` |
| `json-schema` | `--json-schema` |
| `system-prompt` / `append-system-prompt` | `--system-prompt` / `--append-system-prompt` |
| `settings` / `max-budget` / `fallback-model` | `--settings` / `--max-budget-usd` / `--fallback-model` |
| `disable-slash-commands` | `--disable-slash-commands` |
| `output-format` | `--output-format` (`stream-json` supported) |
| `debug: true` | `--debug` |
| prompt | `--print PROMPT` |
| `mcp-servers` | **ignored with a warning**: Claude 2.x has no per-server CLI allow flag; scope servers in the MCP config file |

### vtcode

| Config | Emission |
|--------|----------|
| *(always)* | `vtcode exec` |
| `skip-confirmations: true` | `--dangerously-skip-permissions` |
| `provider` / `model` | `--provider` / `--model` |
| `output-format: json` | `--json` |
| `security-level` | `--security-level strict|moderate|permissive` |
| `max-tool-calls` | `--max-tool-calls N` |
| `tools` / `exclude-tools` | `--allowed-tools a,b` / `--disallowed-tools a,b` |
| `max-concurrent-ops` / `api-rate-limit` | matching flags |
| `config-overrides` / `log-level` / `color` | `-c k=v` (repeated) / `--log-level` / `--color` |
| `events-file` / `last-message-file` | `--events` / `--last-message-file` (exec only) |
| `session-id` / `continue` | `--session-id` / `exec resume --last` (or `exec resume ID`); resume lacks `--json`, `--events`, `--last-message-file` |
| `debug: true` / `quiet: true` | `--verbose` / `--quiet` |
| prompt | first positional argument, after the flags |
| `additional-dirs`, `mcp-servers`, `mcp-config-file` | **ignored with a warning** |

`vtcode exec` needs `[automation.full_auto]` in the workspace `vtcode.toml` (`enabled = true` plus an
`allowed_tools` allow-list), and non-interactive runs need `VTCODE_TRUST_WORKSPACE=full-auto`.

### vtcode with the Bifrost gateway

vtcode reads custom providers from the platform config directory's `vtcode.toml`, not the workspace
file:

- macOS: `~/Library/Application Support/com.vinhnx.vtcode/vtcode.toml`
- Linux: `~/.config/vtcode/vtcode.toml`

```toml
[[custom_providers]]
name = "bifrost"
display_name = "Bifrost"
base_url = "https://bifrost.roboalch.com/v1"
api_key_env = "BIFROST_VK_MASTER"
model = "chunglet/deepseek-v4.1-flash"
models = ["chunglet/deepseek-v4.1-flash"]
```

`--provider` is validated against the built-in providers plus everything in `custom_providers`, so
the provider has to come from that file. A `[[custom_providers]]` block in a workspace `vtcode.toml`
is ignored and `--provider bifrost` fails with `Unknown provider`. Export the variable named by
`api_key_env` before running.

```yaml
cli-agent: vtcode
cli-agent-config:
  provider: bifrost
  model: chunglet/deepseek-v4.1-flash
  skip-confirmations: true
```

The live matrix runs every option through real inference:

```bash
python scripts/validate_vtcode_params.py
```

It defaults to `bifrost/chunglet/deepseek-v4.1-flash`, reads `BIFROST_VK_MASTER` from the
environment or gopass, builds a workspace with the required `[automation.full_auto]` config, and
checks each option, including a tool-driven file write, NDJSON output, and session resume.

### Antigravity

| Config | Emission |
|--------|----------|
| *(always)* | `agy -p PROMPT` (headless print mode) |
| `skip-confirmations: true` | `--dangerously-skip-permissions` |
| `model` / `effort` / `agent` | `--model` / `--effort low|medium|high|xhigh|max` / `--agent` |
| `permissions: [x]` | `--mode plan|accept-edits|auto` (yolo/never → `--dangerously-skip-permissions`) |
| `output-format` | `--output-format text|json|stream-json` |
| `session-id` / `continue` | `--conversation ID` / `--continue` |
| `sandbox: true` | `--sandbox` |
| `additional-dirs` | `--add-dir DIR` (repeated) |
| `timeout` | `--print-timeout Ns` (the executor still enforces its own limit) |
| `json-schema` / `settings` / `project` | `--json-schema` / `--settings` / `--project` |
| `log-file` / `disable-slash-commands` | `--log-file` / `--disable-slash-commands` |
| `mcp-servers`, `mcp-config-file` | **ignored with a warning** (add servers with `agy mcp add` or in `~/.gemini/antigravity-cli/settings.json`) |

`agy` authenticates either through a signed-in Google account or through a Gemini API key:

```json
// ~/.gemini/antigravity-cli/settings.json
{"modelProvider": "gemini"}
```

```bash
export GEMINI_API_KEY=...
```

`--mode auto` is rejected on API-key accounts ("not available for this account") and, even when
available, auto-denies `write_file` in headless mode. That is why `skip-confirmations` maps to
`--dangerously-skip-permissions`, which does let the agent write.

Model slugs come from `agy models` and differ by account and auth mode: they often encode the effort
level (`gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`) and some accounts
also get `claude-sonnet-4-6` or `gpt-oss-120b-medium`. `--effort` is only accepted for models that
expose it separately; pairing it with a model that does not raises
`error: invalid model selection ... --effort is not supported for model ...`.

Live matrix (real inference through either auth path):

```bash
python scripts/validate_antigravity_params.py
```

It defaults to `gemini-3.8-flash`, reads `GEMINI_API_KEY` from the environment or gopass, and
exercises every option including a tool-driven file write, both JSON output modes, and conversation
resume. The `agent` option is not exercised: it needs a named agent from `agy agents`, and a fresh
install has none.

### Codex

| Config | Emission |
|--------|----------|
| *(always)* | `codex exec --skip-git-repo-check` |
| `skip-confirmations: true` | `--dangerously-bypass-approvals-and-sandbox` |
| `additional-dirs` | `--add-dir DIR` (repeated; writable alongside the root) |
| `permissions: [x]` | `plan`/`read-only`/`workspace-write`/`danger-full-access` → `--sandbox`; `untrusted|on-failure|on-request|never` → `-c approval_policy=x` |
| `sandbox` | `--sandbox read-only|workspace-write|danger-full-access` |
| `session-id` / `continue` | `codex exec resume ID` / `codex exec resume --last` (resume has no `--sandbox`/`--add-dir`) |
| `provider` | `--oss --local-provider ollama|lmstudio` |
| `session: false` | `--ephemeral` |
| `effort` | `-c model_reasoning_effort=x` |
| `output-format: json` | `--json` |
| `web-search: true` | `--enable web_search` |
| `json-schema` | `--output-schema FILE` |
| `last-message-file` / `images` | `-o FILE` / `-i FILE` (repeated) |
| `enable` | `--enable FEATURE` (repeated) |
| `ignore-user-config` / `ignore-rules` | matching flags |
| `config-overrides` | `-c k=v` (repeated) |
| `debug: true` | **ignored with a warning**: no headless debug flag |
| prompt | positional, last argument |

---

## Known-Breaking Flags (pin your CLI versions)

These are verified against the binaries in use when this was written and are recorded in the repo's
`AGENTS.md` limitations:

| Adapter | Flag | Status |
|---------|------|--------|
| `codex` | `--full-auto`, `-a`, `--search` | removed in codex-cli 0.153.4; the adapter now emits the verified replacements above |
| `claude` | `--allowed-mcp-server-names` | removed in Claude 2.x; the adapter no longer emits it and warns instead |
| `opencode` | `additional-dirs`, `mcp-servers`, `mcp-config-file`, `output-format: stream-json` | never supported — warning only |
| `pi` | `--mode rpc` | not an output format; RPC needs a long-lived stdin, so the adapter rejects it |

**`raw-args` is the escape hatch.** Every adapter appends `raw-args` verbatim after the translated
flags and before the prompt/producer flag, so a new CLI flag can be used without touching the adapter:

```yaml
cli-agent: codex
cli-agent-config:
  raw-args: ["--sandbox", "workspace-write"]
```

---

## Testing an Adapter Change

1. **Dry run with debug** — `agent-yaml run examples/11-codex.yaml --debug` shows argv without
   spending tokens (dry run prints the command without executing).
2. **Validate the agent name** — `agent-yaml validate <file> --cli-agent <name>`.
3. **Check the unit tests** — each adapter has argv assertions in `tests/unit/`; changing a flag means
   changing its expected argv there.
4. **Live tier, real binary** — `pytest --live tests/live -n 4` runs through OpenCode using the the gateway
   gateway key (`op read "op://Agents/GATEWAY_KEY/credential"`). A 401 means the key is stale,
   not that the adapter is broken.
5. **Never fake a credential** to make a live test pass; fix or refresh the secret.

---

## Adding a New Adapter

1. Subclass `BaseAdapter` in `agent_yaml/adapters/` and implement `build_command()` and
   `check_available()` (`agent_yaml/adapters/base.py`).
2. Register it in `adapter_map` inside `agent_yaml/adapters/__init__.py`.
3. Add the name to `VALID_CLI_AGENTS` in `agent_yaml/validator.py:35` — otherwise `validate` rejects it.
4. Add argv unit tests and an `examples/NN-<agent>.yaml` so CI dry-runs it.
5. Document the mapping table here and in `spec/ADAPTER_SPEC.md`.

---

## Limitations

1. **`cli-agent-config` is only partly portable.** `timeout`, `model`, `raw-args`, `debug` and
   `skip-confirmations` exist everywhere; `mcp-servers`, `output-format`, `web-search`, `extensions`,
   `checkpointing`, `telemetry` and `session-id` are per-CLI.
2. **`mcp-servers` is currently unsafe for `claude`** — it emits a Gemini-only flag.
3. **`additional-dirs` is a no-op for OpenCode** and single-valued for Codex.
4. **No capability negotiation.** The adapter emits flags unconditionally for the requested config, so
   an older or newer CLI fails at invocation time rather than at validation time.
5. **`spec/ADAPTER_SPEC.md` lags the code** in places; the adapter sources are authoritative.

---

## Best Practices

1. **Pin CLI versions per machine** and re-run `agent-yaml run … --debug` after upgrading one.
2. **Prefer the lowest common denominator in shared workflows** (`model`, `timeout`,
   `skip-confirmations`), and put CLI-specific keys in a wrapper workflow or `raw-args`.
3. **Override at the CLI, not in the file**, when switching agents: `--cli-agent opencode --model
   gateway/model-name`.
4. **Read the warnings.** Ignored keys log a warning but do not fail the run, which is easy to miss in
   a long output; `--verbose` keeps them visible.

---

Source of truth: `agent_yaml/adapters/*.py` (per-CLI translation), `agent_yaml/adapters/__init__.py` (registry),
`agent_yaml/executor.py` (argv construction, timeouts), `AGENTS.md` (known-breaking flags).
Related: `spec/ADAPTER_SPEC.md`, `examples/11-codex.yaml`,
`examples/40-pi.yaml`, `examples/41-vtcode.yaml`, `examples/42-antigravity.yaml`.
