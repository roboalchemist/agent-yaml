"""
Gemini CLI adapter.

Maps generic configurations to Gemini-specific CLI arguments:
- skip-confirmations: true → --yolo or --approval-mode yolo
- additional-dirs: ["/tmp"] → --include-directories /tmp (space-separated)
- model: pass through as-is (no translation)
- permissions: ["plan"] → --approval-mode plan
- mcp-servers: [notion] → --allowed-mcp-server-names notion
- extensions: [...] → --extensions ...
- checkpointing: true → --checkpointing
- screen-reader: true → --screen-reader
- telemetry: true → --telemetry
- web-search: true → BUILT-IN (no flag needed)
- output-format: "json" → --output-format json

Unsupported features (log warning):
- session-id
- mcp-config-file

CLI tool: gemini

Reference: spec/ADAPTER_SPEC.md for complete Gemini mappings.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


class GeminiAdapter(BaseAdapter):
    """Adapter for Gemini CLI."""

    def __init__(self, tool_config=None):
        """Initialize Gemini adapter."""
        super().__init__("gemini", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build Gemini CLI command from task configuration.

        Args:
            task_config: Task configuration dict
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
        # Start with base command
        cmd = ["gemini"]

        # Process config options in order per spec

        # 1. skip-confirmations: true → --yolo
        if task_config.get("skip-confirmations"):
            cmd.append("--yolo")

        # 2. additional-dirs: ["/tmp"] → --include-directories /tmp (space-separated)
        additional_dirs = task_config.get("additional-dirs", [])
        if additional_dirs:
            cmd.append("--include-directories")
            cmd.extend(additional_dirs)

        # 3. model: pass through as-is (no translation)
        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        # 4. debug: true → --debug
        if task_config.get("debug"):
            cmd.append("--debug")

        # 5. output-format: "json" → --output-format json
        output_format = task_config.get("output-format")
        if output_format:
            cmd.extend(["--output-format", output_format])

        # 6. session-id: NOT SUPPORTED
        if task_config.get("session-id"):
            logger.warning("Gemini does not support session-id configuration")

        # 7. mcp-servers: [notion] → --allowed-mcp-server-names notion
        mcp_servers = task_config.get("mcp-servers", [])
        if mcp_servers:
            cmd.append("--allowed-mcp-server-names")
            cmd.extend(mcp_servers)

        # 8. mcp-config-file: NOT SUPPORTED
        if task_config.get("mcp-config-file"):
            logger.warning("Gemini does not support mcp-config-file configuration")

        # 9. permissions: ["plan"] → --approval-mode plan
        permissions = task_config.get("permissions", [])
        if permissions:
            # Take first permission mode
            cmd.extend(["--approval-mode", permissions[0]])

        # 10. extensions: [...] → --extensions ...
        extensions = task_config.get("extensions", [])
        if extensions:
            cmd.append("--extensions")
            cmd.extend(extensions)

        # 11. checkpointing: true → --checkpointing
        if task_config.get("checkpointing"):
            cmd.append("--checkpointing")

        # 12. telemetry: true → --telemetry
        if task_config.get("telemetry"):
            cmd.append("--telemetry")

        # 13. screen-reader: true → --screen-reader
        if task_config.get("screen-reader"):
            cmd.append("--screen-reader")

        # 14. web-search: BUILT-IN (no flag needed)
        # web-search is built-in for Gemini, don't add any flag

        # 15. raw-args: passthrough (no translation)
        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # 16. Prompt goes at the end with -p flag
        cmd.extend(["-p", prompt])

        return cmd

    def check_available(self):
        """
        Check if Gemini CLI is available in PATH.

        Checks for "gemini" executable.

        Returns:
            bool: True if tool is available
        """
        return shutil.which("gemini") is not None
