"""Unit tests for agent_yaml/adapters: task config → agent argv, availability checks, get_adapter()."""

import inspect
import shutil
from unittest.mock import patch

import pytest

from agent_yaml.adapters import (
    ClaudeAdapter,
    CLINotFoundError,
    CodexAdapter,
    GeminiAdapter,
    OpenCodeAdapter,
    PiAdapter,
    QwenAdapter,
    UnsupportedCLIError,
    get_adapter,
)

PROMPT = "Test prompt"

ADAPTERS = {
    "claude": ClaudeAdapter,
    "gemini": GeminiAdapter,
    "qwen": QwenAdapter,
    "codex": CodexAdapter,
    "opencode": OpenCodeAdapter,
    "pi": PiAdapter,
}

# Executables each adapter looks for on PATH (Claude takes either, preferring claude-code).
EXECUTABLES = {
    ClaudeAdapter: ("claude-code", "claude"),
    GeminiAdapter: ("gemini",),
    QwenAdapter: ("qwen",),
    CodexAdapter: ("codex",),
    OpenCodeAdapter: ("opencode",),
    PiAdapter: ("pi",),
}
ALL_EXECUTABLES = tuple(name for names in EXECUTABLES.values() for name in names)

every_adapter = pytest.mark.parametrize("adapter_cls", list(ADAPTERS.values()), ids=list(ADAPTERS))


def build(adapter_cls, config, prompt=PROMPT):
    return adapter_cls().build_command(config, prompt)


def build_with_warnings(adapter_cls, config, prompt=PROMPT):
    """build(), plus the messages passed to the adapter module's logger.warning, in order."""
    with patch.object(inspect.getmodule(adapter_cls).logger, "warning") as warning:
        cmd = build(adapter_cls, config, prompt)
    return cmd, [call.args[0] for call in warning.call_args_list]


def has_tokens(cmd, *tokens):
    """True if `tokens` appear in `cmd` consecutively and in this order."""
    n = len(tokens)
    return any(cmd[i : i + n] == list(tokens) for i in range(len(cmd) - n + 1))


@pytest.fixture
def path_has(monkeypatch):
    """path_has(*names): shutil.which (looked up by the adapters at call time) finds only these."""

    def install(*names):
        def which(cmd, *args, **kwargs):
            return f"/usr/local/bin/{cmd}" if cmd in names else None

        monkeypatch.setattr(shutil, "which", which)

    return install


@pytest.fixture(autouse=True)
def every_agent_on_path(path_has):
    """Never consult the real PATH; by default every agent executable is found."""
    path_has(*ALL_EXECUTABLES)


MINIMAL_COMMANDS = [
    pytest.param(
        ClaudeAdapter, ["claude-code", "--tools", "default", "--print", PROMPT], id="claude"
    ),
    pytest.param(GeminiAdapter, ["gemini", "-p", PROMPT], id="gemini"),
    pytest.param(QwenAdapter, ["qwen", "-p", PROMPT], id="qwen"),
    pytest.param(CodexAdapter, ["codex", "exec", "--skip-git-repo-check", PROMPT], id="codex"),
    pytest.param(OpenCodeAdapter, ["opencode", "run", "--standalone", "--", PROMPT], id="opencode"),
    pytest.param(PiAdapter, ["pi", "-p", "--no-session", "--", PROMPT], id="pi"),
]

