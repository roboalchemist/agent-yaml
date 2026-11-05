"""
pi CLI adapter (pi coding agent, non-interactive `pi -p`).

Maps generic configurations onto pi's flags:
- skip-confirmations: true → --approve (trust project-local files for the run)
- provider: "zai" → --provider zai
- model: "zai/glm-5.1" or "zai/glm-5.1:high" → --model ... (passed through)
- thinking: "high" → --thinking high
- tools: ["read", "bash"] → --tools read,bash
- no-tools: true → --no-tools
- exclude-tools: ["write"] → --exclude-tools write
- output-format: "json" → --mode json ("text" is the default, "rpc" is passed through)
- session-id: "abc123" → --session-id abc123 (create or reuse)
- continue: true → --continue (session-id wins when both are set)
- session: true → keep session persistence (the default here is --no-session)
- title: "Nightly docs" → --name "Nightly docs"
- debug: true → --verbose
- no-extensions: true → --no-extensions
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

CLI tool: pi (https://github.com/earendil-works/pi)

Reference: spec/ADAPTER_SPEC.md for the cross-adapter mapping tables.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


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

        # 1. skip-confirmations: true → --approve
        if task_config.get("skip-confirmations"):
            cmd.append("--approve")

        # 2. provider → --provider
        provider = task_config.get("provider")
        if provider:
            cmd.extend(["--provider", provider])

        # 3. model: provider/id with an optional :thinking suffix, passed through
        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        # 4. thinking level
        thinking = task_config.get("thinking")
        if thinking:
            cmd.extend(["--thinking", thinking])

        # 5. tools: list or comma string → --tools
        tools = task_config.get("tools")
        if tools:
            if isinstance(tools, (list, tuple)):
                tools = ",".join(str(tool) for tool in tools)
            cmd.extend(["--tools", tools])

        # 6. no-tools: true → --no-tools
        if task_config.get("no-tools"):
            cmd.append("--no-tools")

        # 7. exclude-tools: list or comma string → --exclude-tools
        exclude_tools = task_config.get("exclude-tools")
        if exclude_tools:
            if isinstance(exclude_tools, (list, tuple)):
                exclude_tools = ",".join(str(tool) for tool in exclude_tools)
            cmd.extend(["--exclude-tools", exclude_tools])

        # 8. output-format: json/rpc → --mode; text is the default
        output_format = task_config.get("output-format")
        if output_format in ("json", "rpc"):
            cmd.extend(["--mode", output_format])
        elif output_format and output_format != "text":
            logger.warning(f"pi does not support output-format '{output_format}'")

        # 9. session handling: session-id, else continue, else ephemeral by default
        session_id = task_config.get("session-id")
        if session_id:
            # --session-id creates the session when it does not exist, unlike --session,
            # which fails with "No session found matching".
            cmd.extend(["--session-id", session_id])
        elif task_config.get("continue"):
            cmd.append("--continue")
        elif not task_config.get("session"):
            cmd.append("--no-session")

        # 10. title → --name
        title = task_config.get("title")
        if title:
            cmd.extend(["--name", title])

        # 11. debug: true → --verbose
        if task_config.get("debug"):
            cmd.append("--verbose")

        # 12. no-extensions: true → --no-extensions (hermetic runs)
        if task_config.get("no-extensions"):
            cmd.append("--no-extensions")

        # 13. Not supported by pi's CLI
        for unsupported in ("additional-dirs", "mcp-servers", "mcp-config-file"):
            if task_config.get(unsupported):
                logger.warning(
                    f"pi adapter ignores '{unsupported}'; tasks run in the workflow directory "
                    "and MCP servers are managed with `pi mcp`"
                )

        # 14. raw-args: passthrough
        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # 15. Prompt last, after "--" so a leading "-" is never parsed as a flag
        cmd.extend(["--", prompt])

        return cmd

    def check_available(self):
        """
        Check if the pi CLI is available in PATH.

        Returns:
            bool: True if the `pi` executable is found
        """
        return shutil.which("pi") is not None
