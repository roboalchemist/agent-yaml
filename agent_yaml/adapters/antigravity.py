"""
Antigravity CLI adapter (Google Antigravity `agy`).

Maps generic configurations onto agy's flags:
- skip-confirmations: true → --mode auto
- model: "gemini-4-argon-high" → --model ...
- effort: low|medium|high → --effort ...
- agent: "reviewer" → --agent ...
- output-format: "json"|"stream-json" → --output-format ... ("text" is the default)
- session-id: "abc" → --conversation abc (resume by conversation id)
- continue: true → --continue (most recent conversation)
- sandbox: true → --sandbox (terminal sandbox restrictions)
- raw-args: [...] → appended after translated flags, before the prompt
- timeout → subprocess timeout (handled by the executor, NOT a CLI arg)

Unsupported (warning logged, value ignored): additional-dirs, mcp-servers, mcp-config-file.
Antigravity reads `~/.gemini/antigravity-cli/settings.json` for permissions and MCP.

Non-interactive mode is `agy -p "<prompt>"`, which prints the response and exits. The prompt is
passed as the value of `-p`, so it is never mistaken for a flag.

CLI tool: agy (Antigravity CLI, https://antigravity.google/docs/cli)

Reference: spec/ADAPTER_SPEC.md for the cross-adapter mapping tables.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


class AntigravityAdapter(BaseAdapter):
    """Adapter for the Antigravity CLI (`agy`)."""

    def __init__(self, tool_config=None):
        """Initialize Antigravity adapter."""
        super().__init__("antigravity", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build an `agy` headless command from task configuration.

        Args:
            task_config: Task configuration dict (merged cli-agent-config)
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
        cmd = ["agy"]

        # 1. skip-confirmations → --mode auto (accept edits without prompting)
        if task_config.get("skip-confirmations"):
            cmd.extend(["--mode", "auto"])

        # 2. model / reasoning effort / agent
        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        effort = task_config.get("effort")
        if effort:
            cmd.extend(["--effort", effort])

        agent = task_config.get("agent")
        if agent:
            cmd.extend(["--agent", agent])

        # 3. output format
        output_format = task_config.get("output-format")
        if output_format:
            cmd.extend(["--output-format", output_format])

        # 4. session handling
        session_id = task_config.get("session-id")
        if session_id:
            cmd.extend(["--conversation", session_id])
        elif task_config.get("continue"):
            cmd.append("--continue")

        # 5. sandbox
        if task_config.get("sandbox"):
            cmd.append("--sandbox")

        # 6. Not supported by the agy CLI
        for unsupported in ("additional-dirs", "mcp-servers", "mcp-config-file"):
            if task_config.get(unsupported):
                logger.warning(
                    f"antigravity adapter ignores '{unsupported}'; configure it in "
                    "~/.gemini/antigravity-cli/settings.json"
                )

        # 7. raw-args: passthrough
        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # 8. Prompt as the value of -p, so it can never be parsed as a flag
        cmd.extend(["-p", prompt])

        return cmd

    def check_available(self):
        """
        Check if the Antigravity CLI is available in PATH.

        Returns:
            bool: True if the `agy` executable is found
        """
        return shutil.which("agy") is not None
