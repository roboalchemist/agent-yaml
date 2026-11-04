"""
Unit tests for post-task validation and `retry` in src.executor.execute_single_task.

Validators run after the agent exits 0. The agent is simulated by a subprocess.run side
effect that writes the task's output file; validator paths are absolute under tmp_path.
"""

import re
from unittest.mock import patch

import pytest

from src.executor import ExecutionError, execute_single_task
from src.task_validators import ValidationError
from tests.support.helpers import completed

COMPLETE_REPORT = "# Report\n\n## Summary\n\nAll good.\n\n## Details\n\n- item one\n"
SUMMARY_ONLY = "# Report\n\n## Summary\n\nDetails are missing.\n"
ONE_VALIDATOR_FAILED = "Task 'my-task' completed but validation failed: 1/1 validators failed"
VALIDATOR_ERROR = "Task 'my-task' validation error: bad validator setup"


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
    """subprocess.run patched to an agent run that exits 0 (and writes nothing)."""
    with patch("subprocess.run", return_value=completed()) as run:
        yield run


def agent_writes(path, *outputs):
    """subprocess.run side effect: attempt N writes outputs[N-1] to `path` (None writes nothing)."""
    remaining = iter(outputs)

    def run(*args, **kwargs):
        content = next(remaining)
        if content is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return completed()

    return run


