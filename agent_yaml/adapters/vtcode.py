"""
vtcode CLI adapter (VT Code headless `vtcode exec`).

Maps generic configurations onto vtcode's flags:
- skip-confirmations: true → --dangerously-skip-permissions
- model / provider → --model / --provider
- output-format: "json" → --json (newline-delimited events)
- debug: true → --verbose
- quiet: true → --quiet (suppress non-essential output)
- security-level: strict|moderate|permissive → --security-level
- max-tool-calls: N → --max-tool-calls N
- session-id: "abc" → --session-id abc
- continue: true → --continue (most recent session)
- raw-args: [...] → appended after translated flags, before the prompt
- timeout → subprocess timeout (handled by the executor, NOT a CLI arg)

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
        cmd = ["vtcode", "exec"]

        # 1. provider and model
        provider = task_config.get("provider")
        if provider:
            cmd.extend(["--provider", provider])

        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        # 2. skip-confirmations → auto-approve promptable actions
        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-skip-permissions")

        # 3. output-format: json → --json (text is the default)
        output_format = task_config.get("output-format")
        if output_format == "json":
            cmd.append("--json")
        elif output_format and output_format != "text":
            logger.warning(f"vtcode does not support output-format '{output_format}'")

        # 4. security level for tool execution
        security_level = task_config.get("security-level")
        if security_level:
            cmd.extend(["--security-level", security_level])

        # 5. tool-call budget
        max_tool_calls = task_config.get("max-tool-calls")
        if max_tool_calls is not None:
            cmd.extend(["--max-tool-calls", str(max_tool_calls)])

        # 6. session handling
        session_id = task_config.get("session-id")
        if session_id:
            cmd.extend(["--session-id", session_id])
        elif task_config.get("continue"):
            cmd.append("--continue")

        # 7. logging
        if task_config.get("debug"):
            cmd.append("--verbose")
        if task_config.get("quiet"):
            cmd.append("--quiet")

        # 8. Not supported by the vtcode CLI
        for unsupported in ("additional-dirs", "mcp-servers", "mcp-config-file"):
            if task_config.get(unsupported):
                logger.warning(
                    f"vtcode adapter ignores '{unsupported}'; run in the workspace directory "
                    "and manage MCP servers with `vtcode mcp`"
                )

        # 9. raw-args: passthrough
        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # 10. Prompt last, after "--" so a leading "-" is never parsed as a flag
        cmd.extend(["--", prompt])

        return cmd

    def check_available(self):
        """
        Check if the vtcode CLI is available in PATH.

        Returns:
            bool: True if the `vtcode` executable is found
        """
        return shutil.which("vtcode") is not None
