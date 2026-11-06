"""
OpenCode CLI adapter (OpenCode v2, non-interactive `opencode run`).

Maps generic configurations to OpenCode-specific CLI arguments:
- skip-confirmations: true → --auto
- model: provider/model[#variant] → --model (short aliases translated)
- agent / permissions[0] → --agent
- output-format: json → --format json; default/text add nothing
- session-id → --session; continue → --continue; title → --title
- files → --file (repeated); log-level → --log-level
- debug → --print-logs (server logs while --standalone is active)
- standalone (default true) → --standalone; server URL replaces it
- raw-args → appended before the prompt
- prompt last, after "--"

Ignored with a remediation hint: additional-dirs, mcp-servers, mcp-config-file (configure
them in opencode.json). Ignored silently: keys another harness owns but OpenCode has no
equivalent for (tools, thinking, sandbox, schemas, prompts, and so on).

CLI tool: opencode (requires v2.x).
"""

import logging

logger = logging.getLogger(__name__)

from .base import (
    BaseAdapter,
    BOOL,
    ENUM,
    IGNORED,
    IGNORED_SILENT,
    LIST,
    NUMBER,
    STR,
)

_IGNORED = {
    key: IGNORED_SILENT
    for key in (
        "provider",
        "tools",
        "exclude-tools",
        "thinking",
        "no-tools",
        "session",
        "no-extensions",
        "web-search",
        "security-level",
        "max-tool-calls",
        "quiet",
        "effort",
        "sandbox",
        "json-schema",
        "last-message-file",
        "system-prompt",
        "append-system-prompt",
        "settings",
        "disable-slash-commands",
        "max-budget",
        "fallback-model",
        "project",
        "log-file",
        "color",
        "images",
        "enable",
        "ignore-user-config",
        "ignore-rules",
        "events-file",
        "max-concurrent-ops",
        "api-rate-limit",
        "config-overrides",
        "session-dir",
        "no-context-files",
        "no-mcp",
        "no-builtin-tools",
        "skills",
        "extensions",
    )
}


class OpenCodeAdapter(BaseAdapter):
    """Adapter for the OpenCode v2 CLI (`opencode run`)."""

    name = "opencode"
    executables = ("opencode",)
    install_hint = "opencode"
    prompt_style = "separator"
    prompt_separator = "--"

    MODEL_ALIASES = {
        "haiku-5.5": "anthropic/claude-haiku-5-5",
        "sonnet-5.5": "anthropic/claude-sonnet-5-5",
        "opus-5.5": "anthropic/claude-opus-5-5",
    }

    option_spec = {
        "model": STR,
        "session-id": STR,
        "continue": BOOL,
        "title": STR,
        "agent": STR,
        "permissions": LIST,
        "output-format": ENUM("text", "default", "json"),
        "skip-confirmations": BOOL,
        "debug": BOOL,
        "raw-args": LIST,
        "additional-dirs": IGNORED("configure it in opencode.json"),
        "mcp-servers": IGNORED("configure it in opencode.json"),
        "mcp-config-file": IGNORED("configure it in opencode.json"),
        "server": STR,
        "standalone": BOOL,
        "log-level": ENUM("all", "trace", "debug", "info", "warn", "warning", "error", "fatal", "none"),
        "files": LIST,
        "timeout": NUMBER,
        **_IGNORED,
    }

    live_exempt = {
        "provider": "OpenCode has no provider flag; the provider is part of the model id",
        "tools": "tool availability is configured by the selected agent, not a run flag",
        "exclude-tools": "tool availability is configured by the selected agent, not a run flag",
        "thinking": "OpenCode --thinking is a display toggle, not a reasoning level",
        "sandbox": "OpenCode has no sandbox flag; worktree isolation is an agent setting",
        "server": "requires a running OpenCode server on the requested port",
        "standalone": "tested through the default command shape (no explicit case)",
        "session-id": "requires an existing ses_... session; continue covers resume",
        "raw-args": "verbatim passthrough; covered by the adapter unit tests",
    }

    def build_command(self, task_config, prompt):
        """Build an `opencode run` command from task configuration."""
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
                self.logger.warning(
                    "OpenCode expects models as provider/model "
                    f"(e.g. anthropic/claude-haiku-5-5), got '{model}'"
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

        self.warn_ignored(task_config)

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        return self.append_prompt(cmd, prompt)
