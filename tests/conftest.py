"""
Shared pytest configuration for agent-yaml.

Tiers (see tests/README.md):
- tests/unit         one module at a time; the agent subprocess is mocked
- tests/integration  whole workflows from real YAML files through run_workflow/main;
                     the agent is the deterministic fake in tests/support/fake_opencode.py
- tests/live         real OpenCode v2 + real model; skipped unless `pytest --live`
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent_yaml.adapters.base import BaseAdapter
from tests.support.helpers import FIXTURES_DIR, REPO_ROOT, SUPPORT_DIR

LIVE_DIR = Path(__file__).resolve().parent / "live"


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run tests/live: real OpenCode v2 agent and model, API key read from 1Password",
    )


def pytest_collection_modifyitems(config, items):
    run_live = config.getoption("--live")
    skip_live = pytest.mark.skip(reason="live tier: run with --live")
    for item in items:
        if LIVE_DIR in item.path.parents:
            item.add_marker(pytest.mark.live)
        if item.get_closest_marker("live") and not run_live:
            item.add_marker(skip_live)


@pytest.fixture
def fixtures_dir():
    """Path to tests/fixtures (static data files)."""
    return FIXTURES_DIR


@pytest.fixture
def mock_adapter():
    """Adapter double with the BaseAdapter interface; builds ["agent", "--", "prompt"]."""
    adapter = Mock(spec=BaseAdapter)
    adapter.build_command.return_value = ["agent", "--", "prompt"]
    adapter.check_available.return_value = True
    return adapter


class FakeAgent:
    """Handle on the fake `opencode` installed by the `fake_opencode` fixture."""

    def __init__(self, log_path):
        self.log_path = log_path

    def calls(self):
        """One dict per invocation: {"argv": [...], "cwd": "...", "prompt": "..."}."""
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]


@pytest.fixture
def fake_opencode(tmp_path_factory, monkeypatch):
    """
    Put a deterministic fake `opencode` first on PATH.

    It runs the ```bash block of each prompt (cwd and env inherited) and exits with
    that script's status, so workflows with `cli-agent: opencode` execute for real
    without a model. Invocations are recorded; read them with `.calls()`.
    """
    bin_dir = tmp_path_factory.mktemp("fake-bin")
    shim = bin_dir / "opencode"
    shim.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{SUPPORT_DIR / "fake_opencode.py"}" "$@"\n'
    )
    shim.chmod(0o755)
    log_path = bin_dir / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log_path))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    return FakeAgent(log_path)
