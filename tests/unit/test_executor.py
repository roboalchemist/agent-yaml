"""
Unit tests for agent_yaml.executor.execute_single_task: running the agent, on-error strategies,
prompt composition, cli-agent-config merging, directory override, dry-run and debug modes.

The agent subprocess is mocked; `mock_adapter` builds the command ["agent", "--", "prompt"].
"""

import copy
import io
import json
import logging
import os
import subprocess
import time
from unittest.mock import patch

import pytest

from agent_yaml.executor import ExecutionError, execute_single_task
from tests.support.helpers import completed

COMMAND = ["agent", "--", "prompt"]


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


def sent_config(adapter):
    """The merged cli-agent-config the executor passed to adapter.build_command."""
    return adapter.build_command.call_args.args[0]


def sent_prompt(adapter):
    """The final prompt the executor passed to adapter.build_command."""
    return adapter.build_command.call_args.args[1]


class TestRunningTheAgent:
    @pytest.mark.parametrize(
        "cli_config, timeout", [({"timeout": 60}, 60), ({}, None)], ids=["timeout", "no-timeout"]
    )
    def test_success_runs_command_in_workflow_directory(
        self, cli_config, timeout, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        workflow_config["cli-agent-config"] = cli_config

        result = execute_single_task(
            "my-task", {"prompt": "Do work"}, {}, mock_adapter, workflow_config
        )

        assert result == {"task_name": "my-task", "status": "success", "exit_code": 0}
        subprocess_run.assert_called_once()
        assert subprocess_run.call_args.args == (COMMAND,)
        kwargs = subprocess_run.call_args.kwargs
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["timeout"] == timeout
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True

    def test_nonzero_exit_with_fail_strategy_raises(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        subprocess_run.return_value = completed(returncode=3)
        task = {"prompt": "Do work", "on-error": "fail"}

        with pytest.raises(ExecutionError, match="Task 'my-task' failed with exit code 3"):
            execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

    @pytest.mark.parametrize(
        "strategy, expected",
        [
            (
                "continue",
                {
                    "status": "failed",
                    "exit_code": 3,
                    "error_message": "Task 'my-task' failed with exit code 3",
                },
            ),
            ("skip", {"status": "skipped", "exit_code": 3}),
        ],
    )
    def test_nonzero_exit_with_continue_or_skip_returns_result(
        self, strategy, expected, mock_adapter, workflow_config, subprocess_run
    ):
        subprocess_run.return_value = completed(returncode=3)
        task = {"prompt": "Do work", "on-error": strategy}

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result == {"task_name": "my-task", **expected}

    @pytest.mark.parametrize(
        "workflow_on_error, task_on_error, status",
        [
            ("fail", {"on-error": "continue"}, "failed"),
            ("fail", {"on-error": "skip"}, "skipped"),
            ("continue", {}, "failed"),
            ("skip", {}, "skipped"),
        ],
        ids=[
            "task-continue-beats-workflow-fail",
            "task-skip-beats-workflow-fail",
            "workflow-continue-applies",
            "workflow-skip-applies",
        ],
    )
    def test_task_on_error_overrides_workflow_on_error(
        self,
        workflow_on_error,
        task_on_error,
        status,
        mock_adapter,
        workflow_config,
        subprocess_run,
    ):
        workflow_config["on-error"] = workflow_on_error
        subprocess_run.return_value = completed(returncode=1)

        result = execute_single_task(
            "my-task", {"prompt": "Do work", **task_on_error}, {}, mock_adapter, workflow_config
        )

        assert result["status"] == status

    @pytest.mark.parametrize(
        "workflow_on_error, task_on_error",
        [({"on-error": "continue"}, {"on-error": "fail"}), ({}, {})],
        ids=["task-fail-beats-workflow-continue", "default-is-fail"],
    )
    def test_fail_strategy_raises(
        self, workflow_on_error, task_on_error, mock_adapter, workflow_config, subprocess_run
    ):
        del workflow_config["on-error"]
        workflow_config.update(workflow_on_error)
        subprocess_run.return_value = completed(returncode=1)

        with pytest.raises(ExecutionError, match="failed with exit code 1"):
            execute_single_task(
                "my-task", {"prompt": "Do work", **task_on_error}, {}, mock_adapter, workflow_config
            )

    @pytest.mark.parametrize(
        "workflow_on_error, task_on_error",
        [("fail", {"on-error": "explode"}), ("explode", {})],
        ids=["task-level", "workflow-level"],
    )
    def test_invalid_on_error_strategy_raises_before_running_agent(
        self, workflow_on_error, task_on_error, mock_adapter, workflow_config, subprocess_run
    ):
        workflow_config["on-error"] = workflow_on_error

        with pytest.raises(
            ExecutionError, match="Invalid on-error strategy 'explode' for task 'my-task'"
        ):
            execute_single_task(
                "my-task", {"prompt": "Do work", **task_on_error}, {}, mock_adapter, workflow_config
            )

        mock_adapter.build_command.assert_not_called()
        subprocess_run.assert_not_called()

    @pytest.mark.parametrize("task_def", [{}, {"prompt": ""}], ids=["no-prompt", "empty-prompt"])
    def test_task_without_prompt_raises(
        self, task_def, mock_adapter, workflow_config, subprocess_run
    ):
        with pytest.raises(ExecutionError, match="Task 'my-task' has no prompt defined"):
            execute_single_task("my-task", task_def, {}, mock_adapter, workflow_config)

        mock_adapter.build_command.assert_not_called()
        subprocess_run.assert_not_called()

    def test_timeout_with_fail_strategy_raises(self, mock_adapter, workflow_config, subprocess_run):
        workflow_config["cli-agent-config"] = {"timeout": 60}
        subprocess_run.side_effect = subprocess.TimeoutExpired(cmd=COMMAND, timeout=60)

        with pytest.raises(ExecutionError) as excinfo:
            execute_single_task(
                "my-task", {"prompt": "Long task"}, {}, mock_adapter, workflow_config
            )

        message = str(excinfo.value)
        assert message.startswith("Task timeout exceeded")
        assert "Task 'my-task' exceeded 60 seconds (1.0 minutes) timeout" in message
        assert "timeout: 120  # Double the current timeout" in message

    @pytest.mark.parametrize(
        "strategy, status, has_message", [("continue", "failed", True), ("skip", "skipped", False)]
    )
    def test_timeout_with_continue_or_skip_returns_result(
        self, strategy, status, has_message, mock_adapter, workflow_config, subprocess_run
    ):
        workflow_config["cli-agent-config"] = {"timeout": 60}
        subprocess_run.side_effect = subprocess.TimeoutExpired(cmd=COMMAND, timeout=60)
        task = {"prompt": "Long task", "on-error": strategy}

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == status
        assert result["exit_code"] == -1
        assert ("error_message" in result) is has_message

    def test_agent_exception_with_fail_strategy_raises(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        subprocess_run.side_effect = OSError("agent binary not found")

        with pytest.raises(
            ExecutionError, match="Task 'my-task' failed with exception: agent binary not found"
        ):
            execute_single_task("my-task", {"prompt": "Do work"}, {}, mock_adapter, workflow_config)

    @pytest.mark.parametrize(
        "strategy, expected",
        [
            (
                "continue",
                {
                    "status": "failed",
                    "exit_code": -1,
                    "error_message": "Task 'my-task' failed with exception: agent binary not found",
                },
            ),
            ("skip", {"status": "skipped", "exit_code": -1}),
        ],
    )
    def test_agent_exception_with_continue_or_skip_returns_result(
        self, strategy, expected, mock_adapter, workflow_config, subprocess_run
    ):
        subprocess_run.side_effect = OSError("agent binary not found")
        task = {"prompt": "Do work", "on-error": strategy}

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result == {"task_name": "my-task", **expected}


class TestPromptComposition:
    def test_prompt_variables_are_interpolated(self, mock_adapter, workflow_config, subprocess_run):
        task = {"prompt": "Document {{topic}} under {{doc-root}}"}

        execute_single_task(
            "my-task",
            task,
            {"topic": "testing", "doc-root": "/docs"},
            mock_adapter,
            workflow_config,
        )

        assert sent_prompt(mock_adapter) == "Document testing under /docs"

    def test_named_includes_are_appended_in_task_order(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        workflow_config["includes"] = {
            "use-intro": "Read the introduction guide.",
            "exhaustive": "Perform exhaustive search.",
        }
        task = {"prompt": "Do work", "include": ["exhaustive", "use-intro"]}

        execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert sent_prompt(mock_adapter) == (
            "Do work Perform exhaustive search. Read the introduction guide."
        )

    def test_includes_are_interpolated_once_after_concatenation(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        """Include text is interpolated together with the prompt, in a single pass."""
        workflow_config["includes"] = {"with-vars": "Topic is {{topic}}."}
        task = {"prompt": "Process {{raw}}", "include": ["with-vars"]}
        resolved_vars = {"topic": "testing", "raw": "{{topic}}"}

        execute_single_task("my-task", task, resolved_vars, mock_adapter, workflow_config)

        assert sent_prompt(mock_adapter) == "Process {{topic}} Topic is testing."

    def test_file_includes_resolve_against_workflow_file_directory(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        workflow_dir = tmp_path / "workflows"
        (workflow_dir / "parts").mkdir(parents=True)
        (workflow_dir / "parts" / "style.md").write_text("Style: {{tone}}.")
        workflow_config["_workflow_dir"] = str(workflow_dir)
        workflow_config["includes"] = {"intro": "Read the intro."}
        task = {"prompt": "Do work", "include": ["intro", "parts/style.md"]}

        execute_single_task("my-task", task, {"tone": "terse"}, mock_adapter, workflow_config)

        assert sent_prompt(mock_adapter) == "Do work Read the intro. Style: terse."

    def test_missing_include_file_raises(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {"prompt": "Do work", "include": ["missing.md"]}

        with pytest.raises(ExecutionError) as excinfo:
            execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        message = str(excinfo.value)
        assert "Task 'my-task' failed to resolve include 'missing.md'" in message
        assert f"File not found: {tmp_path / 'missing.md'}" in message
        subprocess_run.assert_not_called()

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
    def test_unreadable_include_file_raises(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        secret = tmp_path / "secret.md"
        secret.write_text("hidden")
        secret.chmod(0o000)
        task = {"prompt": "Do work", "include": ["secret.md"]}

        with pytest.raises(ExecutionError) as excinfo:
            execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert f"Permission denied reading file: {secret}" in str(excinfo.value)
        subprocess_run.assert_not_called()

    def test_empty_include_list_leaves_prompt_unchanged(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        task = {"prompt": "Do work", "include": []}

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == "success"
        assert sent_prompt(mock_adapter) == "Do work"


class TestCliAgentConfig:
    def test_workflow_config_is_passed_to_adapter(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        workflow_config["cli-agent-config"] = {"timeout": 3600, "skip-confirmations": True}

        execute_single_task("my-task", {"prompt": "Do work"}, {}, mock_adapter, workflow_config)

        mock_adapter.build_command.assert_called_once_with(
            {"timeout": 3600, "skip-confirmations": True}, "Do work"
        )

    def test_task_config_overrides_and_inherits_workflow_config(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        workflow_config["cli-agent-config"] = {
            "timeout": 3600,
            "skip-confirmations": True,
            "model": "wf-model",
        }
        original = copy.deepcopy(workflow_config)
        task = {
            "prompt": "Do work",
            "cli-agent-config": {"timeout": 300, "skip-confirmations": False},
        }

        execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert sent_config(mock_adapter) == {
            "timeout": 300,
            "skip-confirmations": False,
            "model": "wf-model",
        }
        assert subprocess_run.call_args.kwargs["timeout"] == 300
        assert workflow_config == original

    @pytest.mark.parametrize(
        "workflow_model, task_model, override, expected",
        [
            ({"model": "wf-model"}, {"model": "task-model"}, "cli-model", "cli-model"),
            ({"model": "wf-model"}, {}, "cli-model", "cli-model"),
            ({}, {"model": "task-model"}, "cli-model", "cli-model"),
            ({}, {}, "cli-model", "cli-model"),
            ({"model": "wf-model"}, {"model": "task-model"}, None, "task-model"),
        ],
        ids=[
            "beats-workflow-and-task",
            "beats-workflow",
            "beats-task",
            "sets-unconfigured-model",
            "unset-override-keeps-task-model",
        ],
    )
    def test_model_override_replaces_configured_model(
        self,
        workflow_model,
        task_model,
        override,
        expected,
        mock_adapter,
        workflow_config,
        subprocess_run,
    ):
        workflow_config["cli-agent-config"] = {"timeout": 60, **workflow_model}
        workflow_config["_model_override"] = override
        original = copy.deepcopy(workflow_config)
        task = {"prompt": "Do work", "cli-agent-config": task_model}

        execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert sent_config(mock_adapter) == {"timeout": 60, "model": expected}
        assert workflow_config == original


class TestDirectoryOverride:
    @pytest.mark.parametrize(
        "directory",
        ["{tmp}/subdir", "./subdir", "subdir", "{{gitroot}}/subdir"],
        ids=["absolute", "dot-relative", "relative", "template-variable"],
    )
    def test_task_directory_becomes_agent_cwd(
        self, directory, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        """Relative task directories resolve against the workflow directory, not the process cwd."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        task = {"prompt": "Do work", "directory": directory.replace("{tmp}", str(tmp_path))}

        result = execute_single_task(
            "my-task", task, {"gitroot": str(tmp_path)}, mock_adapter, workflow_config
        )

        assert result["status"] == "success"
        assert subprocess_run.call_args.kwargs["cwd"] == str(subdir)

    @pytest.mark.parametrize(
        "workflow_directory, task_directory, expected",
        [
            ("~/proj", {}, "proj"),
            ("{tmp}", {"directory": "~/proj"}, "proj"),
            ("~/proj", {"directory": "sub"}, "proj/sub"),
        ],
        ids=["workflow-directory", "task-directory", "relative-task-directory-under-tilde"],
    )
    def test_tilde_expands_to_home(
        self,
        workflow_directory,
        task_directory,
        expected,
        mock_adapter,
        workflow_config,
        subprocess_run,
        tmp_path,
        monkeypatch,
    ):
        home = tmp_path / "home"
        (home / "proj" / "sub").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        workflow_config["directory"] = workflow_directory.replace("{tmp}", str(tmp_path))

        execute_single_task(
            "my-task", {"prompt": "Do work", **task_directory}, {}, mock_adapter, workflow_config
        )

        assert subprocess_run.call_args.kwargs["cwd"] == str(home / expected)

    def test_missing_task_directory_with_fail_strategy_raises(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        missing = tmp_path / "missing"

        with pytest.raises(ExecutionError) as excinfo:
            execute_single_task(
                "my-task",
                {"prompt": "Do work", "directory": str(missing)},
                {},
                mock_adapter,
                workflow_config,
            )

        assert "Task 'my-task' directory does not exist" in str(excinfo.value)
        assert f"Directory not found: {missing}" in str(excinfo.value)
        subprocess_run.assert_not_called()

    @pytest.mark.parametrize(
        "strategy, status, has_message", [("continue", "failed", True), ("skip", "skipped", False)]
    )
    def test_missing_task_directory_with_continue_or_skip_returns_result(
        self, strategy, status, has_message, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        task = {"prompt": "Do work", "directory": str(tmp_path / "missing"), "on-error": strategy}

        result = execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        assert result["status"] == status
        assert result["exit_code"] == -1
        assert ("error_message" in result) is has_message
        subprocess_run.assert_not_called()

    def test_task_directory_does_not_change_workflow_config(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        (tmp_path / "subdir").mkdir()
        original = copy.deepcopy(workflow_config)

        execute_single_task(
            "my-task",
            {"prompt": "Do work", "directory": "subdir"},
            {},
            mock_adapter,
            workflow_config,
        )

        assert workflow_config == original

    def test_dry_run_reports_task_directory_without_requiring_it(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path, capsys
    ):
        missing = tmp_path / "not-created-yet"
        task = {"prompt": "Do work", "directory": str(missing)}

        result = execute_single_task(
            "my-task", task, {}, mock_adapter, workflow_config, dry_run=True
        )

        assert result == {"task_name": "my-task", "status": "success", "exit_code": 0}
        assert f"Working directory: {missing}" in capsys.readouterr().err
        subprocess_run.assert_not_called()


class TestDryRun:
    def test_dry_run_prints_plan_without_running_agent(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path, capsys
    ):
        workflow_config["cli-agent-config"] = {"timeout": 60}
        task = {"prompt": "Summarize {{topic}}", "on-error": "continue"}

        result = execute_single_task(
            "my-task", task, {"topic": "testing"}, mock_adapter, workflow_config, dry_run=True
        )

        assert result == {"task_name": "my-task", "status": "success", "exit_code": 0}
        subprocess_run.assert_not_called()
        mock_adapter.build_command.assert_called_once_with({"timeout": 60}, "Summarize testing")
        err = capsys.readouterr().err
        assert "[DRY RUN] Task 'my-task' would execute:" in err
        assert "  Command: agent -- prompt" in err
        assert f"  Working directory: {tmp_path}" in err
        assert "  Error strategy: continue" in err
        assert "  Timeout: 60s" in err


STREAM_OUTPUT = "".join(
    line + "\n"
    for line in [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Reading the repo"}]},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}
                    ]
                },
            }
        ),
        "plain stderr line from the agent",
        "",
        json.dumps({"type": "result", "result": "All done"}),
    ]
)


class FakeAgentProcess:
    """subprocess.Popen stand-in: `stdout` is a text stream; the process exits with `returncode`."""

    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.killed = False

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True


class SlowStdout(io.StringIO):
    """Agent output whose every line takes 20 ms to arrive."""

    def readline(self, *args):
        time.sleep(0.02)
        return super().readline(*args)


def debug_log(workspace):
    """Text of the single debug log the executor wrote under <workspace>/logs."""
    (log_file,) = (workspace / "logs").glob("my-task-*.log")
    return log_file.read_text()


@pytest.fixture
def close_debug_loggers():
    """Close the executor's debug log handlers left open when a task ends in an exception."""
    yield
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("agent-yaml.") and isinstance(logger, logging.Logger):
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


class TestDebugMode:
    """Debug mode streams the agent's output through Popen and logs it under <workspace>/logs."""

    def test_streams_agent_output_through_popen(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path, capsys
    ):
        workflow_config["_debug"] = True
        task = {"prompt": "Do work", "env": {"AYT_TASK_VAR": "on"}}
        process = FakeAgentProcess(io.StringIO(STREAM_OUTPUT))

        with patch("subprocess.Popen", return_value=process) as popen:
            result = execute_single_task(
                "my-task", task, {"workspace": str(tmp_path)}, mock_adapter, workflow_config
            )

        assert result == {"task_name": "my-task", "status": "success", "exit_code": 0}
        assert sent_config(mock_adapter) == {"debug": True}
        subprocess_run.assert_not_called()
        popen.assert_called_once()
        assert popen.call_args.args == (COMMAND,)
        kwargs = popen.call_args.kwargs
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["text"] is True
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["env"]["AYT_TASK_VAR"] == "on"
        log = debug_log(tmp_path)
        for logged in [
            "=== Task: my-task ===",
            "Reading the repo",
            "[Tool: Bash]\n  Command: ls -la",
            "plain stderr line from the agent",
            "=== Final Result ===\nAll done",
            "=== Exit Code: 0 ===",
        ]:
            assert logged in log
        out, err = capsys.readouterr()
        assert "Reading the repo" in out
        assert f"Output logged to: {tmp_path / 'logs'}" in err

    def test_streaming_nonzero_exit_with_fail_strategy_raises(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        workflow_config["_debug"] = True
        process = FakeAgentProcess(io.StringIO("crashing\n"), returncode=2)

        with patch("subprocess.Popen", return_value=process):
            with pytest.raises(ExecutionError, match="Task 'my-task' failed with exit code 2"):
                execute_single_task(
                    "my-task",
                    {"prompt": "Do work"},
                    {"workspace": str(tmp_path)},
                    mock_adapter,
                    workflow_config,
                )

        assert "=== Exit Code: 2 ===" in debug_log(tmp_path)
        subprocess_run.assert_not_called()

    @pytest.mark.parametrize(
        "strategy, status, has_message", [("continue", "failed", True), ("skip", "skipped", False)]
    )
    def test_streaming_nonzero_exit_with_continue_or_skip_returns_result(
        self, strategy, status, has_message, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        workflow_config["_debug"] = True
        process = FakeAgentProcess(io.StringIO("crashing\n"), returncode=2)

        with patch("subprocess.Popen", return_value=process):
            result = execute_single_task(
                "my-task",
                {"prompt": "Do work", "on-error": strategy},
                {"workspace": str(tmp_path)},
                mock_adapter,
                workflow_config,
            )

        assert result["status"] == status
        assert result["exit_code"] == 2
        assert ("error_message" in result) is has_message

    def test_streaming_timeout_kills_agent(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path, close_debug_loggers
    ):
        workflow_config["_debug"] = True
        workflow_config["cli-agent-config"] = {"timeout": 0.01}
        process = FakeAgentProcess(SlowStdout("still working\n" * 3))

        with patch("subprocess.Popen", return_value=process):
            result = execute_single_task(
                "my-task",
                {"prompt": "Do work", "on-error": "continue"},
                {"workspace": str(tmp_path)},
                mock_adapter,
                workflow_config,
            )

        assert process.killed is True
        assert result["status"] == "failed"
        assert result["exit_code"] == -1
        assert result["error_message"].startswith("Task timeout exceeded")

    def test_debug_flag_prints_command_and_streams(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path, capsys
    ):
        workflow_config["cli-agent-config"] = {"timeout": 60}

        with patch("subprocess.Popen", return_value=FakeAgentProcess(io.StringIO(""))) as popen:
            result = execute_single_task(
                "my-task",
                {"prompt": "Do work"},
                {"workspace": str(tmp_path)},
                mock_adapter,
                workflow_config,
                debug=True,
            )

        assert result["status"] == "success"
        popen.assert_called_once()
        subprocess_run.assert_not_called()
        err = capsys.readouterr().err
        assert "[DEBUG] Task 'my-task':" in err
        assert "  Command: agent -- prompt" in err
        assert f"  Working directory: {tmp_path}" in err
        assert "  Timeout: 60s" in err

    def test_text_output_format_runs_without_streaming_and_logs_output(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        workflow_config["_debug"] = True
        workflow_config["cli-agent-config"] = {"output-format": "text"}
        subprocess_run.return_value = completed(stdout="agent said hi", stderr="agent warned")

        with patch("subprocess.Popen") as popen:
            result = execute_single_task(
                "my-task",
                {"prompt": "Do work"},
                {"workspace": str(tmp_path)},
                mock_adapter,
                workflow_config,
            )

        assert result["status"] == "success"
        popen.assert_not_called()
        subprocess_run.assert_called_once()
        log = debug_log(tmp_path)
        assert "=== STDOUT ===\nagent said hi" in log
        assert "=== STDERR ===\nagent warned" in log