CANONICAL_COMMANDS = [
    pytest.param(
        ClaudeAdapter,
        {
            "skip-confirmations": True,
            "additional-dirs": ["/tmp", "/var/tmp"],
            "model": "sonnet-4.5",
            "debug": True,
            "output-format": "json",
            "session-id": "workflow-123",
            "mcp-servers": ["notion", "linear"],
            "mcp-config-file": "/path/to/config.json",
            "permissions": ["plan"],
            "raw-args": ["--verbose"],
            "timeout": 3600,
        },
        [
            "claude-code",
            "--dangerously-skip-permissions",
            "--add-dir=/tmp",
            "--add-dir=/var/tmp",
            *["--model", "claude-sonnet-4-5-20250929"],
            "--debug",
            *["--tools", "default"],
            *["--output-format", "json"],
            *["--session-id", "workflow-123"],
            *["--allowed-mcp-server-names", "notion", "linear"],
            *["--mcp-config", "/path/to/config.json"],
            *["--permission-mode", "plan"],
            "--verbose",
            *["--print", PROMPT],
        ],
        id="claude",
    ),
    pytest.param(
        GeminiAdapter,
        {
            "skip-confirmations": True,
            "additional-dirs": ["/tmp", "/var/tmp"],
            "model": "gemini-2.5-pro",
            "debug": True,
            "output-format": "json",
            "mcp-servers": ["notion", "linear"],
            "permissions": ["plan"],
            "extensions": ["ext1", "ext2"],
            "checkpointing": True,
            "screen-reader": True,
            "telemetry": True,
            "web-search": True,
            "raw-args": ["--verbose"],
            "timeout": 3600,
        },
        [
            "gemini",
            "--yolo",
            *["--include-directories", "/tmp", "/var/tmp"],
            *["--model", "gemini-2.5-pro"],
            "--debug",
            *["--output-format", "json"],
            *["--allowed-mcp-server-names", "notion", "linear"],
            *["--approval-mode", "plan"],
            *["--extensions", "ext1", "ext2"],
            "--checkpointing",
            "--telemetry",
            "--screen-reader",
            "--verbose",
            *["-p", PROMPT],
        ],
        id="gemini",
    ),
    pytest.param(
        QwenAdapter,
        {
            "skip-confirmations": True,
            "additional-dirs": ["/tmp", "/var/tmp"],
            "model": "qwen3-coder",
            "debug": True,
            "mcp-servers": ["notion", "linear"],
            "permissions": ["plan"],
            "extensions": ["ext1", "ext2"],
            "checkpointing": True,
            "screen-reader": True,
            "telemetry": True,
            "web-search": True,
            "search-api-key": "sk-tavily-12345",
            "custom": {
                "qwen": {
                    "openai-base-url": "https://api.custom.com",
                    "openai-api-key": "sk-openai-12345",
                    "vlm-switch-mode": "auto",
                }
            },
            "raw-args": ["--verbose"],
            "timeout": 3600,
        },
        [
            "qwen",
            "--yolo",
            *["--include-directories", "/tmp", "/var/tmp"],
            *["--model", "qwen3-coder-plus"],
            "--debug",
            *["--allowed-mcp-server-names", "notion", "linear"],
            *["--approval-mode", "plan"],
            *["--extensions", "ext1", "ext2"],
            "--checkpointing",
            "--screen-reader",
            "--telemetry",
            *["--tavily-api-key", "sk-tavily-12345"],
            *["--openai-base-url", "https://api.custom.com"],
            *["--openai-api-key", "sk-openai-12345"],
            *["--vlm-switch-mode", "auto"],
            "--verbose",
            *["-p", PROMPT],
        ],
        id="qwen",
    ),
    pytest.param(
        CodexAdapter,
        {
            "skip-confirmations": True,
            "additional-dirs": ["/tmp"],
            "model": "gpt-5-codex",
            "debug": True,
            "permissions": ["on-failure"],
            "web-search": True,
            "raw-args": ["--verbose"],
            "timeout": 3600,
        },
        [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--full-auto",
            *["-C", "/tmp"],
            *["--model", "gpt-5-codex"],
            *["-c", "debug=true"],
            *["-a", "on-failure"],
            "--search",
            "--verbose",
            PROMPT,
        ],
        id="codex",
    ),
    pytest.param(
        OpenCodeAdapter,
        {
            "skip-confirmations": True,
            "model": "sonnet-5.5",
            "agent": "build",
            "output-format": "json",
            "session-id": "ses_abc123",
            "title": "Nightly docs run",
            "debug": True,
            "raw-args": ["--thinking"],
            "timeout": 3600,
        },
        [
            "opencode",
            "run",
            "--standalone",
            "--auto",
            *["--model", "anthropic/claude-sonnet-5-5"],
            *["--agent", "build"],
            *["--format", "json"],
            *["--session", "ses_abc123"],
            *["--title", "Nightly docs run"],
            "--print-logs",
            "--thinking",
            *["--", PROMPT],
        ],
        id="opencode",
    ),
]

PROMPT_TAILS = [
    pytest.param(ClaudeAdapter, ["--print", PROMPT], id="claude"),
    pytest.param(GeminiAdapter, ["-p", PROMPT], id="gemini"),
    pytest.param(QwenAdapter, ["-p", PROMPT], id="qwen"),
    pytest.param(CodexAdapter, [PROMPT], id="codex"),
    pytest.param(OpenCodeAdapter, ["--", PROMPT], id="opencode"),
    pytest.param(PiAdapter, ["--", PROMPT], id="pi"),
]


class TestCommandShape:
    @pytest.mark.parametrize("adapter_cls, expected", MINIMAL_COMMANDS)
    def test_empty_config_builds_the_minimal_command(self, adapter_cls, expected):
        assert build(adapter_cls, {}) == expected

    @pytest.mark.parametrize("adapter_cls, config, expected", CANONICAL_COMMANDS)
    def test_canonical_full_command(self, adapter_cls, config, expected):
        assert build(adapter_cls, config) == expected

    @pytest.mark.parametrize("adapter_cls, prompt_tail", PROMPT_TAILS)
    def test_raw_args_go_between_translated_flags_and_the_prompt(self, adapter_cls, prompt_tail):
        config = {"skip-confirmations": True, "debug": True}
        raw_args = ["--ide", "--custom-flag=value"]

        without_raw = build(adapter_cls, config)
        with_raw = build(adapter_cls, {**config, "raw-args": raw_args})

        assert without_raw[-len(prompt_tail) :] == prompt_tail
        assert with_raw == without_raw[: -len(prompt_tail)] + raw_args + prompt_tail

    @every_adapter
    def test_timeout_is_never_passed_to_the_cli(self, adapter_cls):
        cmd = build(adapter_cls, {"timeout": 3600})

        assert cmd == build(adapter_cls, {})
        assert not any("timeout" in arg or "3600" in arg for arg in cmd)


