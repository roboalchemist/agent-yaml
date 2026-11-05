"""
Unit tests for environment variables: agent_yaml.executor.build_merged_environment
(system < workflow `environment` < task `env`) and how execute_single_task uses it for the
agent process and for {{env.NAME}} interpolation.
"""

import copy
import os
from unittest.mock import patch

import pytest

from agent_yaml.executor import build_merged_environment, execute_single_task
from tests.support.helpers import completed


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


def pick(env, expected):
    """The entries of `env` for the keys of `expected`."""
    return {key: env.get(key) for key in expected}


class TestBuildMergedEnvironment:
    def test_task_env_beats_workflow_env_beats_system_env(self, monkeypatch):
        monkeypatch.setenv("AYT_SYSTEM_ONLY", "system")
        monkeypatch.setenv("AYT_SET_BY_WORKFLOW", "system")
        monkeypatch.setenv("AYT_SET_BY_TASK", "system")
        workflow_config = {
            "environment": {
                "AYT_SET_BY_WORKFLOW": "workflow",
                "AYT_SET_BY_TASK": "workflow",
                "AYT_WORKFLOW_ONLY": "workflow",
            }
        }
        task_def = {
            "prompt": "Do work",
            "env": {"AYT_SET_BY_TASK": "task", "AYT_TASK_ONLY": "task"},
        }

        merged = build_merged_environment(workflow_config, task_def, {})

        expected = {
            "AYT_SYSTEM_ONLY": "system",
            "AYT_SET_BY_WORKFLOW": "workflow",
            "AYT_SET_BY_TASK": "task",
            "AYT_WORKFLOW_ONLY": "workflow",
            "AYT_TASK_ONLY": "task",
        }
        assert pick(merged, expected) == expected

    @pytest.mark.parametrize(
        "workflow_env_config, task_env_config",
        [
            ({}, {}),
            ({"environment": {}}, {}),
            ({}, {"env": {}}),
            ({"environment": {}}, {"env": {}}),
        ],
        ids=["no-env-config", "empty-workflow-env", "empty-task-env", "both-empty"],
    )
    def test_without_custom_env_returns_system_env(self, workflow_env_config, task_env_config):
        merged = build_merged_environment(
            workflow_env_config, {"prompt": "Do work", **task_env_config}, {}
        )

        assert merged == dict(os.environ)

    def test_template_variables_are_interpolated_in_values(self):
        workflow_config = {"environment": {"WORKSPACE": "{{gitroot}}"}}
        task_def = {
            "prompt": "Do work",
            "env": {"BUILD_ID": "{{datetime}}", "OUT": "{{gitroot}}/build"},
        }
        resolved_vars = {"gitroot": "/repo", "datetime": "2024-01-01T00:00:00"}

        merged = build_merged_environment(workflow_config, task_def, resolved_vars)

        expected = {"WORKSPACE": "/repo", "BUILD_ID": "2024-01-01T00:00:00", "OUT": "/repo/build"}
        assert pick(merged, expected) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [(42, "42"), (3.14, "3.14"), (True, "True"), (None, "")],
        ids=["int", "float", "bool", "none"],
    )
    def test_values_are_converted_to_strings(self, value, expected):
        merged = build_merged_environment(
            {"environment": {"AYT_WORKFLOW_VALUE": value}},
            {"prompt": "Do work", "env": {"AYT_TASK_VALUE": value}},
            {},
        )

        assert merged["AYT_WORKFLOW_VALUE"] == expected
        assert merged["AYT_TASK_VALUE"] == expected

    def test_keys_are_kept_verbatim(self):
        env = {
            "my.dotted.var": "dotted",
            "MY_UNDERSCORED_VAR": "underscored",
            "MixedCase.Var_Name": "mixed",
        }

        merged = build_merged_environment({"environment": env}, {"prompt": "Do work"}, {})

        assert pick(merged, env) == env

    def test_os_environ_is_not_modified(self, monkeypatch):
        monkeypatch.delenv("AYT_WORKFLOW_VAR", raising=False)
        monkeypatch.delenv("AYT_TASK_VAR", raising=False)
        before = dict(os.environ)

        merged = build_merged_environment(
            {"environment": {"AYT_WORKFLOW_VAR": "workflow", "PATH": "/nowhere"}},
            {"prompt": "Do work", "env": {"AYT_TASK_VAR": "task"}},
            {},
        )
        merged["AYT_ADDED_LATER"] = "x"

        assert dict(os.environ) == before
        expected = {"AYT_WORKFLOW_VAR": "workflow", "AYT_TASK_VAR": "task", "PATH": "/nowhere"}
        assert pick(merged, expected) == expected


