"""
Antigravity CLI adapter (Google Antigravity `agy`).

Maps generic configurations onto agy's flags:
- skip-confirmations → --dangerously-skip-permissions
- model / effort / agent → --model / --effort / --agent
- permissions[0] → --mode plan|accept-edits|auto (yolo/never → --dangerously-skip-permissions)
- output-format → --output-format text|json|stream-json
- session-id / continue → --conversation ID / --continue
- sandbox → --sandbox
- additional-dirs → --add-dir (repeated)
- timeout → --print-timeout Ns (the executor still enforces its own limit)
- json-schema / settings / project / log-file → matching flags
- disable-slash-commands → --disable-slash-commands
- raw-args → appended before the prompt
- prompt: -p PROMPT (the value of --print)

mcp-servers and mcp-config-file are ignored with a hint (use `agy mcp add` or the
settings file).

CLI tool: agy (https://antigravity.google/docs/cli)
"""

import logging

logger = logging.getLogger(__name__)

from .base import (
    BaseAdapter,
    BOOL,
    ENUM,
    IGNORED,
    LIST,
    NUMBER,
    STR,
)

MODE_ALIASES = {
    "plan-only": "plan",
    "auto-edit": "accept-edits",
}
BYPASS_MODES = ("yolo", "never", "bypass", "bypass-permissions")


class AntigravityAdapter(BaseAdapter):
    """Adapter for the Antigravity CLI (`agy`)."""

    name = "antigravity"
    executables = ("agy",)
    install_hint = "agy"
    prompt_style = "flag"
    prompt_flag = "-p"

    option_spec = {
        "model": STR,
        "effort": ENUM("low", "medium", "high", "xhigh", "max"),
        "agent": STR,
        "permissions": LIST,
        "session-id": STR,
        "output-format": ENUM("text", "json", "stream-json"),
        "skip-confirmations": BOOL,
        "continue": BOOL,
        "sandbox": BOOL,
        "json-schema": STR,
        "settings": STR,
        "project": STR,
        "log-file": STR,
        "disable-slash-commands": BOOL,
        "timeout": NUMBER,
        "raw-args": LIST,
        "additional-dirs": LIST,
        "mcp-servers": IGNORED(
            "add servers with `agy mcp add` or in ~/.gemini/antigravity-cli/settings.json"
        ),
        "mcp-config-file": IGNORED(
            "add servers with `agy mcp add` or in ~/.gemini/antigravity-cli/settings.json"
        ),
    }

    def cross_validate(self, config, fail):
        if "json-schema" in config and config.get("output-format", "text") not in (
            "json",
            "stream-json",
        ):
            fail(
                "antigravity option 'json-schema' requires output-format 'json' or "
                "'stream-json' (the CLI rejects it otherwise)"
            )

    live_exempt = {
        "project": "no named Antigravity project is configured for this account",
        "raw-args": "verbatim passthrough; covered by the adapter unit tests",
        "agent": "no custom agents are configured on this account",
    }

    def build_command(self, task_config, prompt):
        """Build an `agy` headless command from task configuration."""
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
                self.logger.warning(
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
                self.logger.warning(
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

        self.warn_ignored(task_config)

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        return self.append_prompt(cmd, prompt)
