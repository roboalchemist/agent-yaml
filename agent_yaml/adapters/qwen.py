"""
Qwen CLI adapter.

Maps generic configurations to Qwen-specific CLI arguments:
- skip-confirmations: true → --yolo
- additional-dirs: ["/tmp"] → --include-directories /tmp (space-separated)
- model: "qwen3-coder" → --model "qwen3-coder-plus"
- permissions: ["plan"] → --approval-mode plan
- mcp-servers: [notion] → --allowed-mcp-server-names notion
- extensions: [...] → --extensions ...
- checkpointing: true → --checkpointing
- screen-reader: true → --screen-reader
- telemetry: true → --telemetry
- web-search: true with search-api-key → --tavily-api-key "sk-..."

Unsupported features (log warning):
- output-format
- session-id
- mcp-config-file

CLI tool: qwen

Reference: spec/ADAPTER_SPEC.md lines 52-86 for Qwen mappings.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


class QwenAdapter(BaseAdapter):
    """Adapter for Qwen CLI."""

    # Model name translation mapping
    MODEL_MAPPING = {
        "qwen3-coder": "qwen3-coder-plus",
    }

    def __init__(self, tool_config=None):
        """Initialize Qwen adapter."""
        super().__init__("qwen", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build Qwen CLI command from task configuration.

        Args:
            task_config: Task configuration dict
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
        # Start with base command
        cmd = ["qwen"]

        # Process config options in order per spec

        # 1. skip-confirmations: true → --yolo
        if task_config.get("skip-confirmations"):
            cmd.append("--yolo")

        # 2. additional-dirs: ["/tmp"] → --include-directories /tmp (space-separated)
        additional_dirs = task_config.get("additional-dirs", [])
        if additional_dirs:
            cmd.append("--include-directories")
            cmd.extend(additional_dirs)

        # 3. model: "qwen3-coder" → --model "qwen3-coder-plus" (with translation)
        model = task_config.get("model")
        if model:
            # Translate generic model name to Qwen-specific identifier
            translated_model = self.MODEL_MAPPING.get(model, model)
            cmd.extend(["--model", translated_model])

        # 4. debug: true → --debug
        if task_config.get("debug"):
            cmd.append("--debug")

        # 5. output-format: NOT SUPPORTED
        if task_config.get("output-format"):
            logger.warning("Qwen does not support output-format configuration")

        # 6. session-id: NOT SUPPORTED
        if task_config.get("session-id"):
            logger.warning("Qwen does not support session-id configuration")

        # 7. mcp-servers: [notion] → --allowed-mcp-server-names notion
        mcp_servers = task_config.get("mcp-servers", [])
        if mcp_servers:
            cmd.append("--allowed-mcp-server-names")
            cmd.extend(mcp_servers)

        # 8. mcp-config-file: NOT SUPPORTED
        if task_config.get("mcp-config-file"):
            logger.warning("Qwen does not support mcp-config-file configuration")

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

        # 12. screen-reader: true → --screen-reader
        if task_config.get("screen-reader"):
            cmd.append("--screen-reader")

        # 13. telemetry: true → --telemetry
        if task_config.get("telemetry"):
            cmd.append("--telemetry")

        # 14. web-search: true with search-api-key → --tavily-api-key "sk-..."
        if task_config.get("web-search"):
            api_key = task_config.get("search-api-key")
            if api_key:
                cmd.extend(["--tavily-api-key", api_key])

        # 15. custom Qwen options
        custom = task_config.get("custom", {}).get("qwen", {})
        if "openai-base-url" in custom:
            cmd.extend(["--openai-base-url", custom["openai-base-url"]])
        if "openai-api-key" in custom:
            cmd.extend(["--openai-api-key", custom["openai-api-key"]])
        if "vlm-switch-mode" in custom:
            cmd.extend(["--vlm-switch-mode", custom["vlm-switch-mode"]])

        # 16. raw-args: [...] → append directly at end
        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # 17. timeout: store but DON'T add to CLI args (used for subprocess timeout)
        # Note: timeout is handled by executor, not part of CLI command

        # 18. Add prompt at the end via -p
        cmd.extend(["-p", prompt])

        return cmd

    def check_available(self):
        """
        Check if Qwen CLI is available in PATH.

        Returns:
            bool: True if tool is available
        """
        return shutil.which("qwen") is not None
