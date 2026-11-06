"""Schema validation for the pi adapter's cli-agent-config options."""

import importlib.util
import sys
from pathlib import Path

import pytest

from agent_yaml.validator import SchemaValidator, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]


def workflow(config=None, agent="pi", task=None):
    data = {
        "directory": "/tmp",
        "cli-agent": agent,
        "task": task if task is not None else [{"t": {"prompt": "x"}}],
    }
    if config is not None:
        data["cli-agent-config"] = config
    return data


def validate(data):
    return SchemaValidator().validate_schema(data)


def test_full_pi_config_passes():
    validate(
        workflow(
            {
                "model": "provider/model",
                "provider": "provider",
                "thinking": "high",
                "title": "run",
                "session-id": "abc",
                "output-format": "json",
                "tools": ["read", "bash"],
                "exclude-tools": "write,edit",
                "skip-confirmations": True,
                "no-tools": False,
                "continue": False,
                "session": True,
                "debug": True,
                "no-extensions": True,
                "timeout": 60,
                "raw-args": ["--flag"],
                "additional-dirs": ["/tmp"],
                "mcp-servers": ["notion"],
                "mcp-config-file": "/tmp/mcp.json",
            }
        )
    )


@pytest.mark.parametrize(
    "config, expected",
    [
        ({"nope": 1}, "Unknown pi option 'nope'"),
        ({"thinking": "bogus"}, "pi option 'thinking' must be one of"),
        ({"output-format": "xml"}, "pi option 'output-format' must be one of"),
        ({"output-format": "stream-json"}, "pi option 'output-format' must be one of"),
        ({"model": 5}, "pi option 'model' must be a string"),
        ({"skip-confirmations": "yes"}, "pi option 'skip-confirmations' must be a boolean"),
        ({"timeout": 0}, "pi option 'timeout' must be a positive number"),
        ({"timeout": True}, "pi option 'timeout' must be a positive number"),
        ({"timeout": "60"}, "pi option 'timeout' must be a positive number"),
        ({"tools": 5}, "pi option 'tools' must be a string or list of strings"),
        ({"tools": [""]}, "pi option 'tools' list entries must be non-empty strings"),
        ({"tools": "  "}, "pi option 'tools' must not be empty"),
        ({"raw-args": "--flag"}, "pi option 'raw-args' must be a list of strings"),
        ({"raw-args": [1]}, "pi option 'raw-args' must be a list of strings"),
        ({"session-id": "  "}, "pi option 'session-id' must not be empty"),
    ],
)
def test_invalid_pi_options_are_rejected(config, expected):
    with pytest.raises(ValidationError) as exc_info:
        validate(workflow(config))

    assert expected in str(exc_info.value)


def test_other_agents_are_not_held_to_pi_options():
    """The pi allowlist must not reject options that belong to another adapter."""
    validate(
        workflow(
            {"web-search": True, "agent": "plan"},
            agent="codex",
        )
    )


def test_task_level_pi_config_is_validated():
    task = [{"t": {"prompt": "x", "cli-agent-config": {"nope": 1}}}]

    with pytest.raises(ValidationError) as exc_info:
        validate(workflow(task=task))

    assert "Unknown pi option 'nope'" in str(exc_info.value)


def test_task_level_config_is_ignored_for_other_agents():
    task = [{"t": {"prompt": "x", "cli-agent-config": {"agent": "plan"}}}]

    validate(workflow(agent="opencode", task=task))


MATRICES = {
    "opencode": ("validate_opencode_params", ("anthropic/claude-sonnet-5-5",)),
    "claude": ("validate_claude_params", ("sonnet",)),
    "codex": ("validate_codex_params", ("gpt-5-codex",)),
    "pi": ("validate_pi_params", ("provider/model",)),
    "vtcode": ("validate_vtcode_params", ("chunglet/deepseek-v4.1-flash",)),
    "antigravity": ("validate_antigravity_params", ("gemini-3.8-flash-high",)),
}


def _load_matrix(module_name):
    path = REPO_ROOT / "scripts" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass field resolution can find the module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("agent", list(MATRICES))
def test_live_matrix_covers_every_surface(agent):
    """Every mapped surface has a live case, or a recorded exemption."""
    from agent_yaml.adapters import ADAPTERS

    module_name, args = MATRICES[agent]
    matrix = _load_matrix(module_name)
    adapter = ADAPTERS[agent]

    covered = set()
    for case in matrix.cases(*args):
        covered.update(case.config)

    ignored = {key for key, option in adapter.option_spec.items() if option.kind == "ignored"}
    exempt = set(adapter.live_exempt)
    required = set(adapter.option_spec) - ignored - exempt - {"model", "provider"}

    assert not (required - covered), f"{agent} has surfaces without a live case"
    assert not (covered & ignored), f"{agent} covers ignored options"


def test_antigravity_json_schema_requires_json_output():
    with pytest.raises(ValidationError) as exc_info:
        validate(workflow({"json-schema": "schema.json"}, agent="antigravity"))
    assert "requires output-format 'json' or 'stream-json'" in str(exc_info.value)


@pytest.mark.parametrize(
    "agent, config",
    [
        ("opencode", {"output-format": "xml"}),
        ("claude", {"output-format": "xml"}),
        ("codex", {"output-format": "xml"}),
        ("pi", {"output-format": "stream-json"}),
        ("vtcode", {"output-format": "stream-json"}),
        ("antigravity", {"output-format": "xml"}),
        ("opencode", {"not-a-key": 1}),
        ("claude", {"not-a-key": 1}),
        ("codex", {"not-a-key": 1}),
    ],
)
def test_every_harness_validates_its_option_spec(agent, config):
    with pytest.raises(ValidationError):
        validate(workflow(config, agent=agent))


@pytest.mark.parametrize(
    "agent, config, expected",
    [
        ("vtcode", {"security-level": "yolo"}, "vtcode option 'security-level' must be one of"),
        ("vtcode", {"max-tool-calls": 0}, "vtcode option 'max-tool-calls' must be a positive integer"),
        ("vtcode", {"max-tool-calls": True}, "vtcode option 'max-tool-calls' must be a positive integer"),
        ("vtcode", {"quiet": "yes"}, "vtcode option 'quiet' must be a boolean"),
        ("vtcode", {"nope": 1}, "Unknown vtcode option 'nope'"),
        ("antigravity", {"effort": "ultra"}, "antigravity option 'effort' must be one of"),
        ("antigravity", {"output-format": "xml"}, "antigravity option 'output-format' must be one of"),
        ("antigravity", {"sandbox": "yes"}, "antigravity option 'sandbox' must be a boolean"),
        ("antigravity", {"nope": 1}, "Unknown antigravity option 'nope'"),
    ],
)
def test_invalid_vtcode_and_antigravity_options_are_rejected(agent, config, expected):
    with pytest.raises(ValidationError) as exc_info:
        validate(workflow(config, agent=agent))

    assert expected in str(exc_info.value)


def test_valid_vtcode_and_antigravity_configs_pass():
    validate(
        workflow(
            {
                "provider": "deepseek",
                "model": "deepseek-flash",
                "security-level": "permissive",
                "max-tool-calls": 30,
                "quiet": True,
            },
            agent="vtcode",
        )
    )
    validate(
        workflow(
            {
                "model": "gemini-4-argon-high",
                "effort": "high",
                "output-format": "stream-json",
                "sandbox": True,
            },
            agent="antigravity",
        )
    )


def test_gemini_is_no_longer_supported():
    with pytest.raises(ValidationError):
        validate(workflow(None, agent="gemini"))
