"""Shared end-to-end scenarios (tests/support/scenarios.py) against a real OpenCode v2 agent."""

import pytest

from tests.support.helpers import write_workflow
from tests.support.scenarios import SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_scenario_with_real_agent(scenario, tmp_path, run_workflow):
    workdir = tmp_path / "work"
    workdir.mkdir()
    workflow_path = write_workflow(tmp_path / "workflow.yaml", scenario.build(workdir))

    result = run_workflow(workflow_path, workdir=workdir)

    try:
        scenario.check(workdir, result.returncode, result.stderr)
    except AssertionError as error:
        raise AssertionError(f"{error}\n{result.describe()}") from error