SKIP_CONFIRMATIONS_FLAGS = [
    pytest.param(ClaudeAdapter, "--dangerously-skip-permissions", id="claude"),
    pytest.param(GeminiAdapter, "--yolo", id="gemini"),
    pytest.param(QwenAdapter, "--yolo", id="qwen"),
    pytest.param(CodexAdapter, "--full-auto", id="codex"),
    pytest.param(OpenCodeAdapter, "--auto", id="opencode"),
    pytest.param(PiAdapter, "--approve", id="pi"),
]

ADDITIONAL_DIRS_FLAGS = [
    pytest.param(
        ClaudeAdapter,
        ["/tmp", "/var/tmp"],
        ["--add-dir=/tmp", "--add-dir=/var/tmp"],
        id="claude",
    ),
    pytest.param(
        GeminiAdapter,
        ["/tmp", "/var/tmp"],
        ["--include-directories", "/tmp", "/var/tmp"],
        id="gemini",
    ),
    pytest.param(
        QwenAdapter,
        ["/tmp", "/var/tmp"],
        ["--include-directories", "/tmp", "/var/tmp"],
        id="qwen",
    ),
    pytest.param(CodexAdapter, ["/tmp"], ["-C", "/tmp"], id="codex-single-dir"),
]

MODEL_FLAGS = [
    pytest.param(ClaudeAdapter, "custom-model-name", "custom-model-name", id="claude-passthrough"),
    pytest.param(GeminiAdapter, "gemini-2.5-pro", "gemini-2.5-pro", id="gemini-passthrough"),
    pytest.param(QwenAdapter, "custom-qwen-model", "custom-qwen-model", id="qwen-passthrough"),
    pytest.param(CodexAdapter, "gpt-5-codex", "gpt-5-codex", id="codex-passthrough"),
    pytest.param(
        OpenCodeAdapter,
        "anthropic/claude-haiku-5-5",
        "anthropic/claude-haiku-5-5",
        id="opencode-passthrough",
    ),
    pytest.param(PiAdapter, "zai/glm-5.1", "zai/glm-5.1", id="pi-passthrough"),
    pytest.param(PiAdapter, "zai/glm-5.1:high", "zai/glm-5.1:high", id="pi-thinking-suffix"),
    pytest.param(
        ClaudeAdapter, "sonnet-4.5", "claude-sonnet-4-5-20250929", id="claude-maps-sonnet-4.5"
    ),
    pytest.param(ClaudeAdapter, "opus-4", "claude-opus-4", id="claude-maps-opus-4"),
    pytest.param(QwenAdapter, "qwen3-coder", "qwen3-coder-plus", id="qwen-maps-qwen3-coder"),
    pytest.param(
        OpenCodeAdapter, "haiku-5.5", "anthropic/claude-haiku-5-5", id="opencode-alias-haiku-5.5"
    ),
    pytest.param(
        OpenCodeAdapter,
        "sonnet-5.5",
        "anthropic/claude-sonnet-5-5",
        id="opencode-alias-sonnet-5.5",
    ),
    pytest.param(
        OpenCodeAdapter, "opus-5.5", "anthropic/claude-opus-5-5", id="opencode-alias-opus-5.5"
    ),
]

DEBUG_FLAGS = [
    pytest.param(ClaudeAdapter, ["--debug"], id="claude"),
    pytest.param(GeminiAdapter, ["--debug"], id="gemini"),
    pytest.param(QwenAdapter, ["--debug"], id="qwen"),
    pytest.param(CodexAdapter, ["-c", "debug=true"], id="codex"),
    pytest.param(OpenCodeAdapter, ["--print-logs"], id="opencode"),
    pytest.param(PiAdapter, ["--verbose"], id="pi"),
]

JSON_OUTPUT_FLAGS = [
    pytest.param(ClaudeAdapter, ["--output-format", "json"], id="claude"),
    pytest.param(GeminiAdapter, ["--output-format", "json"], id="gemini"),
    pytest.param(OpenCodeAdapter, ["--format", "json"], id="opencode"),
    pytest.param(PiAdapter, ["--mode", "json"], id="pi"),
]

