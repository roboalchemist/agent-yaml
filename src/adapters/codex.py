"""
Codex CLI adapter.

Maps generic configurations to Codex-specific CLI arguments:
- skip-confirmations: true → --full-auto
- additional-dirs: ["/tmp"] → -C /tmp (ONLY first directory, warn if multiple)
- model: pass through as-is (no translation)
- debug: true → -c debug=true (config style, NOT --debug)
- permissions: ["on-failure"] → -a on-failure
- web-search: true → --search
- PROMPT: DIRECT argument at end (NO flag)

Unsupported features (log warning):
- output-format

CLI tool: codex exec (uses exec subcommand for non-interactive execution)

Reference: spec/ADAPTER_SPEC.md for complete Codex mappings.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


class CodexAdapter(BaseAdapter):
    """Adapter for Codex CLI."""

    def __init__(self, tool_config=None):
        """Initialize Codex adapter."""
        super().__init__("codex", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build Codex CLI command from task configuration.

        Args:
            task_config: Task configuration dict
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
        # Start with base command - use 'exec' subcommand for non-interactive execution
        cmd = ["codex", "exec"]

        # Always add --skip-git-repo-check to allow running in any directory
        cmd.append("--skip-git-repo-check")

        # Process config options in order per spec

        # 1. skip-confirmations: true → --full-auto
        if task_config.get("skip-confirmations"):
            cmd.append("--full-auto")

        # 2. additional-dirs: ["/tmp"] → -C /tmp (ONLY first directory)
        additional_dirs = task_config.get("additional-dirs", [])
        if additional_dirs:
            # Codex only supports one directory
            cmd.extend(["-C", additional_dirs[0]])
            if len(additional_dirs) > 1:
                logger.warning(
                    f"Codex only supports one directory. Using first directory '{additional_dirs[0]}'. "
                    f"Additional directories will be ignored: {additional_dirs[1:]}"
                )

        # 3. model: pass through as-is (no translation)
        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        # 4. debug: true → -c debug=true (config style)
        if task_config.get("debug"):
            cmd.extend(["-c", "debug=true"])

        # 5. output-format: NOT SUPPORTED
        if task_config.get("output-format"):
            logger.warning("Codex does not support output-format configuration")

        # 6. permissions: ["on-failure"] → -a on-failure
        permissions = task_config.get("permissions", [])
        if permissions:
            # Take first permission mode
            cmd.extend(["-a", permissions[0]])

        # 7. web-search: true → --search
        if task_config.get("web-search"):
            cmd.append("--search")

        # 8. raw-args: passthrough (no translation)
        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # 9. Prompt goes at the end as DIRECT argument (NO flag)
        cmd.append(prompt)

        return cmd

    def check_available(self):
        """
        Check if Codex CLI is available in PATH.

        Checks for "codex" executable.

        Returns:
            bool: True if tool is available
        """
        return shutil.which("codex") is not None
