"""Parallel loop execution: workers, directory-pool, and git-worktrees.

Schema-level validation of these fields lives in ``test_schema.py``; this file
covers the runtime dispatch in ``CSVLoop._execute_parallel`` and JsonLoop.

The agent is mocked: ``executor.execute_single_task`` is patched where loops.py
imports it, so worker assignment and result collection are asserted directly.
"""

import os
import shutil
import subprocess
from unittest.mock import Mock, patch

import pytest

from src.executor import ExecutionError
from src.loops import CSVLoop, JsonLoop

GIT = shutil.which("git")


@pytest.fixture
def run_task():
    with patch("src.executor.execute_single_task") as mock:
        mock.return_value = {"status": "success", "exit_code": 0}
        yield mock


@pytest.fixture
def adapter():
    return Mock()


def _csv(tmp_path, text, name="rows.csv"):
    path = tmp_path / name
    path.write_text(text)
    return path


def _iteration_vars(call):
    return call.args[2]


@pytest.fixture
def two_rows(tmp_path):
    return _csv(tmp_path, "name,branch\nfirst,feature-a\nsecond,feature-b\n")


# ----------------------------------------------------------------- simple parallel


def test_simple_parallel_runs_every_row(two_rows, run_task, adapter):
    result = CSVLoop({}, {}).execute(
        {"prompt": "x"}, {"source": str(two_rows), "workers": 2}, {}, adapter, {"on-error": "fail"}
    )

    assert result == {
        "status": "success",
        "iterations": 2,
        "completed": ["row-1", "row-2"],
        "failed": [],
    }
    assert run_task.call_count == 2
    # No worker info without directory-pool or git-worktrees.
    assert "worker" not in _iteration_vars(run_task.call_args_list[0])["loop"]


def test_simple_parallel_dry_run_does_not_execute(two_rows, run_task, adapter, capsys):
    result = CSVLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(two_rows), "workers": 2},
        {},
        adapter,
        {"on-error": "fail"},
        dry_run=True,
    )

    assert result["iterations"] == 2
    assert "CSV loop (parallel):" in capsys.readouterr().err
    run_task.assert_not_called()


def test_simple_parallel_retry_recovers(two_rows, adapter):
    with patch("src.executor.execute_single_task") as mock:
        mock.side_effect = [
            ExecutionError("boom"),
            {"status": "success", "exit_code": 0},
            {"status": "success", "exit_code": 0},
            {"status": "failed", "exit_code": 1},
            {"status": "success", "exit_code": 0},
        ]

        result = CSVLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(two_rows), "workers": 2, "retry": {"max-attempts": 2, "on-failure": "retry"}},
            {},
            adapter,
            {"on-error": "fail"},
        )

    assert result["status"] == "success"
    assert sorted(result["completed"]) == ["row-1", "row-2"]


def test_simple_parallel_default_failure_raises(two_rows, adapter):
    with patch("src.executor.execute_single_task") as mock:
        mock.side_effect = ExecutionError("boom")

        with pytest.raises(ExecutionError):
            CSVLoop({}, {}).execute(
                {"prompt": "x"},
                {"source": str(two_rows), "workers": 2},
                {},
                adapter,
                {"on-error": "fail"},
            )


def test_simple_parallel_abort_raises(two_rows, adapter):
    with patch("src.executor.execute_single_task") as mock:
        mock.side_effect = ExecutionError("boom")

        with pytest.raises(ExecutionError, match="boom"):
            CSVLoop({}, {}).execute(
                {"prompt": "x"},
                {"source": str(two_rows), "workers": 2, "retry": {"max-attempts": 2, "on-failure": "abort"}},
                {},
                adapter,
                {"on-error": "fail"},
            )


# ------------------------------------------------------------------- directory-pool


def test_directory_pool_assigns_worker_dirs_round_robin(tmp_path, run_task, adapter):
    rows = _csv(
        tmp_path, "name\none\ntwo\nthree\n", "rows.csv"
    )
    pools = [tmp_path / "w0", tmp_path / "w1"]
    for pool in pools:
        pool.mkdir()

    result = CSVLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(rows), "workers": 2, "directory-pool": [str(p) for p in pools]},
        {},
        adapter,
        {"on-error": "fail", "directory": str(tmp_path)},
    )

    assert result["status"] == "success"
    assert result["iterations"] == 3
    assignments = set()
    for call in run_task.call_args_list:
        worker = _iteration_vars(call)["loop"]["worker"]
        assignments.add((worker["id"], worker["directory"]))
        # The task's working directory follows the worker's directory.
        assert call.args[4]["directory"] == worker["directory"]
    assert assignments == {
        (0, str(pools[0])),
        (1, str(pools[1])),
        (0, str(pools[0])),
    }