SESSION_ID_FLAGS = [
    pytest.param(ClaudeAdapter, "--session-id", id="claude"),
    pytest.param(OpenCodeAdapter, "--session", id="opencode"),
    pytest.param(PiAdapter, "--session-id", id="pi"),
]

PERMISSION_FLAGS = [
    pytest.param(ClaudeAdapter, "plan", ["--permission-mode", "plan"], id="claude"),
    pytest.param(GeminiAdapter, "plan", ["--approval-mode", "plan"], id="gemini"),
    pytest.param(QwenAdapter, "plan", ["--approval-mode", "plan"], id="qwen"),
    pytest.param(QwenAdapter, "auto_edit", ["--approval-mode", "auto_edit"], id="qwen-auto_edit"),
    pytest.param(CodexAdapter, "on-failure", ["-a", "on-failure"], id="codex"),
    pytest.param(OpenCodeAdapter, "plan", ["--agent", "plan"], id="opencode"),
]

WEB_SEARCH_FLAGS = [
    pytest.param(CodexAdapter, {"web-search": True}, ["--search"], id="codex"),
    pytest.param(
        QwenAdapter,
        {"web-search": True, "search-api-key": "sk-tavily-12345"},
        ["--tavily-api-key", "sk-tavily-12345"],
        id="qwen-tavily-key",
    ),
]

WEB_SEARCH_WITHOUT_FLAGS = [
    pytest.param(GeminiAdapter, {"web-search": True}, id="gemini-built-in"),
    pytest.param(QwenAdapter, {"web-search": True}, id="qwen-without-api-key"),
    pytest.param(QwenAdapter, {"search-api-key": "sk-tavily-12345"}, id="qwen-key-without-search"),
]


class TestSharedSettings:
    """Generic cli-agent-config keys that several adapters translate to their own flags."""

    @pytest.mark.parametrize("adapter_cls, flag", SKIP_CONFIRMATIONS_FLAGS)
    def test_skip_confirmations(self, adapter_cls, flag):
        assert flag in build(adapter_cls, {"skip-confirmations": True})
        assert flag not in build(adapter_cls, {"skip-confirmations": False})
        assert flag not in build(adapter_cls, {})

    @pytest.mark.parametrize("adapter_cls, dirs, tokens", ADDITIONAL_DIRS_FLAGS)
    def test_additional_dirs(self, adapter_cls, dirs, tokens):
        assert has_tokens(build(adapter_cls, {"additional-dirs": dirs}), *tokens)

    @pytest.mark.parametrize("adapter_cls, model, expected", MODEL_FLAGS)
    def test_model(self, adapter_cls, model, expected):
        cmd = build(adapter_cls, {"model": model})

        assert cmd.count("--model") == 1
        assert cmd[cmd.index("--model") + 1] == expected

    @pytest.mark.parametrize("adapter_cls, tokens", DEBUG_FLAGS)
    def test_debug(self, adapter_cls, tokens):
        assert has_tokens(build(adapter_cls, {"debug": True}), *tokens)
        assert not has_tokens(build(adapter_cls, {"debug": False}), *tokens)

    @pytest.mark.parametrize("adapter_cls, tokens", JSON_OUTPUT_FLAGS)
    def test_json_output_format(self, adapter_cls, tokens):
        assert has_tokens(build(adapter_cls, {"output-format": "json"}), *tokens)

    @pytest.mark.parametrize("adapter_cls, flag", SESSION_ID_FLAGS)
    def test_session_id(self, adapter_cls, flag):
        assert has_tokens(
            build(adapter_cls, {"session-id": "my-session-123"}), flag, "my-session-123"
        )

    @pytest.mark.parametrize(
        "adapter_cls", [ClaudeAdapter, GeminiAdapter, QwenAdapter], ids=["claude", "gemini", "qwen"]
    )
    def test_mcp_servers(self, adapter_cls):
        cmd = build(adapter_cls, {"mcp-servers": ["notion", "linear", "tavily"]})

        assert has_tokens(cmd, "--allowed-mcp-server-names", "notion", "linear", "tavily")

    @pytest.mark.parametrize("adapter_cls, mode, tokens", PERMISSION_FLAGS)
    def test_first_permission_mode_is_used(self, adapter_cls, mode, tokens):
        cmd = build(adapter_cls, {"permissions": [mode, "ignored-mode"]})

        assert has_tokens(cmd, *tokens)
        assert "ignored-mode" not in cmd

    @pytest.mark.parametrize("adapter_cls, config, tokens", WEB_SEARCH_FLAGS)
    def test_web_search_flag(self, adapter_cls, config, tokens):
        assert has_tokens(build(adapter_cls, config), *tokens)

    @pytest.mark.parametrize("adapter_cls, config", WEB_SEARCH_WITHOUT_FLAGS)
    def test_web_search_settings_that_add_no_flag(self, adapter_cls, config):
        assert build(adapter_cls, config) == build(adapter_cls, {})


