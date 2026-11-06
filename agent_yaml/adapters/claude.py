"""
Claude CLI adapter.

Maps generic configurations to Claude-specific CLI arguments:
- skip-confirmations: true → --dangerously-skip-permissions
- additional-dirs: ["/tmp"] → --add-dir="/tmp" (repeated)
- model: legacy aliases translated to current CLI aliases (sonnet-4.5 → sonnet)
- debug: true → --debug
- tools: "default" (default) → --tools "default"; no-tools → --tools ""
- exclude-tools: [...] → --disallowed-tools a,b
- output-format: "stream-json" → --verbose --output-format stream-json
- session-id: "uuid" → --session-id uuid; continue → --continue
- session: false → --no-session-persistence
- agent: "build" → --agent build
- title: "..." → --name "..."
- effort: "high" → --effort high
- mcp-config-file: "..." → --mcp-config "..."
- permissions: [mode] → --permission-mode mode (first entry wins)
- json-schema: <json|path> → --json-schema ...
- system-prompt / append-system-prompt → matching flags
- settings: <json|path> → --settings ...
- max-budget: 2.5 → --max-budget-usd 2.5
- fallback-model: "sonnet" → --fallback-model sonnet
- disable-slash-commands: true → --disable-slash-commands
- raw-args: [...] → appended after the translated flags
- timeout: 3600 → subprocess timeout (not CLI arg)

`mcp-servers` has no per-server flag in Claude 2.x (`--allowed-mcp-server-names` was removed);
scope servers in the MCP config file instead. It warns and is ignored.

CLI tool: claude-code or claude (detection via which)

Default behavior: Uses --print mode with tools enabled for non-interactive agentic execution.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


class ClaudeAdapter(BaseAdapter):
    """Adapter for Claude CLI (claude-code)."""

    # Legacy generic names mapped to the aliases the current CLI documents.
    MODEL_MAPPING = {
        "sonnet-4.5": "sonnet",
        "opus-4": "opus",
    }

    def __init__(self, tool_config=None):
        """Initialize Claude adapter."""
        super().__init__("claude", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build Claude CLI command from task configuration.

        Args:
            task_config: Task configuration dict
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
        cmd = []
        if shutil.which("claude-code"):
            cmd.append("claude-code")
        elif shutil.which("claude"):
            cmd.append("claude")
        else:
            cmd.append("claude")  # Default, will fail in check_available

        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-skip-permissions")

        for directory in task_config.get("additional-dirs", []):
            cmd.append(f"--add-dir={directory}")

        model = task_config.get("model")
        if model:
            cmd.extend(["--model", self.MODEL_MAPPING.get(model, model)])

        if task_config.get("debug"):
            cmd.append("--debug")

        if task_config.get("no-tools"):
            cmd.extend(["--tools", ""])
        else:
            tools = task_config.get("tools", "default")
            if tools:
                cmd.extend(["--tools", tools])

        exclude_tools = task_config.get("exclude-tools")
        if exclude_tools:
            if isinstance(exclude_tools, (list, tuple)):
                exclude_tools = ",".join(str(tool) for tool in exclude_tools)
            cmd.extend(["--disallowed-tools", exclude_tools])

        output_format = task_config.get("output-format")
        if output_format is None:
            output_format = "stream-json" if task_config.get("debug") else "text"
        if output_format == "stream-json":
            cmd.append("--verbose")
            cmd.extend(["--output-format", "stream-json"])
        elif output_format != "text":
            cmd.extend(["--output-format", output_format])

        session_id = task_config.get("session-id")
        if session_id:
            cmd.extend(["--session-id", session_id])
        elif task_config.get("continue"):
            cmd.append("--continue")
        if "session" in task_config and not task_config["session"]:
            cmd.append("--no-session-persistence")

        agent = task_config.get("agent")
        if agent:
            cmd.extend(["--agent", agent])

        title = task_config.get("title")
        if title:
            cmd.extend(["--name", title])

        effort = task_config.get("effort")
        if effort:
            cmd.extend(["--effort", effort])

        mcp_servers = task_config.get("mcp-servers", [])
        if mcp_servers:
            logger.warning(
                "claude has no per-server CLI allow flag; configure mcp-servers inside the "
                "MCP config file (see mcp-config-file) instead"
            )

        mcp_config_file = task_config.get("mcp-config-file")
        if mcp_config_file:
            cmd.extend(["--mcp-config", mcp_config_file])

        permissions = task_config.get("permissions", [])
        if permissions:
            if len(permissions) > 1:
                logger.warning(
                    f"claude uses only the first permission mode; ignoring {permissions[1:]}"
                )
            cmd.extend(["--permission-mode", permissions[0]])

        for key, flag in (
            ("json-schema", "--json-schema"),
            ("system-prompt", "--system-prompt"),
            ("settings", "--settings"),
            ("fallback-model", "--fallback-model"),
        ):
            value = task_config.get(key)
            if value:
                cmd.extend([flag, str(value)])

        append_prompts = task_config.get("append-system-prompt")
        if append_prompts:
            if isinstance(append_prompts, str):
                append_prompts = [append_prompts]
            for extra in append_prompts:
                cmd.extend(["--append-system-prompt", extra])

        max_budget = task_config.get("max-budget")
        if max_budget is not None:
            cmd.extend(["--max-budget-usd", str(max_budget)])

        if task_config.get("disable-slash-commands"):
            cmd.append("--disable-slash-commands")

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        cmd.extend(["--print", prompt])

        return cmd

    def check_available(self):
        """
        Check if Claude CLI is available in PATH.

        Returns:
            bool: True if tool is available
        """
        return shutil.which("claude-code") is not None or shutil.which("claude") is not None
