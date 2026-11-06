"""
Claude CLI adapter.

Maps generic configurations to Claude-specific CLI arguments:
- skip-confirmations: true → --dangerously-skip-permissions
- additional-dirs: ["/tmp"] → --add-dir="/tmp" (repeated)
- model: legacy aliases translated to current CLI aliases (sonnet-4.5 → sonnet)
- debug: true → --debug
- tools: "default" (default) → --tools "default"; no-tools → --tools ""
- exclude-tools: [...] → --disallowed-tools a,b
- output-format: stream-json → --verbose --output-format stream-json
- session-id: uuid → --session-id; continue → --continue
- session: false → --no-session-persistence
- agent / title / effort → --agent / --name / --effort
- mcp-config-file → --mcp-config
- permissions[0] → --permission-mode
- json-schema / system-prompt / append-system-prompt / settings / max-budget /
  fallback-model / disable-slash-commands → matching flags
- raw-args → appended before the prompt
- prompt: --print PROMPT

mcp-servers has no per-server flag in Claude 2.x and is ignored with a remediation hint.

CLI tool: claude-code or claude.
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
    STR_OR_LIST,
)

_IGNORED = {
    key: IGNORED_SILENT
    for key in (
        "provider",
        "thinking",
        "no-extensions",
        "web-search",
        "server",
        "standalone",
        "security-level",
        "max-tool-calls",
        "quiet",
        "sandbox",
        "last-message-file",
        "project",
        "log-file",
        "log-level",
        "color",
        "files",
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


class ClaudeAdapter(BaseAdapter):
    """Adapter for Claude CLI (claude-code)."""

    name = "claude"
    executables = ("claude-code", "claude")
    install_hint = "claude-code or claude"
    fallback_executable = "claude"
    prompt_style = "flag"
    prompt_flag = "--print"

    MODEL_MAPPING = {
        "sonnet-4.5": "sonnet",
        "opus-4": "opus",
    }

    option_spec = {
        "model": STR,
        "session-id": STR,
        "continue": BOOL,
        "title": STR,
        "agent": STR,
        "permissions": LIST,
        "output-format": ENUM("text", "json", "stream-json"),
        "skip-confirmations": BOOL,
        "debug": BOOL,
        "raw-args": LIST,
        "additional-dirs": LIST,
        "mcp-config-file": STR,
        "mcp-servers": IGNORED(
            "Claude 2.x has no per-server CLI allow flag; scope servers in the MCP config file"
        ),
        "tools": STR_OR_LIST,
        "exclude-tools": STR_OR_LIST,
        "no-tools": BOOL,
        "session": BOOL,
        "effort": ENUM("low", "medium", "high", "xhigh", "max"),
        "json-schema": STR,
        "system-prompt": STR,
        "append-system-prompt": STR_OR_LIST,
        "settings": STR,
        "max-budget": NUMBER,
        "fallback-model": STR,
        "disable-slash-commands": BOOL,
        "timeout": NUMBER,
        **_IGNORED,
    }

    live_exempt = {
        "max-budget": "spend caps are account-sensitive; argv is parse-verified",
        "settings": "a settings file changes the operator's Claude install; parse-verified only",
        "mcp-config-file": "needs a real MCP server definition",
        "no-tools": "covered by the tools allowlist cases; disabling all tools has no turn to assert",
        "raw-args": "verbatim passthrough; covered by the adapter unit tests",
        "agent": "needs a user-defined Claude agent",
    }

    def build_command(self, task_config, prompt):
        """Build Claude CLI command from task configuration."""
        cmd = [self.executable()]

        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-skip-permissions")

        for directory in task_config.get("additional-dirs", []):
            cmd.append(f"--add-dir={directory}")

        model = task_config.get("model")
        if model:
            cmd.extend(["--model", self.MODEL_MAPPING.get(model, model)])

        if task_config.get("debug"):
            cmd.append("--debug")

        if task_config.get("no-tools"):
            cmd.extend(["--tools", ""])
        else:
            tools = task_config.get("tools", "default")
            if tools:
                cmd.extend(["--tools", self.join_list(tools)])

        exclude_tools = task_config.get("exclude-tools")
        if exclude_tools:
            cmd.extend(["--disallowed-tools", self.join_list(exclude_tools)])

        output_format = task_config.get("output-format")
        if output_format is None:
            output_format = "stream-json" if task_config.get("debug") else "text"
        if output_format == "stream-json":
            cmd.append("--verbose")
            cmd.extend(["--output-format", "stream-json"])
        elif output_format != "text":
            cmd.extend(["--output-format", output_format])

        session_id = task_config.get("session-id")
        if session_id:
            cmd.extend(["--session-id", session_id])
        elif task_config.get("continue"):
            cmd.append("--continue")
        if "session" in task_config and not task_config["session"]:
            cmd.append("--no-session-persistence")

        agent = task_config.get("agent")
        if agent:
            cmd.extend(["--agent", agent])

        title = task_config.get("title")
        if title:
            cmd.extend(["--name", title])

        effort = task_config.get("effort")
        if effort:
            cmd.extend(["--effort", effort])

        mcp_config_file = task_config.get("mcp-config-file")
        if mcp_config_file:
            cmd.extend(["--mcp-config", mcp_config_file])

        permissions = task_config.get("permissions", [])
        if permissions:
            if len(permissions) > 1:
                self.logger.warning(
                    f"claude uses only the first permission mode; ignoring {permissions[1:]}"
                )
            cmd.extend(["--permission-mode", permissions[0]])

        for key, flag in (
            ("json-schema", "--json-schema"),
            ("system-prompt", "--system-prompt"),
            ("settings", "--settings"),
            ("fallback-model", "--fallback-model"),
        ):
            value = task_config.get(key)
            if value:
                cmd.extend([flag, str(value)])

        append_prompts = task_config.get("append-system-prompt")
        if append_prompts:
            if isinstance(append_prompts, str):
                append_prompts = [append_prompts]
            for extra in append_prompts:
                cmd.extend(["--append-system-prompt", extra])

        max_budget = task_config.get("max-budget")
        if max_budget is not None:
            cmd.extend(["--max-budget-usd", str(max_budget)])

        if task_config.get("disable-slash-commands"):
            cmd.append("--disable-slash-commands")

        self.warn_ignored(task_config)

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        return self.append_prompt(cmd, prompt)