UNSUPPORTED_SETTINGS = [
    pytest.param(
        GeminiAdapter,
        "session-id",
        "my-session-123",
        "Gemini does not support session-id configuration",
        id="gemini-session-id",
    ),
    pytest.param(
        GeminiAdapter,
        "mcp-config-file",
        "/path/to/mcp-config.json",
        "Gemini does not support mcp-config-file configuration",
        id="gemini-mcp-config-file",
    ),
    pytest.param(
        QwenAdapter,
        "output-format",
        "json",
        "Qwen does not support output-format configuration",
        id="qwen-output-format",
    ),
    pytest.param(
        QwenAdapter,
        "session-id",
        "my-session-123",
        "Qwen does not support session-id configuration",
        id="qwen-session-id",
    ),
    pytest.param(
        QwenAdapter,
        "mcp-config-file",
        "/path/to/mcp-config.json",
        "Qwen does not support mcp-config-file configuration",
        id="qwen-mcp-config-file",
    ),
    pytest.param(
        CodexAdapter,
        "output-format",
        "json",
        "Codex does not support output-format configuration",
        id="codex-output-format",
    ),
    pytest.param(
        OpenCodeAdapter,
        "output-format",
        "stream-json",
        "OpenCode does not support output-format 'stream-json'",
        id="opencode-output-format-stream-json",
    ),
    pytest.param(
        OpenCodeAdapter,
        "output-format",
        "markdown",
        "OpenCode does not support output-format 'markdown'",
        id="opencode-output-format-other",
    ),
    pytest.param(
        OpenCodeAdapter,
        "additional-dirs",
        ["/srv/extra-dir"],
        "OpenCode adapter ignores 'additional-dirs'; configure it in opencode.json",
        id="opencode-additional-dirs",
    ),
    pytest.param(
        OpenCodeAdapter,
        "mcp-servers",
        ["notion", "linear"],
        "OpenCode adapter ignores 'mcp-servers'; configure it in opencode.json",
        id="opencode-mcp-servers",
    ),
    pytest.param(
        OpenCodeAdapter,
        "mcp-config-file",
        "/path/to/mcp-config.json",
        "OpenCode adapter ignores 'mcp-config-file'; configure it in opencode.json",
        id="opencode-mcp-config-file",
    ),
]


class TestUnsupportedSettings:
    """Settings an adapter cannot express: a warning is logged and the argv is left untouched."""

    @pytest.mark.parametrize("adapter_cls, key, value, message", UNSUPPORTED_SETTINGS)
    def test_setting_warns_and_never_reaches_argv(self, adapter_cls, key, value, message):
        cmd, warnings = build_with_warnings(adapter_cls, {key: value})

        assert warnings == [message]
        assert cmd == build(adapter_cls, {})

    @pytest.mark.parametrize(
        "adapter_cls, config",
        [
            pytest.param(
                GeminiAdapter,
                {"session-id": "s-1", "mcp-config-file": "/path/to/mcp.json"},
                id="gemini",
            ),
            pytest.param(
                QwenAdapter,
                {
                    "output-format": "json",
                    "session-id": "s-1",
                    "mcp-config-file": "/path/to/mcp.json",
                },
                id="qwen",
            ),
            pytest.param(
                OpenCodeAdapter,
                {
                    "additional-dirs": ["/srv/extra-dir"],
                    "mcp-servers": ["notion"],
                    "mcp-config-file": "/path/to/mcp.json",
                },
                id="opencode",
            ),
        ],
    )
    def test_each_unsupported_setting_warns_separately(self, adapter_cls, config):
        cmd, warnings = build_with_warnings(adapter_cls, config)

        assert len(warnings) == len(config)
        assert all(any(key in message for message in warnings) for key in config)
        assert cmd == build(adapter_cls, {})


class TestCheckAvailable:
    @pytest.mark.parametrize(
        "adapter_cls, executable",
        [
            pytest.param(adapter_cls, executable, id=executable)
            for adapter_cls, executables in EXECUTABLES.items()
            for executable in executables
        ],
    )
    def test_available_when_its_executable_is_on_path(self, path_has, adapter_cls, executable):
        path_has(executable)

        assert adapter_cls().check_available() is True

    @every_adapter
    def test_unavailable_without_its_own_executable(self, path_has, adapter_cls):
        path_has(*(name for name in ALL_EXECUTABLES if name not in EXECUTABLES[adapter_cls]))

        assert adapter_cls().check_available() is False


