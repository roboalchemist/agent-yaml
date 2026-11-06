"""
Antigravity CLI adapter (Google Antigravity `agy`).

Maps generic configurations onto agy's flags:
- skip-confirmations: true → --dangerously-skip-permissions
- model: "gemini-3.8-flash-high" → --model ...
- effort: low|medium|high|xhigh|max → --effort ...
- agent: "reviewer" → --agent ...
- permissions: ["plan"] → --mode plan (accept-edits|auto|plan; first entry wins)
- output-format: "json"|"stream-json" → --output-format ... ("text" is the default)
- session-id: "abc" → --conversation abc (resume by conversation id)
- continue: true → --continue (most recent conversation; session-id wins)
- sandbox: true → --sandbox (terminal sandbox restrictions)
- additional-dirs: [DIR, ...] → --add-dir DIR (repeated)
- timeout: 600 → --print-timeout 600s (the executor still enforces its own limit)
- json-schema: <json|path> → --json-schema ...
- settings: <json|path> → --settings ... (session-only, never persisted)
- project: "proj" → --project proj
- log-file: path → --log-file path
- disable-slash-commands: true → --disable-slash-commands
- raw-args: [...] → appended after translated flags, before the prompt

`permissions` aliases: plan-only → plan, auto-edit → accept-edits, and
yolo/never/bypass → --dangerously-skip-permissions.

Unsupported (warning logged, value ignored): mcp-servers, mcp-config-file.
MCP servers are managed with `agy mcp add` or `~/.gemini/antigravity-cli/settings.json`.

Non-interactive mode is `agy -p "<prompt>"`, which prints the response and exits. `-p` is
`--print`'s alias and takes the next argument as the prompt, so the prompt is its value.

CLI tool: agy (Antigravity CLI, https://antigravity.google/docs/cli)

Reference: spec/ADAPTER_SPEC.md for the cross-adapter mapping tables.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)

MODE_ALIASES = {
    "plan-only": "plan",
    "auto-edit": "accept-edits",
}
BYPASS_MODES = ("yolo", "never", "bypass", "bypass-permissions")


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

        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-skip-permissions")

        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        effort = task_config.get("effort")
        if effort:
            cmd.extend(["--effort", effort])

        agent = task_config.get("agent")
        if agent:
            cmd.extend(["--agent", agent])

        permissions = task_config.get("permissions", [])
        if permissions:
            if len(permissions) > 1:
                logger.warning(
                    f"antigravity uses only the first permission mode; ignoring {permissions[1:]}"
                )
            mode = permissions[0]
            if mode in BYPASS_MODES:
                cmd.append("--dangerously-skip-permissions")
            else:
                cmd.extend(["--mode", MODE_ALIASES.get(mode, mode)])

        output_format = task_config.get("output-format")
        if output_format:
            cmd.extend(["--output-format", output_format])

        session_id = task_config.get("session-id")
        if session_id:
            if task_config.get("continue"):
                logger.warning(
                    "antigravity session-id and continue are mutually exclusive; "
                    "resuming the session-id"
                )
            cmd.extend(["--conversation", session_id])
        elif task_config.get("continue"):
            cmd.append("--continue")

        if task_config.get("sandbox"):
            cmd.append("--sandbox")

        for directory in task_config.get("additional-dirs", []):
            cmd.extend(["--add-dir", directory])

        timeout = task_config.get("timeout")
        if timeout is not None:
            cmd.extend(["--print-timeout", f"{max(1, int(timeout))}s"])

        for key, flag in (
            ("json-schema", "--json-schema"),
            ("settings", "--settings"),
            ("project", "--project"),
            ("log-file", "--log-file"),
        ):
            value = task_config.get(key)
            if value:
                cmd.extend([flag, str(value)])

        if task_config.get("disable-slash-commands"):
            cmd.append("--disable-slash-commands")

        for unsupported in ("mcp-servers", "mcp-config-file"):
            if task_config.get(unsupported):
                logger.warning(
                    f"antigravity adapter ignores '{unsupported}'; add servers with "
                    "`agy mcp add` or in ~/.gemini/antigravity-cli/settings.json"
                )

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # -p/--print takes the prompt as its value.
        cmd.extend(["-p", prompt])

        return cmd

    def check_available(self):
        """
        Check if the Antigravity CLI is available in PATH.

        Returns:
            bool: True if the `agy` executable is found
        """
        return shutil.which("agy") is not None
