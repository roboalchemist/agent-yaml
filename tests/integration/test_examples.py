"""Every examples/*.yaml and tasks/*.yaml parses, passes schema validation, and dry-runs without calling the agent."""

import pytest

from agent_yaml.cli import run_workflow
from tests.support.helpers import EXAMPLES_DIR, REPO_ROOT

EXAMPLES = sorted(EXAMPLES_DIR.glob("*.yaml"))

TASKS_DIR = REPO_ROOT / "tasks"
TASKS = sorted(TASKS_DIR.glob("*.yaml"))
# tasks/ workflows that cannot run standalone:
SKIP_TASKS = {
    "base.yaml": "copy-paste base fragment: no top-level directory field",
    "under-development-rfc.yaml": "WIP file with invalid YAML (line 91)",
}


def test_examples_exist():
    assert len(EXAMPLES) >= 30


def test_tasks_exist():
    assert len(TASKS) >= 4


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.stem)
def test_example_dry_run(example, tmp_path, fake_opencode, capsys):
    returncode = run_workflow(
        str(example),
        dry_run=True,
        directory_override=str(tmp_path),
        cli_agent_override="opencode",
    )

    stderr = capsys.readouterr().err
    assert returncode == 0, stderr
    assert "Dry run complete" in stderr
    assert fake_opencode.calls() == []


@pytest.mark.parametrize("task", TASKS, ids=lambda path: path.stem)
def test_task_dry_run(task, tmp_path, fake_opencode, capsys):
    if task.name in SKIP_TASKS:
        pytest.skip(SKIP_TASKS[task.name])
    returncode = run_workflow(
        str(task),
        dry_run=True,
        directory_override=str(tmp_path),
        cli_agent_override="opencode",
    )

    stderr = capsys.readouterr().err
    assert returncode == 0, stderr
    assert "Dry run complete" in stderr
    assert fake_opencode.calls() == []