class TestClaudeAdapter:
    @pytest.mark.parametrize(
        "on_path, executable",
        [
            pytest.param(("claude-code", "claude"), "claude-code", id="prefers-claude-code"),
            pytest.param(("claude",), "claude", id="falls-back-to-claude"),
            pytest.param((), "claude", id="defaults-to-claude-when-neither-is-found"),
        ],
    )
    def test_executable_detection(self, path_has, on_path, executable):
        path_has(*on_path)

        assert build(ClaudeAdapter, {})[0] == executable

    @pytest.mark.parametrize(
        "config, format_tokens",
        [
            pytest.param({}, [], id="text-by-default"),
            pytest.param({"output-format": "text"}, [], id="explicit-text"),
            pytest.param(
                {"output-format": "stream-json"},
                ["--verbose", "--output-format", "stream-json"],
                id="stream-json-needs-verbose",
            ),
            pytest.param(
                {"debug": True},
                ["--verbose", "--output-format", "stream-json"],
                id="debug-defaults-to-stream-json",
            ),
            pytest.param(
                {"debug": True, "output-format": "text"}, [], id="explicit-text-beats-debug"
            ),
            pytest.param(
                {"debug": True, "output-format": "json"},
                ["--output-format", "json"],
                id="explicit-json-beats-debug",
            ),
        ],
    )
    def test_output_format(self, config, format_tokens):
        cmd = build(ClaudeAdapter, config)

        format_related = {"--verbose", "--output-format", "text", "json", "stream-json"}
        assert [arg for arg in cmd if arg in format_related] == format_tokens

    @pytest.mark.parametrize(
        "config, tools",
        [
            pytest.param({}, "default", id="all-tools-by-default"),
            pytest.param({"tools": "Read"}, "Read", id="explicit"),
        ],
    )
    def test_tools(self, config, tools):
        cmd = build(ClaudeAdapter, config)

        assert cmd.count("--tools") == 1
        assert cmd[cmd.index("--tools") + 1] == tools

    def test_mcp_config_file(self):
        cmd = build(ClaudeAdapter, {"mcp-config-file": "/path/to/mcp-config.json"})

        assert has_tokens(cmd, "--mcp-config", "/path/to/mcp-config.json")


class TestGeminiAndQwenAdapters:
    """Gemini CLI flags that the Qwen CLI (a Gemini fork) shares."""

    @pytest.mark.parametrize("adapter_cls", [GeminiAdapter, QwenAdapter], ids=["gemini", "qwen"])
    @pytest.mark.parametrize(
        "config, tokens",
        [
            pytest.param(
                {"extensions": ["ext1", "ext2", "ext3"]},
                ["--extensions", "ext1", "ext2", "ext3"],
                id="extensions",
            ),
            pytest.param({"checkpointing": True}, ["--checkpointing"], id="checkpointing"),
            pytest.param({"telemetry": True}, ["--telemetry"], id="telemetry"),
            pytest.param({"screen-reader": True}, ["--screen-reader"], id="screen-reader"),
        ],
    )
    def test_extra_flags(self, adapter_cls, config, tokens):
        assert has_tokens(build(adapter_cls, config), *tokens)


class TestQwenAdapter:
    @pytest.mark.parametrize(
        "option, value, tokens",
        [
            pytest.param(
                "openai-base-url",
                "https://api.custom.com",
                ["--openai-base-url", "https://api.custom.com"],
                id="openai-base-url",
            ),
            pytest.param(
                "openai-api-key",
                "sk-openai-12345",
                ["--openai-api-key", "sk-openai-12345"],
                id="openai-api-key",
            ),
            pytest.param(
                "vlm-switch-mode", "auto", ["--vlm-switch-mode", "auto"], id="vlm-switch-mode"
            ),
        ],
    )
    def test_custom_qwen_options(self, option, value, tokens):
        cmd = build(QwenAdapter, {"custom": {"qwen": {option: value}}})

        assert has_tokens(cmd, *tokens)


class TestCodexAdapter:
    @pytest.mark.parametrize(
        "config",
        [
            pytest.param({"skip-confirmations": True, "model": "gpt-5-codex"}, id="options"),
            pytest.param({"debug": True, "raw-args": ["--json"]}, id="raw-args"),
        ],
    )
    def test_runs_exec_without_git_check_and_takes_a_bare_prompt(self, config):
        cmd = build(CodexAdapter, config)

        assert cmd[:3] == ["codex", "exec", "--skip-git-repo-check"]
        assert cmd[-1] == PROMPT
        assert "-p" not in cmd
        assert "--print" not in cmd

    def test_only_the_first_additional_dir_is_used(self):
        cmd, warnings = build_with_warnings(
            CodexAdapter, {"additional-dirs": ["/tmp", "/var/tmp", "/private"]}
        )

        assert has_tokens(cmd, "-C", "/tmp")
        assert cmd.count("-C") == 1
        assert "/var/tmp" not in cmd
        assert "/private" not in cmd
        assert len(warnings) == 1
        assert "only supports one directory" in warnings[0]
        assert "/var/tmp" in warnings[0]
        assert "/private" in warnings[0]

    def test_single_additional_dir_does_not_warn(self):
        cmd, warnings = build_with_warnings(CodexAdapter, {"additional-dirs": ["/tmp"]})

        assert has_tokens(cmd, "-C", "/tmp")
        assert warnings == []

    def test_debug_is_a_config_override_not_a_flag(self):
        cmd = build(CodexAdapter, {"debug": True})

        assert has_tokens(cmd, "-c", "debug=true")
        assert "--debug" not in cmd


