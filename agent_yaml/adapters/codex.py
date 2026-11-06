"""
Codex CLI adapter (`codex exec`).

Maps generic configurations to Codex-specific CLI arguments:
- skip-confirmations: true → --dangerously-bypass-approvals-and-sandbox
- additional-dirs: [DIR, ...] → --add-dir DIR (repeated; `-C` would replace the root)
- model: pass through as-is (no translation)
- output-format: "json" → --json ("text" adds nothing)
- permissions: [mode, ...] → first entry only:
    plan / read-only            → --sandbox read-only
    workspace-write             → --sandbox workspace-write
    danger-full-access          → --sandbox danger-full-access
    untrusted|on-failure|on-request|never → -c approval_policy=<mode>
- sandbox: "read-only|workspace-write|danger-full-access" → --sandbox
- provider: "ollama"|"lmstudio" → --oss --local-provider <name>
- session: false → --ephemeral
- effort: "high" → -c model_reasoning_effort=high
- session-id: "id" → `codex exec resume <id>`
- continue: true → `codex exec resume --last` (session-id wins)
- json-schema: path → --output-schema PATH
- last-message-file: path → -o PATH
- images: [path, ...] → -i PATH (repeated)
- enable: [feature, ...] → --enable FEATURE (repeated)
- ignore-user-config / ignore-rules → matching flags
- web-search: true → --enable web_search
- config-overrides: ["k=v", ...] → -c k=v (repeated)
- raw-args: [...] → appended after the translated flags
- PROMPT: DIRECT argument at the end (NO flag)

`codex exec resume` has no `--sandbox` or `--add-dir`; when resuming, those options are
warned and dropped. `--oss` is exec-only for the same reason.

`debug` has no headless equivalent in codex 0.153.x, so it warns and is dropped.

Reference: spec/ADAPTER_SPEC.md for the complete Codex mappings.
"""

import logging
import shutil

from .base import BaseAdapter

logger = logging.getLogger(__name__)

SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
APPROVAL_MODES = ("untrusted", "on-failure", "on-request", "never")
OSS_PROVIDERS = ("ollama", "lmstudio")


class CodexAdapter(BaseAdapter):
    """Adapter for Codex CLI."""

    def __init__(self, tool_config=None):
        """Initialize Codex adapter."""
        super().__init__("codex", tool_config)

    def build_command(self, task_config, prompt):
        """
        Build a Codex CLI command from task configuration.

        Args:
            task_config: Task configuration dict
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
        session_id = task_config.get("session-id")
        continue_session = bool(task_config.get("continue"))

        # `codex exec resume` continues an existing session; otherwise plain exec.
        if session_id:
            cmd = ["codex", "exec", "resume", session_id]
        elif continue_session:
            cmd = ["codex", "exec", "resume", "--last"]
        else:
            cmd = ["codex", "exec"]
        resuming = bool(session_id or continue_session)

        # Allow running in a directory that is not a git repo.
        cmd.append("--skip-git-repo-check")

        if task_config.get("skip-confirmations"):
            cmd.append("--dangerously-bypass-approvals-and-sandbox")

        # additional-dirs are extra writable roots; -C replaces the working root.
        additional_dirs = task_config.get("additional-dirs", [])
        if additional_dirs:
            if resuming:
                logger.warning(
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
            if provider.lower() in OSS_PROVIDERS:
                if resuming:
                    logger.warning(
                        "codex exec resume has no --oss; ignoring provider on resume"
                    )
                else:
                    cmd.extend(["--oss", "--local-provider", provider.lower()])
            else:
                logger.warning(
                    "codex only supports provider 'ollama' or 'lmstudio' (via --oss); "
                    f"ignoring provider '{provider}'"
                )

        if "session" in task_config and not task_config["session"]:
            cmd.append("--ephemeral")

        if task_config.get("debug"):
            logger.warning("codex exec has no debug flag; ignoring debug")

        output_format = task_config.get("output-format")
        if output_format == "json":
            cmd.append("--json")
        elif output_format and output_format != "text":
            logger.warning(f"codex does not support output-format '{output_format}'")

        sandbox = task_config.get("sandbox")
        if sandbox:
            if resuming:
                logger.warning(
                    "codex exec resume has no --sandbox; ignoring sandbox on resume"
                )
            elif sandbox in SANDBOX_MODES:
                cmd.extend(["--sandbox", sandbox])
            else:
                logger.warning(
                    f"codex sandbox must be one of {list(SANDBOX_MODES)}, got '{sandbox}'"
                )

        permissions = task_config.get("permissions", [])
        if permissions:
            if len(permissions) > 1:
                logger.warning(
                    f"codex uses only the first permission mode; ignoring {permissions[1:]}"
                )
            mode = permissions[0]
            if mode in ("plan", "read-only"):
                if resuming:
                    logger.warning(
                        "codex exec resume has no --sandbox; ignoring plan/read-only"
                    )
                else:
                    cmd.extend(["--sandbox", "read-only"])
            elif mode in SANDBOX_MODES:
                if resuming:
                    logger.warning(
                        "codex exec resume has no --sandbox; ignoring sandbox mode"
                    )
                else:
                    cmd.extend(["--sandbox", mode])
            elif mode in APPROVAL_MODES:
                cmd.extend(["-c", f"approval_policy={mode}"])
            else:
                logger.warning(
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

        raw_args = task_config.get("raw-args", [])
        if raw_args:
            cmd.extend(raw_args)

        # Prompt goes at the end as a direct argument (no flag).
        cmd.append(prompt)

        return cmd

    def check_available(self):
        """
        Check if Codex CLI is available in PATH.

        Returns:
            bool: True if the tool is available
        """
        return shutil.which("codex") is not None
