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


def _load_matrix():
    path = REPO_ROOT / "scripts" / "validate_pi_params.py"
    spec = importlib.util.spec_from_file_location("validate_pi_params", path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass field resolution can find the module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_matrix_covers_every_validated_option():
    """Every option the validator accepts is exercised by the live matrix."""
    matrix = _load_matrix()
    covered = set()
    for case in matrix.cases("provider/model"):
        covered.update(case.config)

    assert covered == set(SchemaValidator.PI_OPTION_SPEC)


def _load_vtcode_matrix():
    path = REPO_ROOT / "scripts" / "validate_vtcode_params.py"
    spec = importlib.util.spec_from_file_location("validate_vtcode_params", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vtcode_live_matrix_covers_every_validated_option():
    """Every vtcode option is either exercised live or explicitly warned-and-dropped."""
    matrix = _load_vtcode_matrix()
    covered = set()
    for case in matrix.cases("bifrost", "chunglet/deepseek-v4.1-flash"):
        covered.update(case.config)

    ignored = {"additional-dirs", "mcp-servers", "mcp-config-file"}
    assert covered | ignored == set(SchemaValidator.VTCODE_OPTION_SPEC)
    assert not (covered & ignored)


@pytest.mark.parametrize(
    "agent, config, expected",
    [
        ("vtcode", {"security-level": "yolo"}, "vtcode option 'security-level' must be one of"),
        ("vtcode", {"max-tool-calls": 0}, "vtcode option 'max-tool-calls' must be a positive integer"),
        ("vtcode", {"max-tool-calls": True}, "vtcode option 'max-tool-calls' must be a positive integer"),
        ("vtcode", {"quiet": "yes"}, "vtcode option 'quiet' must be a boolean"),
        ("vtcode", {"nope": 1}, "Unknown vtcode option 'nope'"),
        ("antigravity", {"effort": "max"}, "antigravity option 'effort' must be one of"),
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
