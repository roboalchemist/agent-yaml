"""
Antigravity CLI adapter (Google Antigravity `agy`).

Maps generic configurations onto agy's flags:
- skip-confirmations: true → --dangerously-skip-permissions
- model: "gemini-4-argon" → --model ...
- effort: low|medium|high|xhigh|max → --effort ...
- agent: "reviewer" → --agent ...
- output-format: "json"|"stream-json" → --output-format ... ("text" is the default)
- session-id: "abc" → --conversation abc (resume by conversation id)
- continue: true → --continue (most recent conversation)
- sandbox: true → --sandbox (terminal sandbox restrictions)
- additional-dirs: [DIR, ...] → --add-dir DIR (repeated)
- timeout: 600 → --print-timeout 600s (the executor still enforces its own limit)
- raw-args: [...] → appended after translated flags, before the prompt

Unsupported (warning logged, value ignored): mcp-servers, mcp-config-file.
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

        # 1. skip-confirmations → --dangerously-skip-permissions.
        # `--mode auto` is unavailable on API-key accounts and auto-denies the
        # write_file permission in headless mode, so it cannot run agent tasks.
        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-skip-permissions")

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

        # 6. additional directories (repeatable flag)
        for directory in task_config.get("additional-dirs", []):
            cmd.extend(["--add-dir", directory])

        # 7. print-mode deadline, in seconds
        timeout = task_config.get("timeout")
        if timeout is not None:
            cmd.extend(["--print-timeout", f"{int(timeout)}s"])

        # 8. Not supported by the agy CLI
        for unsupported in ("mcp-servers", "mcp-config-file"):
            if task_config.get(unsupported):
                logger.warning(
                    f"antigravity adapter ignores '{unsupported}'; configure it in "
                    "~/.gemini/antigravity-cli/settings.json"
                )

        # 9. raw-args: passthrough
        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # 10. -p is a boolean flag and the prompt is positional. A leading dash
        # would be parsed as a flag, so it gets a single leading space.
        if prompt.startswith("-"):
            logger.warning(
                "antigravity adapter: prompt starts with '-'; prefixing a space so it "
                "is not parsed as a flag"
            )
            prompt = " " + prompt
        cmd.extend(["-p", prompt])

        return cmd

    def check_available(self):
        """
        Check if the Antigravity CLI is available in PATH.

        Returns:
            bool: True if the `agy` executable is found
        """
        return shutil.which("agy") is not None