def test_directory_pool_requires_existing_directories(tmp_path, adapter, run_task):
    rows = _csv(tmp_path, "name\none\n")

    with pytest.raises(ExecutionError, match="Directory in pool does not exist"):
        CSVLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(rows), "workers": 2, "directory-pool": [str(tmp_path / "missing")]},
            {},
            adapter,
            {"on-error": "fail"},
        )

    with pytest.raises(ExecutionError, match="directory-pool cannot be empty"):
        CSVLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(rows), "workers": 2, "directory-pool": []},
            {},
            adapter,
            {"on-error": "fail"},
        )


def test_directory_pool_and_worktrees_are_mutually_exclusive(tmp_path, adapter, run_task):
    rows = _csv(tmp_path, "name\none\n")
    pool = tmp_path / "w0"
    pool.mkdir()

    with pytest.raises(ExecutionError, match="Cannot use both directory-pool and git-worktrees"):
        CSVLoop({}, {}).execute(
            {"prompt": "x"},
            {
                "source": str(rows),
                "workers": 2,
                "directory-pool": [str(pool)],
                "git-worktrees": {"enabled": True, "branch-field": "branch"},
            },
            {"gitroot": str(tmp_path)},
            adapter,
            {"on-error": "fail"},
        )


# -------------------------------------------------------------------- git worktrees


def test_git_worktrees_requires_enabled_and_branch_field(tmp_path, adapter, run_task):
    rows = _csv(tmp_path, "name,branch\none,feature-a\n")
    base = {"enabled": True, "base": str(tmp_path / "worktrees"), "branch-field": "branch"}

    with pytest.raises(ExecutionError, match="git-worktrees.enabled must be true"):
        CSVLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(rows), "workers": 2, "git-worktrees": {"base": base["base"]}},
            {"gitroot": str(tmp_path)},
            adapter,
            {"on-error": "fail"},
        )

    with pytest.raises(ExecutionError, match="git-worktrees.branch-field is required"):
        CSVLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(rows), "workers": 2, "git-worktrees": {"enabled": True, "base": base["base"]}},
            {"gitroot": str(tmp_path)},
            adapter,
            {"on-error": "fail"},
        )


def _git(cwd, *args):
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "agent-yaml tests",
        "GIT_AUTHOR_EMAIL": "tests@example.invalid",
        "GIT_COMMITTER_NAME": "agent-yaml tests",
        "GIT_COMMITTER_EMAIL": "tests@example.invalid",
    }
    return subprocess.run([GIT, *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


@pytest.mark.skipif(GIT is None, reason="git is not installed")
def test_git_worktrees_created_per_worker_and_cleaned_up(tmp_path, run_task, adapter):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "seed.txt").write_text("seed")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")
    for branch in ("feature-a", "feature-b"):
        _git(repo, "branch", branch)

    rows = _csv(repo, "name,branch\nTask A,feature-a\nTask B,feature-b\n", "branches.csv")

    result = CSVLoop({}, {}).execute(
        {"prompt": "x"},
        {
            "source": str(rows),
            "workers": 2,
            "git-worktrees": {
                "enabled": True,
                "base": "{{gitroot}}/.worktrees",
                "branch-field": "branch",
                "name-template": "worker-{{loop.worker.id}}",
                "cleanup": True,
            },
        },
        {"gitroot": str(repo)},
        adapter,
        {"on-error": "fail", "directory": str(repo)},
    )

    assert result["status"] == "success"
    assert sorted(result["completed"]) == ["row-1", "row-2"]
    for call in run_task.call_args_list:
        worker_dir = _iteration_vars(call)["loop"]["worker"]["directory"]
        assert ".worktrees" in worker_dir
        assert call.args[4]["directory"] == worker_dir

    worktrees = repo / ".worktrees"
    assert not worktrees.exists() or not any(worktrees.iterdir())


# --------------------------------------------------------------------- json parallel


def test_json_parallel_runs_every_item(tmp_path, run_task, adapter):
    path = tmp_path / "items.json"
    path.write_text('[{"id": 1}, {"id": 2}, {"id": 3}]')

    result = JsonLoop({}, {}).execute(
        {"prompt": "x"}, {"source": str(path), "workers": 3}, {}, adapter, {"on-error": "fail"}
    )

    assert result["status"] == "success"
    assert result["iterations"] == 3
    # Completion order is nondeterministic with as_completed().
    assert sorted(result["completed"]) == ["item-0", "item-1", "item-2"]
    assert result["failed"] == []
    assert run_task.call_count == 3
    assert "worker" not in _iteration_vars(run_task.call_args_list[0])["loop"]


def test_json_parallel_dry_run(tmp_path, run_task, adapter, capsys):
    path = tmp_path / "items.json"
    path.write_text('[{"id": 1}, {"id": 2}]')

    result = JsonLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(path), "workers": 2},
        {},
        adapter,
        {"on-error": "fail"},
        dry_run=True,
    )

    assert result["iterations"] == 2
    assert "JSON loop (parallel):" in capsys.readouterr().err
    run_task.assert_not_called()
