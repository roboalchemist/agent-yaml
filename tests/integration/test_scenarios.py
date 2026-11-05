"""Shared end-to-end scenarios (tests/support/scenarios.py) against the fake OpenCode agent."""

import pytest

from agent_yaml.cli import run_workflow
from tests.support.helpers import write_workflow
from tests.support.scenarios import SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_scenario_with_fake_agent(scenario, tmp_path, fake_opencode, capsys):
    workdir = tmp_path / "work"
    workdir.mkdir()
    workflow_path = write_workflow(tmp_path / "workflow.yaml", scenario.build(workdir))

    returncode = run_workflow(str(workflow_path))

    scenario.check(workdir, returncode, capsys.readouterr().err)
    calls = fake_opencode.calls()
    assert len(calls) == scenario.agent_calls
    for call in calls:
        assert call["argv"][:2] == ["run", "--standalone"]
        assert call["argv"][-2] == "--"
