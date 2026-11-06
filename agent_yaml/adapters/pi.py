"""
pi CLI adapter (pi coding agent, non-interactive `pi -p`).

Maps generic configurations onto pi's flags:
- skip-confirmations: true → --approve; explicit false → --no-approve
- provider → --provider (requires model)
- model → --model (provider/id[:thinking] passes through)
- thinking → --thinking
- tools / exclude-tools → --tools / --exclude-tools (comma-joined)
- no-tools / no-builtin-tools → matching flags
- output-format: json → --mode json; text is the default
- session-id / continue → --session-id / --continue
- session: true keeps persistence; the default is --no-session
- session-dir → --session-dir
- title → --name
- system-prompt / append-system-prompt → matching flags
- extensions → -e; skills → --skill
- no-extensions / no-context-files / no-mcp → matching flags
- debug → --verbose (accepted; pi only uses it in the interactive TUI)
- raw-args → appended before the prompt
- prompt after "--"

Ignored with a hint: additional-dirs, mcp-servers, mcp-config-file.

Why empty stdin: print mode can hang on /dev/null; the adapter sets needs_empty_stdin.
Why --no-session by default: one subprocess per task, so sessions stay ephemeral unless asked.
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
    STR_OR_LIST,
)

THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
OUTPUT_FORMATS = ("text", "json")


class PiAdapter(BaseAdapter):
    """Adapter for the pi coding agent CLI (`pi -p`)."""

    name = "pi"
    executables = ("pi",)
    install_hint = "pi"
    needs_empty_stdin = True
    prompt_style = "separator"
    prompt_separator = "--"

    option_spec = {
        "model": STR,
        "provider": STR,
        "thinking": ENUM(*THINKING_LEVELS),
        "title": STR,
        "session-id": STR,
        "output-format": ENUM(*OUTPUT_FORMATS),
        "tools": STR_OR_LIST,
        "exclude-tools": STR_OR_LIST,
        "skip-confirmations": BOOL,
        "no-tools": BOOL,
        "continue": BOOL,
        "session": BOOL,
        "session-dir": STR,
        "system-prompt": STR,
        "append-system-prompt": STR_OR_LIST,
        "debug": BOOL,
        "no-extensions": BOOL,
        "extensions": LIST,
        "skills": LIST,
        "no-builtin-tools": BOOL,
        "no-context-files": BOOL,
        "no-mcp": BOOL,
        "timeout": NUMBER,
        "raw-args": LIST,
        "additional-dirs": IGNORED(
            "tasks run in the workflow directory and MCP servers are managed with `pi mcp`"
        ),
        "mcp-servers": IGNORED(
            "tasks run in the workflow directory and MCP servers are managed with `pi mcp`"
        ),
        "mcp-config-file": IGNORED(
            "tasks run in the workflow directory and MCP servers are managed with `pi mcp`"
        ),
    }

    live_exempt = {
        "skills": "needs an installed pi skill to load",
        "extensions": "needs an installed pi extension to load",
        "raw-args": "verbatim passthrough; covered by the adapter unit tests",
    }

    def cross_validate(self, config, fail):
        if "provider" in config and "model" not in config:
            fail("pi option 'provider' requires 'model' (the CLI rejects --provider alone)")

    def build_command(self, task_config, prompt):
        """Build a `pi -p` command from task configuration."""
        cmd = ["pi", "-p"]

        if task_config.get("skip-confirmations"):
            cmd.append("--approve")
        elif "skip-confirmations" in task_config:
            cmd.append("--no-approve")

        provider = task_config.get("provider")
        if provider:
            cmd.extend(["--provider", provider])

        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        thinking = task_config.get("thinking")
        if thinking:
            cmd.extend(["--thinking", thinking])

        tools = task_config.get("tools")
        if tools:
            cmd.extend(["--tools", self.join_list(tools)])

        if task_config.get("no-tools"):
            cmd.append("--no-tools")

        exclude_tools = task_config.get("exclude-tools")
        if exclude_tools:
            cmd.extend(["--exclude-tools", self.join_list(exclude_tools)])

        output_format = task_config.get("output-format")
        if output_format == "json":
            cmd.extend(["--mode", "json"])

        session_id = task_config.get("session-id")
        if session_id:
            cmd.extend(["--session-id", session_id])
        elif task_config.get("continue"):
            cmd.append("--continue")
        elif not task_config.get("session"):
            cmd.append("--no-session")

        session_dir = task_config.get("session-dir")
        if session_dir:
            cmd.extend(["--session-dir", session_dir])

        title = task_config.get("title")
        if title:
            cmd.extend(["--name", title])

        if task_config.get("debug"):
            cmd.append("--verbose")

        if task_config.get("no-extensions"):
            cmd.append("--no-extensions")
        for extension in task_config.get("extensions", []):
            cmd.extend(["-e", extension])

        for skill in task_config.get("skills", []):
            cmd.extend(["--skill", skill])

        if task_config.get("no-builtin-tools"):
            cmd.append("--no-builtin-tools")
        if task_config.get("no-context-files"):
            cmd.append("--no-context-files")
        if task_config.get("no-mcp"):
            cmd.append("--no-mcp")

        system_prompt = task_config.get("system-prompt")
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        append_prompts = task_config.get("append-system-prompt")
        if append_prompts:
            if isinstance(append_prompts, str):
                append_prompts = [append_prompts]
            for extra in append_prompts:
                cmd.extend(["--append-system-prompt", extra])

        self.warn_ignored(task_config)

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        return self.append_prompt(cmd, prompt)
