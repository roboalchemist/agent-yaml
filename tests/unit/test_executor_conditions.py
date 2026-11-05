"""
Unit tests for skip-if and when handling in agent_yaml.executor.execute_single_task.

Both are checked before the agent runs, skip-if first. Relative skip-if paths resolve
against the task's working directory (task `directory`, else the workflow `directory`).
"""

import re
from unittest.mock import patch

import pytest

from agent_yaml.executor import ExecutionError, execute_single_task
from agent_yaml.skip_conditions import check_skip_conditions
from tests.support.helpers import completed

WHEN_ERROR = "Task 'my-task' when condition error: Failed to evaluate when expression: boom"


@pytest.fixture
def workflow_config(tmp_path):
    """Workflow config whose working directory and workflow-file directory are tmp_path."""
    return {
        "directory": str(tmp_path),
        "_workflow_dir": str(tmp_path),
        "cli-agent-config": {},
        "on-error": "fail",
    }


@pytest.fixture
def subprocess_run():
    """subprocess.run patched to an agent run that exits 0."""
    with patch("subprocess.run", return_value=completed()) as run:
        yield run


class TestSkipIf:
    @pytest.mark.parametrize(
        "skip_if",
        [
            {"file-exists": "{{out-dir}}/done.flag"},
            {"file-contains": {"path": "{{out-dir}}/status.txt", "text": "SUCCESS"}},
        ],
        ids=["file-exists", "file-contains"],
    )
    def test_met_condition_skips_without_running_agent(
        self, skip_if, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        (tmp_path / "done.flag").write_text("")
        (tmp_path / "status.txt").write_text("Status: SUCCESS")
        task = {"prompt": "Deploy", "skip-if": skip_if}

        result = execute_single_task(
            "my-task", task, {"out-dir": str(tmp_path)}, mock_adapter, workflow_config
        )

        assert result["status"] == "skipped"
        assert result["exit_code"] == 0
        assert result["skip_condition"]["should_skip"] is True
        assert result["skip_condition"]["condition_type"] == next(iter(skip_if))
        mock_adapter.build_command.assert_not_called()
        subprocess_run.assert_not_called()

    @pytest.mark.parametrize(
        "skip_if",
        [
            {"file-exists": "{{out-dir}}/done.flag"},
            {"file-contains": {"path": "{{out-dir}}/status.txt", "text": "SUCCESS"}},
        ],
        ids=["file-missing", "text-missing"],
    )
    def test_unmet_condition_runs_task(
        self, skip_if, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        (tmp_path / "status.txt").write_text("Status: PENDING")
        task = {"prompt": "Deploy", "skip-if": skip_if}

        result = execute_single_task(
            "my-task", task, {"out-dir": str(tmp_path)}, mock_adapter, workflow_config
        )

        assert result == {"task_name": "my-task", "status": "success", "exit_code": 0}
        mock_adapter.build_command.assert_called_once()
        subprocess_run.assert_called_once()

    def test_condition_error_with_fail_strategy_raises(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        missing = tmp_path / "missing.txt"
        task = {
            "prompt": "Deploy",
            "skip-if": {"file-contains": {"path": str(missing), "text": "x"}},
        }

        with pytest.raises(ExecutionError) as excinfo:
            execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert str(excinfo.value) == (
            "Task 'my-task' skip-if condition error: "
            f"file-contains skip condition: file does not exist: {missing}"
        )
        subprocess_run.assert_not_called()

    @pytest.mark.parametrize(
        "workflow_on_error, task_on_error, status, has_message",
        [
            ("fail", {"on-error": "continue"}, "failed", True),
            ("fail", {"on-error": "skip"}, "skipped", False),
            ("continue", {}, "failed", True),
        ],
        ids=["task-continue", "task-skip", "workflow-continue"],
    )
    def test_condition_error_with_continue_or_skip_returns_result(
        self,
        workflow_on_error,
        task_on_error,
        status,
        has_message,
        mock_adapter,
        workflow_config,
        subprocess_run,
        tmp_path,
    ):
        workflow_config["on-error"] = workflow_on_error
        task = {
            "prompt": "Deploy",
            "skip-if": {"file-contains": {"path": str(tmp_path / "missing.txt"), "text": "x"}},
            **task_on_error,
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == status
        assert result["exit_code"] == -1
        assert ("error_message" in result) is has_message
        subprocess_run.assert_not_called()

    def test_invalid_skip_if_config_is_a_condition_error(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        task = {"prompt": "Deploy", "skip-if": {"file-modified": "done.flag"}}

        with pytest.raises(
            ExecutionError,
            match=re.escape("skip-if condition error: Unknown skip condition type: file-modified"),
        ):
            execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        subprocess_run.assert_not_called()


class TestSkipIfWorkingDirectory:
    @pytest.mark.parametrize(
        "skip_if",
        [
            {"file-exists": "deployed.flag"},
            {"file-contains": {"path": "deployed.flag", "text": "deployed"}},
        ],
        ids=["file-exists", "file-contains"],
    )
    def test_relative_path_resolves_against_workflow_directory(
        self, skip_if, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        project = tmp_path / "project"
        project.mkdir()
        (project / "deployed.flag").write_text("deployed")
        workflow_config["directory"] = str(project)

        result = execute_single_task(
            "my-task", {"prompt": "Deploy", "skip-if": skip_if}, {}, mock_adapter, workflow_config
        )

        assert result["status"] == "skipped"
        assert result["skip_condition"]["details"]["file"] == str(project / "deployed.flag")

    @pytest.mark.parametrize(
        "task_directory",
        ["{workflow}/task-dir", "task-dir"],
        ids=["absolute-task-directory", "relative-task-directory"],
    )
    def test_relative_path_resolves_against_task_directory(
        self, task_directory, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        workflow_dir = tmp_path / "workflow"
        task_dir = workflow_dir / "task-dir"
        task_dir.mkdir(parents=True)
        (task_dir / "task-flag.txt").write_text("task-specific")
        workflow_config["directory"] = str(workflow_dir)
        task = {
            "prompt": "Deploy",
            "skip-if": {"file-exists": "task-flag.txt"},
            "directory": task_directory.replace("{workflow}", str(workflow_dir)),
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == "skipped"
        assert result["skip_condition"]["details"]["file"] == str(task_dir / "task-flag.txt")


class TestCheckSkipConditionsWorkingDir:
    """check_skip_conditions called directly with and without a working_dir."""

    @pytest.mark.parametrize(
        "skip_if",
        [
            {"file-exists": "marker.txt"},
            {"file-contains": {"path": "marker.txt", "text": "marked"}},
        ],
        ids=["file-exists", "file-contains"],
    )
    def test_relative_path_resolves_against_working_dir(self, skip_if, tmp_path):
        (tmp_path / "marker.txt").write_text("marked")

        result = check_skip_conditions(skip_if, {}, str(tmp_path))

        assert result.should_skip is True
        assert result.details["file"] == str(tmp_path / "marker.txt")

    @pytest.mark.parametrize(
        "skip_if",
        [
            {"file-exists": "{{marker}}"},
            {"file-contains": {"path": "{{marker}}", "text": "marked"}},
        ],
        ids=["file-exists", "file-contains"],
    )
    def test_absolute_path_ignores_working_dir(self, skip_if, tmp_path):
        marker = tmp_path / "data" / "marker.txt"
        marker.parent.mkdir()
        marker.write_text("marked")
        other_dir = tmp_path / "other"
        other_dir.mkdir()

        result = check_skip_conditions(skip_if, {"marker": str(marker)}, str(other_dir))

        assert result.should_skip is True
        assert result.details["file"] == str(marker)

    def test_relative_path_without_working_dir_uses_process_cwd(self, tmp_path, monkeypatch):
        (tmp_path / "marker.txt").write_text("marked")
        monkeypatch.chdir(tmp_path)

        result = check_skip_conditions({"file-exists": "marker.txt"}, {})

        assert result.should_skip is True
        assert result.details["file"] == str(tmp_path / "marker.txt")


class TestWhen:
    @pytest.mark.parametrize(
        "when, resolved_vars",
        [
            ("{{environment}} == 'production'", {"environment": "production"}),
            (
                "{{environment}} == 'prod' and {{tests-pass}}",
                {"environment": "prod", "tests-pass": True},
            ),
            ("{{environment}} == 'prod' or {{force}}", {"environment": "staging", "force": True}),
        ],
        ids=["equality", "and", "or"],
    )
    def test_true_condition_runs_task(
        self, when, resolved_vars, mock_adapter, workflow_config, subprocess_run
    ):
        task = {"prompt": "Deploy", "when": when}

        result = execute_single_task("my-task", task, resolved_vars, mock_adapter, workflow_config)

        assert result == {"task_name": "my-task", "status": "success", "exit_code": 0}
        mock_adapter.build_command.assert_called_once()
        subprocess_run.assert_called_once()

    @pytest.mark.parametrize(
        "when, reason",
        [
            ("{{environment}} == 'production'", "when condition not satisfied"),
            ("", "when expression is empty"),
            ("   ", "when expression is empty"),
        ],
        ids=["false", "empty", "whitespace"],
    )
    def test_false_or_empty_condition_skips_without_running_agent(
        self, when, reason, mock_adapter, workflow_config, subprocess_run
    ):
        task = {"prompt": "Deploy", "when": when}

        result = execute_single_task(
            "my-task", task, {"environment": "staging"}, mock_adapter, workflow_config
        )

        assert result["status"] == "skipped"
        assert result["exit_code"] == 0
        assert result["when_condition"]["should_execute"] is False
        assert result["when_condition"]["reason"].startswith(reason)
        mock_adapter.build_command.assert_not_called()
        subprocess_run.assert_not_called()

    def test_evaluation_error_with_fail_strategy_raises(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        task = {"prompt": "Deploy", "when": "{{ready}}"}

        with patch("agent_yaml.when_conditions.evaluate_expression", side_effect=RuntimeError("boom")):
            with pytest.raises(ExecutionError, match=re.escape(WHEN_ERROR)):
                execute_single_task("my-task", task, {"ready": True}, mock_adapter, workflow_config)

        subprocess_run.assert_not_called()

    @pytest.mark.parametrize(
        "strategy, expected",
        [
            ("continue", {"status": "failed", "exit_code": -1, "error_message": WHEN_ERROR}),
            ("skip", {"status": "skipped", "exit_code": -1}),
        ],
    )
    def test_evaluation_error_with_continue_or_skip_returns_result(
        self, strategy, expected, mock_adapter, workflow_config, subprocess_run
    ):
        task = {"prompt": "Deploy", "when": "{{ready}}", "on-error": strategy}

        with patch("agent_yaml.when_conditions.evaluate_expression", side_effect=RuntimeError("boom")):
            result = execute_single_task(
                "my-task", task, {"ready": True}, mock_adapter, workflow_config
            )

        assert result == {"task_name": "my-task", **expected}
        subprocess_run.assert_not_called()


class TestConditionOrder:
    @pytest.mark.parametrize(
        "environment", ["production", "staging"], ids=["when-true", "when-false"]
    )
    def test_skip_if_is_checked_before_when(
        self, environment, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        (tmp_path / "done.flag").write_text("")
        task = {
            "prompt": "Deploy",
            "skip-if": {"file-exists": str(tmp_path / "done.flag")},
            "when": "{{environment}} == 'production'",
        }

        result = execute_single_task(
            "my-task", task, {"environment": environment}, mock_adapter, workflow_config
        )

        assert result["status"] == "skipped"
        assert result["skip_condition"]["should_skip"] is True
        assert "when_condition" not in result
        mock_adapter.build_command.assert_not_called()

    def test_when_is_checked_after_unmet_skip_if(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {
            "prompt": "Deploy",
            "skip-if": {"file-exists": str(tmp_path / "not-there.flag")},
            "when": "{{environment}} == 'production'",
        }

        result = execute_single_task(
            "my-task", task, {"environment": "staging"}, mock_adapter, workflow_config
        )

        assert result["status"] == "skipped"
        assert result["when_condition"]["should_execute"] is False
        assert "skip_condition" not in result
        mock_adapter.build_command.assert_not_called()
