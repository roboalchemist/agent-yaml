"""Keep docs/CONFIG_SURFACES.md honest.

Parses the harness × config-surface matrix from the docs page and checks every
cell against the real adapter behaviour and the schema validator:

* a mapped cell shows a flag that must appear in the built command
* "ignored" means the command must not change
* "ignored + warning" also requires a warning naming the option
* "rejected" means the validator must refuse the option
* "passthrough" means the raw args land in argv
* "executor" means the option is not a CLI flag
* "no `--flag`" means the option removes that flag
"""

import logging
import re
from pathlib import Path

import pytest

from agent_yaml.adapters import (
    AntigravityAdapter,
    ClaudeAdapter,
    CodexAdapter,
    OpenCodeAdapter,
    PiAdapter,
    VTCodeAdapter,
)
from agent_yaml.validator import SchemaValidator, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "CONFIG_SURFACES.md"

ADAPTERS = {
    "opencode": OpenCodeAdapter,
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "pi": PiAdapter,
    "vtcode": VTCodeAdapter,
    "antigravity": AntigravityAdapter,
}
STRICT_AGENTS = {"pi", "vtcode", "antigravity"}

# One representative value per surface. Values must satisfy the strict
# validators for the harnesses that accept the surface.
SAMPLES = {
    "model": "test-model",
    "provider": "test-provider",
    "session-id": "sid",
    "continue": True,
    "title": "T",
    "agent": "build",
    "permissions": ["plan"],
    "output-format": "json",
    "skip-confirmations": True,
    "debug": True,
    "raw-args": ["--custom"],
    "additional-dirs": ["/tmp"],
    "mcp-servers": ["notion"],
    "mcp-config-file": "/tmp/mcp.json",
    "tools": "read,bash",
    "exclude-tools": ["write"],
    "thinking": "high",
    "no-tools": True,
    "session": True,
    "no-extensions": True,
    "web-search": True,
    "server": "http://localhost:4096",
    "standalone": False,
    "security-level": "permissive",
    "max-tool-calls": 8,
    "quiet": True,
    "effort": "high",
    "sandbox": True,
    "json-schema": "schema.json",
    "last-message-file": "/tmp/last.txt",
    "system-prompt": "Be terse.",
    "append-system-prompt": ["Be brief."],
    "settings": "{}",
    "disable-slash-commands": True,
    "max-budget": 2.5,
    "fallback-model": "sonnet",
    "project": "demo",
    "log-file": "/tmp/agy.log",
    "log-level": "debug",
    "color": "never",
    "files": ["/tmp/file.txt"],
    "images": ["/tmp/img.png"],
    "enable": ["web_search"],
    "ignore-user-config": True,
    "ignore-rules": True,
    "events-file": "/tmp/events.jsonl",
    "max-concurrent-ops": 3,
    "api-rate-limit": 20,
    "config-overrides": ["model=test"],
    "session-dir": "/tmp/sessions",
    "no-context-files": True,
    "no-mcp": True,
    "no-builtin-tools": True,
    "skills": ["/tmp/skills"],
    "extensions": ["builtin:mcp"],
    "timeout": 300,
}

# Values whose meaning depends on the harness (same key, different type/semantics).
AGENT_SAMPLES = {
    "provider": {"codex": "ollama"},
    "sandbox": {"codex": "read-only"},
    "session": {"pi": True, "claude": False, "codex": False},
}

HEADER = "| Surface | opencode | claude | codex | pi | vtcode | antigravity |"


def parse_matrix():
    """Return {(surface, agent): cell} from the docs table."""
    lines = DOC.read_text().splitlines()
    start = lines.index(HEADER)
    rows = {}
    header = [cell.strip() for cell in lines[start].strip("|").split("|")]
    agents = header[1:]
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        surface = cells[0].strip("`")
        for agent, cell in zip(agents, cells[1:]):
            rows[(surface, agent)] = cell
    return rows


def build(adapter_cls, config):
    logger = logging.getLogger(adapter_cls.__module__)
    messages = []

    class Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = Capture()
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        cmd = adapter_cls().build_command(config, "PROMPT")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    return cmd, messages


def assert_rejected(agent, surface, sample):
    assert agent in STRICT_AGENTS, f"{agent} is not strict, it cannot reject {surface}"
    data = {
        "directory": "/tmp",
        "cli-agent": agent,
        "cli-agent-config": {surface: sample},
        "task": [{"t": {"prompt": "x"}}],
    }
    with pytest.raises(ValidationError) as exc_info:
        SchemaValidator().validate_schema(data)
    assert f"Unknown {agent} option '{surface}'" in str(exc_info.value)


def assert_cell(surface, agent, cell):
    adapter_cls = ADAPTERS[agent]
    sample = AGENT_SAMPLES.get(surface, {}).get(agent, SAMPLES[surface])
    baseline, _ = build(adapter_cls, {})
    cmd, warnings = build(adapter_cls, {surface: sample})

    if cell == "rejected":
        assert_rejected(agent, surface, sample)
        return

    if cell == "executor":
        assert surface == "timeout"
        assert cmd == baseline
        return

    if cell == "passthrough":
        for value in sample:
            assert value in cmd
        return

    if cell.startswith("no "):
        flag = re.search(r"`([^`]+)`", cell).group(1)
        assert flag not in cmd, f"{surface} should remove {flag}, got {cmd}"
        return

    if "ignored" in cell:
        assert cmd == baseline, f"{surface} should not change the command, got {cmd}"
        warned = any(surface in message for message in warnings)
        if "+ warning" in cell:
            assert warned, f"{surface} should warn on {agent}"
        else:
            assert not warned, f"{surface} should not warn on {agent}: {warnings}"
        return

    flag = re.search(r"`([^`]+)`", cell).group(1)
    assert any(arg == flag or arg.startswith(flag) for arg in cmd), (
        f"{surface} on {agent} should emit {flag}, got {cmd}"
    )


def test_matrix_surface_names_match_samples():
    matrix = parse_matrix()
    documented = {surface for surface, _ in matrix}
    assert documented == set(SAMPLES)


@pytest.mark.parametrize(
    "surface, agent",
    sorted(parse_matrix()),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_matrix_cell_matches_adapter(surface, agent):
    cell = parse_matrix()[(surface, agent)]
    assert cell, f"empty cell for {surface} × {agent}"
    assert_cell(surface, agent, cell)


def test_rejected_cells_only_on_strict_harnesses():
    for (surface, agent), cell in parse_matrix().items():
        if cell == "rejected":
            assert agent in STRICT_AGENTS
