"""
OpenCode CLI adapter (OpenCode v2, non-interactive `opencode run`).

Maps generic configurations to OpenCode-specific CLI arguments:
- skip-confirmations: true → --auto (auto-approve permissions that are not explicitly denied)
- model: "anthropic/claude-haiku-5-5" → --model anthropic/claude-haiku-5-5
  (provider/model[#variant]; a few short aliases such as "haiku-5.5" are translated)
- agent: "build" → --agent build
- permissions: ["plan"] → --agent plan (only if `agent` is not set; first entry wins)
- output-format: "json" → --format json; "default"/"text" add nothing
- session-id: "ses_..." → --session ses_...
- continue: true → --continue (session-id wins when both are set)
- title: "..." → --title "..."
- files: [path, ...] → --file path (repeated)
- log-level: "debug" → --log-level debug
- debug: true → --print-logs (server logs only while --standalone is active)
- standalone: true (default) → --standalone
- server: "http://host:port" → --server URL (replaces --standalone)
- raw-args: [...] → appended after the translated flags, before the prompt
- timeout → subprocess timeout (handled by the executor, NOT a CLI arg)
- PROMPT: last argument, always preceded by "--"

Why --standalone by default: without it `opencode run` talks to the shared background
service, whose environment, credentials, and model catalog are not the ones agent-yaml
sets up, so workflow `environment:`/`env:` values never reach the agent's tools. With
--standalone a private server is started as a child process and inherits the subprocess
env and working directory. It exits when `opencode run` exits, including on timeout kill.

Why "--" before the prompt: `opencode run` parses a prompt that starts with "-" as an
unknown flag, prints help, and exits non-zero (v2.0.25 behavior), which would fail the task
with a confusing usage error.

`thinking` is not mapped: OpenCode's `--thinking` is a display toggle for thinking blocks,
while the generic key is a reasoning level (pi). It is ignored without a warning.

Unsupported (warning logged, value ignored); configure these in opencode.json instead:
- additional-dirs, mcp-servers, mcp-config-file

CLI tool: opencode (requires v2.x; v1 has no --standalone/--auto)

Reference: spec/ADAPTER_SPEC.md for the cross-adapter mapping tables.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)


class OpenCodeAdapter(BaseAdapter):
    """Adapter for the OpenCode v2 CLI (`opencode run`)."""

    MODEL_ALIASES = {
        "haiku-5.5": "anthropic/claude-haiku-5-5",
        "sonnet-5.5": "anthropic/claude-sonnet-5-5",
        "opus-5.5": "anthropic/claude-opus-5-5",
    }

    def __init__(self, tool_config=None):
        """Initialize OpenCode adapter."""
        super().__init__("opencode", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build an `opencode run` command from task configuration.

        Args:
            task_config: Task configuration dict (merged cli-agent-config)
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
        cmd = ["opencode", "run"]

        server = task_config.get("server")
        if server:
            cmd.extend(["--server", server])
        elif task_config.get("standalone", True):
            cmd.append("--standalone")

        if task_config.get("skip-confirmations"):
            cmd.append("--auto")

        model = task_config.get("model")
        if model:
            model = self.MODEL_ALIASES.get(model, model)
            if "/" not in model:
                logger.warning(
                    f"OpenCode expects models as provider/model (e.g. anthropic/claude-haiku-5-5), "
                    f"got '{model}'"
                )
            cmd.extend(["--model", model])

        agent = task_config.get("agent")
        permissions = task_config.get("permissions", [])
        if not agent and permissions:
            agent = permissions[0]
        if agent:
            cmd.extend(["--agent", agent])

        output_format = task_config.get("output-format")
        if output_format == "json":
            cmd.extend(["--format", "json"])
        elif output_format and output_format not in ("text", "default"):
            logger.warning(f"OpenCode does not support output-format '{output_format}'")

        session_id = task_config.get("session-id")
        if session_id:
            cmd.extend(["--session", session_id])
        elif task_config.get("continue"):
            cmd.append("--continue")

        title = task_config.get("title")
        if title:
            cmd.extend(["--title", title])

        for path in task_config.get("files", []):
            cmd.extend(["--file", path])

        log_level = task_config.get("log-level")
        if log_level:
            cmd.extend(["--log-level", log_level])

        if task_config.get("debug"):
            cmd.append("--print-logs")

        for unsupported in ("additional-dirs", "mcp-servers", "mcp-config-file"):
            if task_config.get(unsupported):
                logger.warning(
                    f"OpenCode adapter ignores '{unsupported}'; configure it in opencode.json"
                )

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        cmd.extend(["--", prompt])

        return cmd

    def check_available(self):
        """
        Check if the OpenCode CLI is available in PATH.

        Returns:
            bool: True if the `opencode` executable is found
        """
        return shutil.which("opencode") is not None