class TestValidation:
    def test_passing_validators_are_reported_with_success(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        report = tmp_path / "out" / "report.md"
        subprocess_run.side_effect = agent_writes(report, COMPLETE_REPORT)
        task = {
            "prompt": f"Create {report}",
            "validate": [
                {"file-exists": str(report)},
                {"file-not-empty": str(report)},
                {"contains": {"file": str(report), "text": "## Summary"}},
                {"contains": {"file": str(report), "text": "- item one"}},
            ],
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == "success"
        assert result["exit_code"] == 0
        validation = result["validation"]
        assert validation["all_passed"] is True
        assert (validation["total_count"], validation["failed_count"]) == (4, 0)
        assert [check["validator_type"] for check in validation["results"]] == [
            "file-exists",
            "file-not-empty",
            "contains",
            "contains",
        ]

    def test_validator_config_is_interpolated(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        report = tmp_path / "output.md"
        subprocess_run.side_effect = agent_writes(report, "# Report\n\nSUCCESS_MARKER\n")
        task = {
            "prompt": "Create report",
            "validate": [
                {"file-exists": "{{report-file}}"},
                {"contains": {"file": "{{report-file}}", "text": "{{marker}}"}},
            ],
        }
        resolved_vars = {"report-file": str(report), "marker": "SUCCESS_MARKER"}

        result = execute_single_task("my-task", task, resolved_vars, mock_adapter, workflow_config)

        assert result["status"] == "success"
        assert result["validation"]["all_passed"] is True
        assert [check["details"]["file"] for check in result["validation"]["results"]] == [
            str(report),
            str(report),
        ]

    @pytest.mark.parametrize(
        "agent_output, validator, error",
        [
            (None, {"file-exists": "{{report}}"}, "File does not exist"),
            ("", {"file-not-empty": "{{report}}"}, "File is empty"),
            (
                "# Report\n\n## Introduction\n",
                {"contains": {"file": "{{report}}", "text": "## Summary"}},
                "File does not contain expected text: '## Summary'",
            ),
        ],
        ids=["file-exists", "file-not-empty", "contains"],
    )
    def test_failed_validator_is_reported_in_result(
        self,
        agent_output,
        validator,
        error,
        mock_adapter,
        workflow_config,
        subprocess_run,
        tmp_path,
    ):
        report = tmp_path / "out" / "report.md"
        subprocess_run.side_effect = agent_writes(report, agent_output)
        task = {
            "prompt": "Write the report",
            "validate": [validator],
            "on-error": "continue",
            "retry": {"max-attempts": 1, "on-validation-failure": "retry"},
        }

        result = execute_single_task(
            "my-task", task, {"report": str(report)}, mock_adapter, workflow_config
        )

        assert result["status"] == "failed"
        assert result["exit_code"] == 0
        assert result["attempts"] == 1
        assert result["error_message"] == ONE_VALIDATOR_FAILED
        assert (result["validation"]["total_count"], result["validation"]["failed_count"]) == (1, 1)
        (check,) = result["validation"]["results"]
        assert check["validator_type"] == next(iter(validator))
        assert check["passed"] is False
        assert check["error_message"].startswith(error)

    def test_each_validator_result_is_reported_in_order(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        existing = tmp_path / "exists.md"
        existing.write_text("Content here\n")
        task = {
            "prompt": "Check files",
            "validate": [
                {"file-exists": str(existing)},
                {"file-not-empty": str(existing)},
                {"file-exists": str(tmp_path / "missing.md")},
            ],
            "on-error": "continue",
            "retry": {"max-attempts": 1, "on-validation-failure": "retry"},
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == "failed"
        assert result["error_message"].endswith("1/3 validators failed")
        validation = result["validation"]
        assert validation["all_passed"] is False
        assert (validation["total_count"], validation["failed_count"]) == (3, 1)
        assert [check["passed"] for check in validation["results"]] == [True, True, False]

    def test_validators_do_not_run_in_dry_run(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path, capsys
    ):
        task = {"prompt": "Do nothing", "validate": [{"file-exists": str(tmp_path / "never.md")}]}

        result = execute_single_task(
            "my-task", task, {}, mock_adapter, workflow_config, dry_run=True
        )

        assert result == {"task_name": "my-task", "status": "success", "exit_code": 0}
        subprocess_run.assert_not_called()
        assert "validator(s) for task" not in capsys.readouterr().err

    def test_validators_and_retry_are_skipped_when_agent_fails(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        subprocess_run.return_value = completed(returncode=1)
        task = {
            "prompt": "Generate output",
            "validate": [{"file-exists": str(tmp_path / "out.txt")}],
            "retry": {"max-attempts": 3, "on-validation-failure": "retry"},
            "on-error": "continue",
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result == {
            "task_name": "my-task",
            "status": "failed",
            "exit_code": 1,
            "error_message": "Task 'my-task' failed with exit code 1",
        }
        assert subprocess_run.call_count == 1

    def test_relative_validator_paths_resolve_against_process_cwd(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path, monkeypatch
    ):
        """Current behavior: not against the workflow `directory` the agent ran in."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        process_cwd = tmp_path / "cwd"
        process_cwd.mkdir()
        (process_cwd / "out.txt").write_text("written elsewhere")
        workflow_config["directory"] = str(work_dir)
        monkeypatch.chdir(process_cwd)
        task = {"prompt": "Write out.txt", "validate": [{"file-exists": "out.txt"}]}

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == "success"
        assert subprocess_run.call_args.kwargs["cwd"] == str(work_dir)
        assert result["validation"]["results"][0]["details"]["file"] == str(process_cwd / "out.txt")


class TestOnValidationFailure:
    @pytest.mark.parametrize(
        "task_extra",
        [
            {},
            {"retry": {"on-validation-failure": "fail"}},
            {"retry": {"max-attempts": 3, "on-validation-failure": "fail"}},
            {"on-error": "continue"},
        ],
        ids=["default", "explicit-fail", "fail-ignores-max-attempts", "fail-ignores-on-error"],
    )
    def test_fail_raises_without_retrying(
        self, task_extra, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {
            "prompt": "Create file",
            "validate": [{"file-exists": str(tmp_path / "missing.md")}],
            **task_extra,
        }

        with pytest.raises(ExecutionError, match=f"^{re.escape(ONE_VALIDATOR_FAILED)}$"):
            execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert subprocess_run.call_count == 1

    @pytest.mark.parametrize(
        "retry",
        [{"on-validation-failure": "skip"}, {"max-attempts": 3, "on-validation-failure": "skip"}],
        ids=["skip", "skip-ignores-max-attempts"],
    )
    def test_skip_marks_task_skipped_without_retrying(
        self, retry, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {
            "prompt": "Don't create file",
            "validate": [{"file-exists": str(tmp_path / "missing.md")}],
            "retry": retry,
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == "skipped"
        assert result["exit_code"] == 0
        assert result["attempts"] == 1
        assert result["validation"]["all_passed"] is False
        assert subprocess_run.call_count == 1


class TestRetry:
    @pytest.mark.parametrize(
        "outputs, max_attempts",
        [
            (["# Report\nMissing the summary.\n", COMPLETE_REPORT], 3),
            ([None, None, COMPLETE_REPORT], 4),
            ([None, "", SUMMARY_ONLY, COMPLETE_REPORT], 4),
        ],
        ids=["passes-on-attempt-2", "passes-on-attempt-3", "passes-on-last-allowed-attempt"],
    )
    def test_retries_until_validators_pass(
        self,
        outputs,
        max_attempts,
        mock_adapter,
        workflow_config,
        subprocess_run,
        tmp_path,
        capsys,
    ):
        report = tmp_path / "out" / "report.md"
        subprocess_run.side_effect = agent_writes(report, *outputs)
        task = {
            "prompt": "Create report",
            "validate": [
                {"file-exists": str(report)},
                {"contains": {"file": str(report), "text": "## Summary"}},
                {"contains": {"file": str(report), "text": "## Details"}},
            ],
            "retry": {"max-attempts": max_attempts, "on-validation-failure": "retry"},
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        attempts = len(outputs)
        assert result["status"] == "success"
        assert result["validation"]["all_passed"] is True
        assert subprocess_run.call_count == attempts
        assert mock_adapter.build_command.call_count == attempts
        err = capsys.readouterr().err
        assert f"⟳ Validation failed, retrying (attempt 1/{max_attempts})..." in err
        assert f"⟳ Retrying task 'my-task' (attempt {attempts}/{max_attempts})..." in err

    @pytest.mark.parametrize("max_attempts", [2, 3])
    def test_exhausted_retries_with_continue_return_failure(
        self, max_attempts, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {
            "prompt": "Try to create file",
            "validate": [{"file-exists": str(tmp_path / "never-created.md")}],
            "retry": {"max-attempts": max_attempts, "on-validation-failure": "retry"},
            "on-error": "continue",
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == "failed"
        assert result["exit_code"] == 0
        assert result["attempts"] == max_attempts
        assert result["error_message"].endswith(f"(failed after {max_attempts} attempts)")
        assert result["validation"]["all_passed"] is False
        assert subprocess_run.call_count == max_attempts

    def test_exhausted_retries_with_skip_return_skipped(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {
            "prompt": "Try to create file",
            "validate": [{"file-exists": str(tmp_path / "never-created.md")}],
            "retry": {"max-attempts": 2, "on-validation-failure": "retry"},
            "on-error": "skip",
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == "skipped"
        assert result["exit_code"] == 0
        assert result["attempts"] == 2
        assert "error_message" not in result
        assert subprocess_run.call_count == 2

    def test_exhausted_retries_with_fail_raise(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {
            "prompt": "Try to create file",
            "validate": [{"file-exists": str(tmp_path / "never-created.md")}],
            "retry": {"max-attempts": 3, "on-validation-failure": "retry"},
        }

        with pytest.raises(ExecutionError, match=r"\(failed after 3 attempts\)"):
            execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert subprocess_run.call_count == 3

    def test_retry_without_max_attempts_runs_once(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {
            "prompt": "Create file",
            "validate": [{"file-exists": str(tmp_path / "missing.md")}],
            "retry": {"on-validation-failure": "retry"},
            "on-error": "continue",
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert subprocess_run.call_count == 1
        assert result["attempts"] == 1
        assert result["error_message"] == ONE_VALIDATOR_FAILED


@pytest.fixture
def broken_validators():
    """run_validators raising ValidationError, as for a validator that cannot be set up."""
    error = ValidationError("bad validator setup")
    with patch("src.task_validators.run_validators", side_effect=error) as run_validators:
        yield run_validators


class TestValidatorErrors:
    """A ValidationError raised by run_validators follows the task's on-error strategy."""

    def test_with_fail_strategy_raises(
        self, mock_adapter, workflow_config, subprocess_run, broken_validators, tmp_path
    ):
        task = {"prompt": "Do work", "validate": [{"file-exists": str(tmp_path / "out.md")}]}

        with pytest.raises(ExecutionError, match=f"^{re.escape(VALIDATOR_ERROR)}$"):
            execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        broken_validators.assert_called_once()

    @pytest.mark.parametrize(
        "strategy, expected",
        [
            ("continue", {"status": "failed", "exit_code": 0, "error_message": VALIDATOR_ERROR}),
            ("skip", {"status": "skipped", "exit_code": 0}),
        ],
    )
    def test_with_continue_or_skip_returns_result(
        self,
        strategy,
        expected,
        mock_adapter,
        workflow_config,
        subprocess_run,
        broken_validators,
        tmp_path,
    ):
        task = {
            "prompt": "Do work",
            "validate": [{"file-exists": str(tmp_path / "out.md")}],
            "on-error": strategy,
        }

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result == {"task_name": "my-task", **expected}
