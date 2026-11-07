"""
Codex CLI adapter (`codex exec`).

Maps generic configurations to Codex-specific CLI arguments:
- skip-confirmations: true → --dangerously-bypass-approvals-and-sandbox
- additional-dirs: [DIR, ...] → --add-dir DIR (repeated)
- model: pass through as-is
- output-format: json → --json; text adds nothing
- permissions[0]: plan/read-only/workspace-write/danger-full-access → --sandbox;
  untrusted|on-failure|on-request|never → -c approval_policy=…
- sandbox: read-only|workspace-write|danger-full-access → --sandbox
- provider: ollama|lmstudio → --oss --local-provider
- session: false → --ephemeral; session-id/continue → `codex exec resume`
- effort → -c model_reasoning_effort=…
- web-search → --enable web_search
- json-schema → --output-schema; last-message-file → -o; images → -i
- enable → --enable (repeated); config-overrides → -c (repeated)
- ignore-user-config / ignore-rules → matching flags
- raw-args → appended before the prompt
- prompt: positional, last argument

`codex exec resume` has no --sandbox or --add-dir; those are dropped with a warning when
resuming. `debug` has no headless equivalent and is ignored with a hint.

Reference: spec/ADAPTER_SPEC.md for the complete Codex mappings.
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
        "agent",
        "title",
        "mcp-servers",
        "mcp-config-file",
        "tools",
        "exclude-tools",
        "thinking",
        "no-tools",
        "no-extensions",
        "server",
        "standalone",
        "security-level",
        "max-tool-calls",
        "quiet",
        "system-prompt",
        "append-system-prompt",
        "settings",
        "disable-slash-commands",
        "max-budget",
        "fallback-model",
        "project",
        "log-file",
        "log-level",
        "color",
        "files",
        "events-file",
        "max-concurrent-ops",
        "api-rate-limit",
        "session-dir",
        "no-context-files",
        "no-mcp",
        "no-builtin-tools",
        "skills",
        "extensions",
    )
}

SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
APPROVAL_MODES = ("untrusted", "on-failure", "on-request", "never")
OSS_PROVIDERS = ("ollama", "lmstudio")


class CodexAdapter(BaseAdapter):
    """Adapter for Codex CLI."""

    name = "codex"
    executables = ("codex",)
    install_hint = "codex"
    prompt_style = "positional"

    option_spec = {
        "model": STR,
        "provider": ENUM(*OSS_PROVIDERS),
        "session-id": STR,
        "continue": BOOL,
        "permissions": LIST,
        "output-format": ENUM("text", "json"),
        "skip-confirmations": BOOL,
        "debug": IGNORED("codex exec has no debug flag"),
        "raw-args": LIST,
        "additional-dirs": LIST,
        "sandbox": ENUM(*SANDBOX_MODES),
        "session": BOOL,
        "effort": STR,
        "web-search": BOOL,
        "json-schema": STR,
        "last-message-file": STR,
        "images": LIST,
        "enable": LIST,
        "ignore-user-config": BOOL,
        "ignore-rules": BOOL,
        "config-overrides": LIST,
        "timeout": NUMBER,
        **_IGNORED,
    }

    live_exempt = {
        "provider": "needs a local ollama or lmstudio endpoint",
        "images": "vision input needs a model that accepts images",
        "ignore-user-config": "changes what Codex loads from the operator's home directory",
        "ignore-rules": "changes what Codex loads from the operator's home directory",
        "config-overrides": "arbitrary config injection; parse-verified only",
        "raw-args": "verbatim passthrough; covered by the adapter unit tests",
        "session-id": "resume needs a real session id from a prior run; continue covers the resume path",
        "effort": "reasoning effort is deliberately not exercised in the cheap-model matrix",
    }

    def build_command(self, task_config, prompt):
        """Build a Codex CLI command from task configuration."""
        session_id = task_config.get("session-id")
        continue_session = bool(task_config.get("continue"))

        if session_id:
            cmd = ["codex", "exec", "resume", session_id]
        elif continue_session:
            cmd = ["codex", "exec", "resume", "--last"]
        else:
            cmd = ["codex", "exec"]
        resuming = bool(session_id or continue_session)

        cmd.append("--skip-git-repo-check")

        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-bypass-approvals-and-sandbox")

        additional_dirs = task_config.get("additional-dirs", [])
        if additional_dirs:
            if resuming:
                self.logger.warning(
                    "codex exec resume has no --add-dir; ignoring additional-dirs on resume"
                )
            else:
                for directory in additional_dirs:
                    cmd.extend(["--add-dir", directory])

        model = task_config.get("model")
        if model:
            cmd.extend(["--model", model])

        provider = task_config.get("provider")
        if provider:
            if resuming:
                self.logger.warning("codex exec resume has no --oss; ignoring provider on resume")
            else:
                cmd.extend(["--oss", "--local-provider", provider.lower()])

        if "session" in task_config and not task_config["session"]:
            cmd.append("--ephemeral")

        output_format = task_config.get("output-format")
        if output_format == "json":
            cmd.append("--json")

        sandbox = task_config.get("sandbox")
        if sandbox:
            if resuming:
                self.logger.warning("codex exec resume has no --sandbox; ignoring sandbox on resume")
            else:
                cmd.extend(["--sandbox", sandbox])

        permissions = task_config.get("permissions", [])
        if permissions:
            if len(permissions) > 1:
                self.logger.warning(
                    f"codex uses only the first permission mode; ignoring {permissions[1:]}"
                )
            mode = permissions[0]
            if mode in ("plan",) or mode in SANDBOX_MODES:
                if resuming:
                    self.logger.warning(
                        "codex exec resume has no --sandbox; ignoring sandbox mode"
                    )
                else:
                    cmd.extend(["--sandbox", "read-only" if mode == "plan" else mode])
            elif mode in APPROVAL_MODES:
                cmd.extend(["-c", f"approval_policy={mode}"])
            else:
                self.logger.warning(
                    "codex permissions must be one of "
                    f"{list(APPROVAL_MODES + SANDBOX_MODES)} or 'plan', got '{mode}'"
                )

        effort = task_config.get("effort")
        if effort:
            cmd.extend(["-c", f"model_reasoning_effort={effort}"])

        if task_config.get("web-search"):
            cmd.extend(["--enable", "web_search"])

        json_schema = task_config.get("json-schema")
        if json_schema:
            cmd.extend(["--output-schema", json_schema])

        last_message_file = task_config.get("last-message-file")
        if last_message_file:
            cmd.extend(["-o", last_message_file])

        for image in task_config.get("images", []):
            cmd.extend(["-i", image])

        for feature in task_config.get("enable", []):
            cmd.extend(["--enable", feature])

        if task_config.get("ignore-user-config"):
            cmd.append("--ignore-user-config")
        if task_config.get("ignore-rules"):
            cmd.append("--ignore-rules")

        for override in task_config.get("config-overrides", []):
            cmd.extend(["-c", override])

        self.warn_ignored(task_config)

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        return self.append_prompt(cmd, prompt)
