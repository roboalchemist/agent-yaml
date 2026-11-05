"""
Claude CLI adapter.

Maps generic configurations to Claude-specific CLI arguments:
- skip-confirmations: true → --dangerously-skip-permissions
- additional-dirs: ["/tmp"] → --add-dir="/tmp"
- timeout: 3600 → subprocess timeout (not CLI arg)
- mcp-config-file: "..." → --mcp-config "..."
- tools: "default" (default) → --tools "default" (enable all tools in print mode)
- output-format: "stream-json" → --output-format "stream-json" (streaming output)

CLI tool: claude-code or claude (detection via which)

Default behavior: Uses --print mode with tools enabled for non-interactive agentic execution.

Reference: spec/ADAPTER_SPEC.md for complete Claude mappings.
"""

import shutil

from .base import BaseAdapter


class ClaudeAdapter(BaseAdapter):
    """Adapter for Claude CLI (claude-code)."""

    # Model name translation mapping
    MODEL_MAPPING = {
        "sonnet-4.5": "claude-sonnet-4-5-20250929",
        "opus-4": "claude-opus-4",
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
        # Start with base command - check both "claude" and "claude-code"
        cmd = []
        if shutil.which("claude-code"):
            cmd.append("claude-code")
        elif shutil.which("claude"):
            cmd.append("claude")
        else:
            cmd.append("claude")  # Default, will fail in check_available

        # Process config options in order per spec

        # 1. skip-confirmations: true → --dangerously-skip-permissions
        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-skip-permissions")

        # 2. additional-dirs: ["/tmp"] → --add-dir="/tmp" (repeat for each)
        additional_dirs = task_config.get("additional-dirs", [])
        for directory in additional_dirs:
            cmd.append(f"--add-dir={directory}")

        # 3. model: "sonnet-4.5" → --model "claude-sonnet-4-5-20250929" (with translation)
        model = task_config.get("model")
        if model:
            # Translate generic model name to Claude-specific identifier
            translated_model = self.MODEL_MAPPING.get(model, model)
            cmd.extend(["--model", translated_model])

        # 4. debug: true → --debug
        if task_config.get("debug"):
            cmd.append("--debug")

        # 5. tools: "default" → --tools "default" (enable tools in print mode)
        # Default to "default" which enables all tools for agentic execution
        tools = task_config.get("tools", "default")
        if tools:
            cmd.extend(["--tools", tools])

        # 6. output-format: "stream-json" → --output-format "stream-json"
        # Default to "text" for simplicity, use "stream-json" in debug mode for streaming
        output_format = task_config.get("output-format")
        if output_format is None:
            # Auto-select: stream-json in debug mode, text otherwise
            output_format = "stream-json" if task_config.get("debug") else "text"

        # stream-json requires --verbose flag
        if output_format == "stream-json":
            cmd.append("--verbose")
            cmd.extend(["--output-format", "stream-json"])
        elif output_format != "text":
            cmd.extend(["--output-format", output_format])

        # 7. session-id: "id" → --session-id "id"
        session_id = task_config.get("session-id")
        if session_id:
            cmd.extend(["--session-id", session_id])

        # 8. mcp-servers: [notion] → --allowed-mcp-server-names notion
        mcp_servers = task_config.get("mcp-servers", [])
        if mcp_servers:
            cmd.append("--allowed-mcp-server-names")
            cmd.extend(mcp_servers)

        # 9. mcp-config-file: "path" → --mcp-config "path"
        mcp_config_file = task_config.get("mcp-config-file")
        if mcp_config_file:
            cmd.extend(["--mcp-config", mcp_config_file])

        # 10. permissions: ["plan"] → --permission-mode plan
        permissions = task_config.get("permissions", [])
        if permissions:
            # Take first permission mode
            cmd.extend(["--permission-mode", permissions[0]])

        # 11. raw-args: [...] → append directly at end
        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # 12. timeout: 3600 → store but DON'T add to CLI args (used for subprocess timeout)
        # Note: timeout is handled by executor, not part of CLI command

        # 13. Add prompt in print mode (non-interactive agentic execution)
        # Always use --print mode with tools enabled for reliable non-interactive execution
        cmd.extend(["--print", prompt])

        return cmd

    def check_available(self):
        """
        Check if Claude CLI is available in PATH.

        Checks for both "claude" and "claude-code" executables.

        Returns:
            bool: True if tool is available
        """
        return shutil.which("claude-code") is not None or shutil.which("claude") is not None
