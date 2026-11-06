"""
vtcode CLI adapter (VT Code headless `vtcode exec`).

Maps generic configurations onto vtcode's flags:
- skip-confirmations: true → --dangerously-skip-permissions
- model / provider → --model / --provider
- tools: [..] → --allowed-tools a,b
- exclude-tools: [..] → --disallowed-tools a,b
- output-format: "json" → --json (newline-delimited events)
- debug: true → --verbose
- quiet: true → --quiet (suppress non-essential output)
- security-level: strict|moderate|permissive → --security-level
- max-tool-calls: N → --max-tool-calls N
- max-concurrent-ops / api-rate-limit → matching flags
- config-overrides: ["k=v", ..] → -c k=v (repeated)
- log-level: "debug" → --log-level debug
- color: auto|always|never → --color
- events-file: path → --events path
- last-message-file: path → --last-message-file path
- session-id: "abc" → --session-id abc
- continue: true → `vtcode exec resume --last` (or `resume abc` when session-id is set)
- raw-args: [...] → appended after translated flags, before the prompt
- timeout → subprocess timeout (handled by the executor, NOT a CLI arg)

`vtcode exec resume` lacks --json, --events, and --last-message-file; when resuming, those are
warned and dropped.

Unsupported (warning logged, value ignored): additional-dirs, mcp-servers, mcp-config-file.
vtcode runs in the workspace passed to `exec`, and MCP servers are managed with `vtcode mcp`.

Requirements: `vtcode exec` needs `[automation.full_auto]` in the workspace `vtcode.toml`
(`enabled = true`, plus an `allowed_tools` allow-list). Non-interactive runs also need
`VTCODE_TRUST_WORKSPACE=full-auto` unless the workspace was trusted interactively.

CLI tool: vtcode (https://github.com/vinhnx/vtcode)

Reference: spec/ADAPTER_SPEC.md for the cross-adapter mapping tables.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


def _comma_join(value):
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return value


class VTCodeAdapter(BaseAdapter):
    """Adapter for the VT Code CLI (`vtcode exec`)."""

    def __init__(self, tool_config=None):
        """Initialize VT Code adapter."""
        super().__init__("vtcode", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build a `vtcode exec` command from task configuration.

        Args:
            task_config: Task configuration dict (merged cli-agent-config)
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
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
            cmd.extend(["--allowed-tools", _comma_join(tools)])

        exclude_tools = task_config.get("exclude-tools")
        if exclude_tools:
            cmd.extend(["--disallowed-tools", _comma_join(exclude_tools)])

        output_format = task_config.get("output-format")
        if output_format == "json":
            if resume:
                logger.warning("vtcode exec resume does not support --json; ignoring output-format")
            else:
                cmd.append("--json")
        elif output_format and output_format != "text":
            logger.warning(f"vtcode does not support output-format '{output_format}'")

        security_level = task_config.get("security-level")
        if security_level:
            cmd.extend(["--security-level", security_level])

        max_tool_calls = task_config.get("max-tool-calls")
        if max_tool_calls is not None:
            cmd.extend(["--max-tool-calls", str(max_tool_calls)])

        max_concurrent_ops = task_config.get("max-concurrent-ops")
        if max_concurrent_ops is not None:
            cmd.extend(["--max-concurrent-ops", str(max_concurrent_ops)])

        api_rate_limit = task_config.get("api-rate-limit")
        if api_rate_limit is not None:
            cmd.extend(["--api-rate-limit", str(api_rate_limit)])

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
                logger.warning("vtcode exec resume does not support --events; ignoring events-file")
            else:
                cmd.extend(["--events", events_file])

        last_message_file = task_config.get("last-message-file")
        if last_message_file:
            if resume:
                logger.warning(
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

        for unsupported in ("additional-dirs", "mcp-servers", "mcp-config-file"):
            if task_config.get(unsupported):
                logger.warning(
                    f"vtcode adapter ignores '{unsupported}'; run in the workspace directory "
                    "and manage MCP servers with `vtcode mcp`"
                )

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # The prompt is the first positional argument. vtcode's `--` separates the
        # workspace, not the prompt, so `-- PROMPT` is parsed as a workspace path.
        # A leading dash is guarded with a space.
        if prompt.startswith("-"):
            logger.warning(
                "vtcode adapter: prompt starts with '-'; prefixing a space so it is "
                "not parsed as a flag"
            )
            prompt = " " + prompt
        cmd.append(prompt)

        return cmd

    def check_available(self):
        """
        Check if the vtcode CLI is available in PATH.

        Returns:
            bool: True if the `vtcode` executable is found
        """
        return shutil.which("vtcode") is not None