OPENCODE_SERVER = "http://127.0.0.1:4096"


class TestOpenCodeAdapter:
    @pytest.mark.parametrize(
        "prompt",
        [
            pytest.param("Summarize the README", id="plain"),
            pytest.param("-v means verbose in this repo", id="leading-dash"),
            pytest.param("--help", id="looks-like-a-flag"),
            pytest.param("Fix these:\n- first bug\n--second bug", id="multi-line"),
        ],
    )
    @pytest.mark.parametrize(
        "config",
        [
            pytest.param({}, id="no-options"),
            pytest.param(
                {
                    "skip-confirmations": True,
                    "model": "anthropic/claude-haiku-5-5",
                    "raw-args": ["--thinking"],
                },
                id="options",
            ),
        ],
    )
    def test_prompt_is_the_last_argument_right_after_double_dash(self, config, prompt):
        cmd = build(OpenCodeAdapter, config, prompt)

        assert cmd[-2:] == ["--", prompt]
        assert cmd.count("--") == 1

    def test_model_without_provider_passes_through_with_a_warning(self):
        cmd, warnings = build_with_warnings(OpenCodeAdapter, {"model": "claude-haiku-5-5"})

        assert has_tokens(cmd, "--model", "claude-haiku-5-5")
        assert len(warnings) == 1
        assert "provider/model" in warnings[0]
        assert "'claude-haiku-5-5'" in warnings[0]

    @pytest.mark.parametrize(
        "model",
        [
            pytest.param("anthropic/claude-haiku-5-5", id="provider-model"),
            pytest.param("openai/gpt-5#high", id="with-variant"),
            pytest.param("haiku-5.5", id="alias"),
        ],
    )
    def test_provider_qualified_model_does_not_warn(self, model):
        _, warnings = build_with_warnings(OpenCodeAdapter, {"model": model})

        assert warnings == []

    @pytest.mark.parametrize(
        "config, agent",
        [
            pytest.param({"agent": "build"}, "build", id="agent"),
            pytest.param({"permissions": ["plan"]}, "plan", id="permissions-pick-the-agent"),
            pytest.param(
                {"agent": "build", "permissions": ["plan"]}, "build", id="explicit-agent-wins"
            ),
        ],
    )
    def test_agent(self, config, agent):
        cmd = build(OpenCodeAdapter, config)

        assert cmd.count("--agent") == 1
        assert cmd[cmd.index("--agent") + 1] == agent

    def test_text_output_format_is_the_default(self):
        cmd, warnings = build_with_warnings(OpenCodeAdapter, {"output-format": "text"})

        assert cmd == build(OpenCodeAdapter, {})
        assert warnings == []

    def test_title(self):
        cmd = build(OpenCodeAdapter, {"title": "Nightly docs run"})

        assert has_tokens(cmd, "--title", "Nightly docs run")

    @pytest.mark.parametrize(
        "config, connection_flags",
        [
            pytest.param({"standalone": True}, ["--standalone"], id="standalone"),
            pytest.param({"standalone": False}, [], id="shared-background-service"),
            pytest.param({"server": OPENCODE_SERVER}, ["--server", OPENCODE_SERVER], id="server"),
            pytest.param(
                {"server": OPENCODE_SERVER, "standalone": True},
                ["--server", OPENCODE_SERVER],
                id="server-replaces-standalone",
            ),
        ],
    )
    def test_connection_mode(self, config, connection_flags):
        """The connection flags are everything between `run` and `--` when nothing else is set."""
        cmd = build(OpenCodeAdapter, config)

        assert cmd[:2] == ["opencode", "run"]
        assert cmd[2 : cmd.index("--")] == connection_flags