class TestAgentProcessEnvironment:
    def test_agent_receives_merged_env(
        self, mock_adapter, workflow_config, subprocess_run, monkeypatch
    ):
        monkeypatch.setenv("AYT_SYSTEM_VAR", "system")
        workflow_config["environment"] = {"AYT_WORKFLOW_VAR": "workflow", "AYT_SHARED": "workflow"}
        task = {"prompt": "Do work", "env": {"AYT_TASK_VAR": "task", "AYT_SHARED": "task"}}

        execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        expected = {
            "AYT_SYSTEM_VAR": "system",
            "AYT_WORKFLOW_VAR": "workflow",
            "AYT_TASK_VAR": "task",
            "AYT_SHARED": "task",
        }
        assert pick(subprocess_run.call_args.kwargs["env"], expected) == expected

    def test_pwd_tracks_the_launch_directory(
        self, mock_adapter, workflow_config, subprocess_run, tmp_path
    ):
        """opencode/claude shell tools resolve relative paths against $PWD, not the real cwd."""
        task_dir = tmp_path / "sub"
        task_dir.mkdir()
        task = {"prompt": "Do work", "directory": str(task_dir), "env": {"PWD": "/wrong"}}

        execute_single_task("my-task", task, {}, mock_adapter, workflow_config)

        call = subprocess_run.call_args.kwargs
        assert call["cwd"] == str(task_dir)
        assert call["env"]["PWD"] == str(task_dir)

    def test_env_values_are_interpolated_for_agent(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        task = {
            "prompt": "Do work",
            "env": {"BUILD_ID": "{{datetime}}", "WORKSPACE": "{{gitroot}}/build"},
        }
        resolved_vars = {"gitroot": "/repo", "datetime": "2024-01-01T00:00:00"}

        execute_single_task("my-task", task, resolved_vars, mock_adapter, workflow_config)

        expected = {"BUILD_ID": "2024-01-01T00:00:00", "WORKSPACE": "/repo/build"}
        assert pick(subprocess_run.call_args.kwargs["env"], expected) == expected

    def test_dry_run_lists_custom_env_with_its_source(
        self, mock_adapter, workflow_config, subprocess_run, capsys
    ):
        workflow_config["environment"] = {"AYT_SHARED": "workflow", "AYT_WORKFLOW_VAR": "wf"}
        task = {"prompt": "Do work", "env": {"AYT_SHARED": "task", "AYT_TASK_VAR": "t"}}

        result = execute_single_task(
            "my-task", task, {}, mock_adapter, workflow_config, dry_run=True
        )

        assert result["status"] == "success"
        subprocess_run.assert_not_called()
        env_section = capsys.readouterr().err.split("  Environment variables:\n", 1)[1]
        assert env_section.splitlines() == [
            "    AYT_SHARED=task (task)",
            "    AYT_TASK_VAR=t (task)",
            "    AYT_WORKFLOW_VAR=wf (workflow)",
        ]

    def test_dry_run_without_custom_env_omits_env_section(
        self, mock_adapter, workflow_config, subprocess_run, capsys
    ):
        execute_single_task(
            "my-task", {"prompt": "Do work"}, {}, mock_adapter, workflow_config, dry_run=True
        )

        err = capsys.readouterr().err
        assert "[DRY RUN] Task 'my-task' would execute:" in err
        assert "Environment variables:" not in err


class TestEnvTemplateNamespace:
    """Task `env` is merged into resolved_vars["env"], so templates see it as {{env.NAME}}."""

    def test_prompt_sees_task_env_over_workflow_env(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        resolved_vars = {"env": {"AYT_WORKFLOW_VAR": "wf", "AYT_SHARED": "workflow"}}
        task = {
            "prompt": (
                "{{env.AYT_TASK_VAR}}|{{env.AYT_SHARED}}|{{env.AYT_WORKFLOW_VAR}}"
                "|{{env.AYT_COUNT}}|{{env.AYT_UNSET}}"
            ),
            "env": {
                "AYT_TASK_VAR": "task",
                "AYT_SHARED": "task",
                "AYT_COUNT": 42,
                "AYT_UNSET": None,
            },
        }

        execute_single_task("my-task", task, resolved_vars, mock_adapter, workflow_config)

        assert mock_adapter.build_command.call_args.args[1] == "task|task|wf|42|"

    def test_callers_resolved_vars_are_not_modified(
        self, mock_adapter, workflow_config, subprocess_run
    ):
        resolved_vars = {"env": {"AYT_SHARED": "workflow"}}
        before = copy.deepcopy(resolved_vars)
        task = {"prompt": "{{env.AYT_SHARED}}", "env": {"AYT_SHARED": "task"}}

        execute_single_task("my-task", task, resolved_vars, mock_adapter, workflow_config)

        assert mock_adapter.build_command.call_args.args[1] == "task"
        assert resolved_vars == before

    def test_validators_see_task_env(self, mock_adapter, workflow_config, subprocess_run, tmp_path):
        (tmp_path / "out.txt").write_text("done")
        task = {
            "prompt": "Write out.txt",
            "env": {"AYT_OUT_DIR": str(tmp_path)},
            "validate": [{"file-exists": "{{env.AYT_OUT_DIR}}/out.txt"}],
        }

        result = execute_single_task("my-task", task, {"env": {}}, mock_adapter, workflow_config)

        assert result["status"] == "success"
        assert result["validation"]["results"][0]["details"]["file"] == str(tmp_path / "out.txt")
