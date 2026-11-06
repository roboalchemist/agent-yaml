"""
vtcode CLI adapter (VT Code headless `vtcode exec`).

Maps generic configurations onto vtcode's flags:
- skip-confirmations → --dangerously-skip-permissions
- model / provider → --model / --provider
- tools / exclude-tools → --allowed-tools / --disallowed-tools (comma-joined)
- output-format: json → --json
- debug / quiet → --verbose / --quiet
- security-level / max-tool-calls / max-concurrent-ops / api-rate-limit → matching flags
- config-overrides → -c (repeated); log-level / color → matching flags
- events-file / last-message-file → --events / --last-message-file (exec only)
- session-id → --session-id; continue → `vtcode exec resume --last` (or `resume <id>`)
- raw-args → appended before the prompt
- prompt: first positional argument

`vtcode exec resume` lacks --json, --events, and --last-message-file; those drop with a
warning when continuing. `additional-dirs`, `mcp-servers`, and `mcp-config-file` are ignored
with a hint (workspace is the executor cwd; MCP uses `vtcode mcp`).

Requirements: `[automation.full_auto]` in the workspace `vtcode.toml` and
`VTCODE_TRUST_WORKSPACE=full-auto` for non-interactive runs.
"""

import logging

logger = logging.getLogger(__name__)

from .base import (
    BaseAdapter,
    BOOL,
    ENUM,
    IGNORED,
    INT,
    LIST,
    NUMBER,
    STR,
    STR_OR_LIST,
)

SECURITY_LEVELS = ("strict", "moderate", "permissive")
LOG_LEVELS = ("error", "warn", "info", "debug", "trace")
COLORS = ("auto", "always", "never")


class VTCodeAdapter(BaseAdapter):
    """Adapter for the VT Code CLI (`vtcode exec`)."""

    name = "vtcode"
    executables = ("vtcode",)
    install_hint = "vtcode"
    prompt_style = "positional"

    option_spec = {
        "model": STR,
        "provider": STR,
        "session-id": STR,
        "output-format": ENUM("text", "json"),
        "security-level": ENUM(*SECURITY_LEVELS),
        "max-tool-calls": INT,
        "max-concurrent-ops": INT,
        "api-rate-limit": INT,
        "tools": STR_OR_LIST,
        "exclude-tools": STR_OR_LIST,
        "config-overrides": LIST,
        "log-level": ENUM(*LOG_LEVELS),
        "color": ENUM(*COLORS),
        "events-file": STR,
        "last-message-file": STR,
        "skip-confirmations": BOOL,
        "continue": BOOL,
        "debug": BOOL,
        "quiet": BOOL,
        "timeout": NUMBER,
        "raw-args": LIST,
        "additional-dirs": IGNORED(
            "run in the workspace directory and manage MCP servers with `vtcode mcp`"
        ),
        "mcp-servers": IGNORED(
            "run in the workspace directory and manage MCP servers with `vtcode mcp`"
        ),
        "mcp-config-file": IGNORED(
            "run in the workspace directory and manage MCP servers with `vtcode mcp`"
        ),
    }

    live_exempt = {
        "raw-args": "verbatim passthrough; covered by the adapter unit tests",
    }

    def build_command(self, task_config, prompt):
        """Build a `vtcode exec` command from task configuration."""
        resume = bool(task_config.get("continue"))
        session_id = task_config.get("session-id")
        if resume and session_id:
            cmd = ["vtcode", "exec", "resume", session_id]
        elif resume:
            cmd = ["vtcode", "exec", "resume", "--last"]
        else:
            cmd = ["vtcode", "exec"]

        provider = task_config.get("provider")
        if provider:
            cmd.extend(["--provider", provider])

        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-skip-permissions")

        tools = task_config.get("tools")
        if tools:
            cmd.extend(["--allowed-tools", self.join_list(tools)])

        exclude_tools = task_config.get("exclude-tools")
        if exclude_tools:
            cmd.extend(["--disallowed-tools", self.join_list(exclude_tools)])

        output_format = task_config.get("output-format")
        if output_format == "json":
            if resume:
                self.logger.warning("vtcode exec resume does not support --json; ignoring output-format")
            else:
                cmd.append("--json")

        security_level = task_config.get("security-level")
        if security_level:
            cmd.extend(["--security-level", security_level])

        for key, flag in (
            ("max-tool-calls", "--max-tool-calls"),
            ("max-concurrent-ops", "--max-concurrent-ops"),
            ("api-rate-limit", "--api-rate-limit"),
        ):
            value = task_config.get(key)
            if value is not None:
                cmd.extend([flag, str(value)])

        for override in task_config.get("config-overrides", []):
            cmd.extend(["-c", override])

        log_level = task_config.get("log-level")
        if log_level:
            cmd.extend(["--log-level", log_level])

        color = task_config.get("color")
        if color:
            cmd.extend(["--color", color])

        events_file = task_config.get("events-file")
        if events_file:
            if resume:
                self.logger.warning("vtcode exec resume does not support --events; ignoring events-file")
            else:
                cmd.extend(["--events", events_file])

        last_message_file = task_config.get("last-message-file")
        if last_message_file:
            if resume:
                self.logger.warning(
                    "vtcode exec resume does not support --last-message-file; "
                    "ignoring last-message-file"
                )
            else:
                cmd.extend(["--last-message-file", last_message_file])

        if session_id and not resume:
            cmd.extend(["--session-id", session_id])

        if task_config.get("debug"):
            cmd.append("--verbose")
        if task_config.get("quiet"):
            cmd.append("--quiet")

        self.warn_ignored(task_config)

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        return self.append_prompt(cmd, prompt)