class TestGetAdapter:
    @pytest.mark.parametrize("name, adapter_cls", list(ADAPTERS.items()), ids=list(ADAPTERS))
    def test_returns_the_matching_adapter(self, path_has, name, adapter_cls):
        path_has(*EXECUTABLES[adapter_cls])

        adapter = get_adapter(name)

        assert type(adapter) is adapter_cls
        assert adapter.tool_name == name

    @pytest.mark.parametrize(
        "name, adapter_cls",
        [
            pytest.param("CLAUDE", ClaudeAdapter, id="upper"),
            pytest.param("Claude", ClaudeAdapter, id="title"),
            pytest.param("cLaUdE", ClaudeAdapter, id="mixed"),
            pytest.param("  qwen  ", QwenAdapter, id="padded"),
            pytest.param("  OpenCode ", OpenCodeAdapter, id="padded-mixed-case"),
            pytest.param("\tCodex\n", CodexAdapter, id="tab-and-newline"),
        ],
    )
    def test_agent_names_are_case_and_whitespace_insensitive(self, name, adapter_cls):
        assert type(get_adapter(name)) is adapter_cls

    @pytest.mark.parametrize(
        "name",
        [
            pytest.param("unknown-cli", id="unknown"),
            pytest.param("invalid", id="invalid"),
            pytest.param("", id="empty"),
            pytest.param("  INVALID-CLI  ", id="padded-upper"),
        ],
    )
    def test_unknown_agent_is_rejected_with_the_supported_list(self, name):
        with pytest.raises(UnsupportedCLIError) as exc_info:
            get_adapter(name)

        message = str(exc_info.value)
        assert f"Unsupported CLI agent: '{name}'" in message
        assert "Supported agents are: claude, codex, gemini, opencode, pi, qwen" in message

    @pytest.mark.parametrize(
        "name, hint, which_command",
        [
            pytest.param("claude", "claude-code or claude", "which claude-code", id="claude"),
            pytest.param("gemini", "gemini", "which gemini", id="gemini"),
            pytest.param("qwen", "qwen", "which qwen", id="qwen"),
            pytest.param("codex", "codex", "which codex", id="codex"),
            pytest.param("opencode", "opencode", "which opencode", id="opencode"),
            pytest.param("  OpenCode ", "opencode", "which opencode", id="opencode-unnormalized"),
        ],
    )
    def test_missing_executable_raises_with_install_hint(self, path_has, name, hint, which_command):
        path_has()

        with pytest.raises(CLINotFoundError) as exc_info:
            get_adapter(name)

        message = str(exc_info.value)
        assert f"CLI executable not found for '{name}'" in message
        assert f"Please ensure '{hint}' is installed and available in PATH" in message
        assert f"Run '{which_command}' to verify installation" in message


class TestPiAdapter:
    """pi-specific mapping: sessions, tools, provider, and ignored options."""

    def test_sessions_are_ephemeral_by_default(self):
        assert build(PiAdapter, {}) == ["pi", "-p", "--no-session", "--", PROMPT]

    def test_session_true_keeps_persistence(self):
        cmd = build(PiAdapter, {"session": True})

        assert cmd[:3] == ["pi", "-p", "--"]
        assert "--no-session" not in cmd

    def test_session_id_wins_over_continue_and_no_session(self):
        cmd = build(PiAdapter, {"session-id": "abc123", "continue": True})

        assert has_tokens(cmd, "--session-id", "abc123")
        assert "--continue" not in cmd
        assert "--no-session" not in cmd

    def test_continue_flag(self):
        cmd = build(PiAdapter, {"continue": True})

        assert "--continue" in cmd
        assert "--no-session" not in cmd

    def test_tools_list_is_joined(self):
        cmd = build(PiAdapter, {"tools": ["read", "bash", "grep"]})

        assert has_tokens(cmd, "--tools", "read,bash,grep")

    def test_tools_string_passes_through(self):
        cmd = build(PiAdapter, {"tools": "read,grep"})

        assert has_tokens(cmd, "--tools", "read,grep")

    def test_tool_denylists_and_no_tools(self):
        cmd = build(PiAdapter, {"no-tools": True, "exclude-tools": ["write", "edit"]})

        assert "--no-tools" in cmd
        assert has_tokens(cmd, "--exclude-tools", "write,edit")

    def test_provider_and_thinking(self):
        cmd = build(PiAdapter, {"provider": "zai", "thinking": "high"})

        assert has_tokens(cmd, "--provider", "zai")
        assert has_tokens(cmd, "--thinking", "high")

    def test_title_maps_to_name(self):
        cmd = build(PiAdapter, {"title": "Nightly docs"})

        assert has_tokens(cmd, "--name", "Nightly docs")

    def test_no_extensions_flag(self):
        assert "--no-extensions" in build(PiAdapter, {"no-extensions": True})

    @pytest.mark.parametrize("option", ["additional-dirs", "mcp-servers", "mcp-config-file"])
    def test_unsupported_options_warn_and_are_dropped(self, option):
        cmd, warnings = build_with_warnings(PiAdapter, {option: ["x"]})

        assert cmd == build(PiAdapter, {})
        assert any(option in message for message in warnings)

    def test_unknown_output_format_warns(self):
        cmd, warnings = build_with_warnings(PiAdapter, {"output-format": "stream-json"})

        assert "--mode" not in cmd
        assert any("stream-json" in message for message in warnings)

    def test_adapter_requests_empty_stdin(self):
        assert PiAdapter.needs_empty_stdin is True
