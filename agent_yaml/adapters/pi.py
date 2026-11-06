"""
pi CLI adapter (pi coding agent, non-interactive `pi -p`).

Maps generic configurations onto pi's flags:
- skip-confirmations: true → --approve (trust project-local files for the run)
  false (explicit) → --no-approve
- provider: "zai" → --provider zai (requires model)
- model: "zai/glm-5.1" or "zai/glm-5.1:high" → --model ... (passed through)
- thinking: "high" → --thinking high
- tools: ["read", "bash"] → --tools read,bash
- no-tools: true → --no-tools
- exclude-tools: ["write"] → --exclude-tools write
- output-format: "json" → --mode json ("text" is the default)
- session-id: "abc123" → --session-id abc123 (create or reuse)
- continue: true → --continue (session-id wins when both are set)
- session: true → keep session persistence (the default here is --no-session)
- session-dir: "./sessions" → --session-dir ./sessions
- title: "Nightly docs" → --name "Nightly docs"
- debug: true → --verbose (accepted; pi only uses it in the interactive TUI)
- no-extensions: true → --no-extensions
- extensions: [name, ...] → -e name (repeated)
- skills: [path, ...] → --skill path (repeated)
- no-builtin-tools / no-context-files / no-mcp → matching flags
- system-prompt: "..." → --system-prompt ...
- append-system-prompt: [...] → --append-system-prompt ... (repeated)
- raw-args: [...] → appended after the translated flags, before the prompt
- timeout → subprocess timeout (handled by the executor, NOT a CLI arg)

Unsupported (warning logged, value ignored): additional-dirs, mcp-servers, mcp-config-file.
pi runs in the task working directory, and MCP servers are managed with `pi mcp`.

Why `-p`: interactive pi is a TUI (`--tui-mode`), which would hang a subprocess. Print mode
processes one prompt and exits.

Why `--no-session` by default: agent-yaml runs one task per subprocess. Persisting every task to
~/.pi/agent/sessions grows session history and makes reruns depend on earlier runs.

Why empty stdin: pi's print mode reads piped stdin, and some versions hang when stdin is
/dev/null instead of exiting. The adapter sets `needs_empty_stdin`, so the executor feeds an empty
string and pi sees a clean EOF.

Why `--` before the prompt: pi parses a leading "-" as a flag.

`output-format: rpc` is not supported: RPC is a long-lived NDJSON stdin protocol, and a one-shot
print run with closed stdin exits without inference. Use `text` or `json`.

CLI tool: pi (https://github.com/earendil-works/pi)

Reference: spec/ADAPTER_SPEC.md for the cross-adapter mapping tables.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


def _comma_join(value):
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return value


class PiAdapter(BaseAdapter):
    """Adapter for the pi coding agent CLI (`pi -p`)."""

    # pi can hang on /dev/null stdin in print mode; feed an empty string instead.
    needs_empty_stdin = True

    def __init__(self, tool_config=None):
        """Initialize pi adapter."""
        super().__init__("pi", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build a `pi -p` command from task configuration.

        Args:
            task_config: Task configuration dict (merged cli-agent-config)
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
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
            cmd.extend(["--tools", _comma_join(tools)])

        if task_config.get("no-tools"):
            cmd.append("--no-tools")

        exclude_tools = task_config.get("exclude-tools")
        if exclude_tools:
            cmd.extend(["--exclude-tools", _comma_join(exclude_tools)])

        output_format = task_config.get("output-format")
        if output_format == "json":
            cmd.extend(["--mode", "json"])
        elif output_format and output_format != "text":
            logger.warning(f"pi does not support output-format '{output_format}'")

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

        for unsupported in ("additional-dirs", "mcp-servers", "mcp-config-file"):
            if task_config.get(unsupported):
                logger.warning(
                    f"pi adapter ignores '{unsupported}'; tasks run in the workflow directory "
                    "and MCP servers are managed with `pi mcp`"
                )

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        cmd.extend(["--", prompt])

        return cmd

    def check_available(self):
        """
        Check if the pi CLI is available in PATH.

        Returns:
            bool: True if the `pi` executable is found
        """
        return shutil.which("pi") is not None
