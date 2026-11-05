"""
Integration tests for the agent-yaml entry point (agent_yaml/cli.py).

Workflows are real YAML files in tmp_path, run through run_workflow() / main() with the
deterministic fake `opencode` agent (fixture `fake_opencode`), which executes the
```bash block of each prompt in the task's working directory.
"""

import os
import re
import subprocess
import sys
from unittest.mock import patch

import pytest

from agent_yaml.adapters import UnsupportedCLIError
from agent_yaml.cli import main, parse_var_overrides, run_workflow
from agent_yaml.executor import ExecutionError
from tests.support.helpers import bash_prompt, write_workflow

ALLOWED_AGENTS = "['opencode', 'claude', 'gemini', 'qwen', 'codex']"
MODEL = "openai/gpt-4o-mini"


def make_workflow(tmp_path, task, agent="opencode", **fields):
    """Write a workflow rooted at tmp_path; kwargs spell hyphens as underscores (on_error)."""
    workflow = {"directory": str(tmp_path)}
    if agent:
        workflow["cli-agent"] = agent
    workflow.update({key.replace("_", "-"): value for key, value in fields.items()})
    workflow["task"] = task
    return str(write_workflow(tmp_path / "workflow.yaml", workflow))


def run_main(monkeypatch, *args):
    """Run main() as `agent-yaml <args>` and return its exit code."""
    monkeypatch.setattr(sys, "argv", ["agent-yaml", *args])
    with pytest.raises(SystemExit) as exit_info:
        main()
    return exit_info.value.code


def planned_prompts(err):
    """Prompts the agent would get, from a dry run's `Command: ... -- <prompt>` lines."""
    return [
        line.split(" -- ", 1)[1]
        for line in err.splitlines()
        if line.lstrip().startswith("Command:")
    ]


def record_env(*names):
    """Bash that appends NAME=value for each variable to seen.env in the agent's cwd."""
    return "\n".join(f'printf "{name}=%s\\n" "${name}" >> seen.env' for name in names)


def recorded_env(directory):
    lines = (directory / "seen.env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


class TestRunWorkflowExecution:
    def test_runs_tasks_in_order_through_the_agent(self, tmp_path, fake_opencode, capsys):
        wf = make_workflow(
            tmp_path,
            [
                {"first": {"prompt": bash_prompt("echo first >> order.txt")}},
                {"second": {"prompt": bash_prompt("echo second >> order.txt")}},
            ],
        )

        assert run_workflow(wf, env_files=[]) == 0

        assert (tmp_path / "order.txt").read_text() == "first\nsecond\n"
        calls = fake_opencode.calls()
        assert [call["cwd"] for call in calls] == [str(tmp_path), str(tmp_path)]
        assert "echo first" in calls[0]["prompt"]
        assert "echo second" in calls[1]["prompt"]
        assert "Workflow completed successfully" in capsys.readouterr().err

    def test_verbose_reports_each_stage(self, tmp_path, fake_opencode, capsys):
        wf = make_workflow(tmp_path, [{"t": {"prompt": "Do work"}}])

        assert run_workflow(wf, verbose=True) == 0

        err = capsys.readouterr().err
        for message in (
            f"Loading workflow: {wf}",
            "Validating workflow schema...",
            "Resolving reserved variables...",
            "Resolving template variables...",
            "Using CLI agent: opencode",
            f"Starting workflow execution: {wf}",
        ):
            assert message in err

    @pytest.mark.parametrize(
        "strategy, exit_code, later_task_ran",
        [("fail", 1, False), ("continue", 0, True), ("skip", 0, True)],
    )
    def test_on_error_decides_whether_later_tasks_run(
        self, tmp_path, fake_opencode, capsys, strategy, exit_code, later_task_ran
    ):
        wf = make_workflow(
            tmp_path,
            [
                {"broken": {"prompt": bash_prompt("exit 3")}},
                {"after": {"prompt": bash_prompt("touch after.txt")}},
            ],
            on_error=strategy,
        )

        assert run_workflow(wf) == exit_code

        assert (tmp_path / "after.txt").exists() is later_task_ran
        assert len(fake_opencode.calls()) == (2 if later_task_ran else 1)
        assert "failed with exit code 3" in capsys.readouterr().err

    def test_parallel_group_runs_agents_concurrently(self, tmp_path, fake_opencode):
        """Each agent waits for the other's marker file, so this only passes if both run at once."""

        def rendezvous(me, other):
            return {
                "prompt": bash_prompt(
                    f"touch {me}.started\n"
                    f"for _ in $(seq 100); do [ -f {other}.started ] && exit 0; sleep 0.05; done\n"
                    "exit 1"
                )
            }

        wf = make_workflow(tmp_path, [{"a": rendezvous("a", "b"), "b": rendezvous("b", "a")}])

        assert run_workflow(wf) == 0
        assert len(fake_opencode.calls()) == 2


class TestTemplateVariables:
    def test_reserved_variables_reach_the_prompt(self, tmp_path, fake_opencode, monkeypatch):
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        workdir = repo / "pkg"
        workdir.mkdir()
        monkeypatch.setenv("USER", "alice")
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": "dir={{directory}} root={{gitroot}} user={{user}} at={{datetime}}"}}],
            directory=str(workdir),
        )

        assert run_workflow(wf) == 0

        prompt = fake_opencode.calls()[0]["prompt"]
        assert prompt.startswith(f"dir={workdir} root={repo} user=alice at=")
        assert re.search(r"at=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$", prompt)

    def test_template_variables_resolve_against_each_other(self, tmp_path, fake_opencode, capsys):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": "Work on {{doc}}"}}],
            template_variables={"topic": "testing", "doc": "{{directory}}/{{topic}}.md"},
        )

        assert run_workflow(wf, dry_run=True) == 0
        assert planned_prompts(capsys.readouterr().err) == [f"Work on {tmp_path}/testing.md"]

    def test_var_override_replaces_template_variable(self, tmp_path, fake_opencode, capsys):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": "Topic: {{topic}}"}}],
            template_variables={"topic": "default"},
        )

        assert run_workflow(wf, dry_run=True, var_overrides={"topic": "override"}) == 0

        err = capsys.readouterr().err
        assert planned_prompts(err) == ["Topic: override"]
        assert "Warning" not in err

    @pytest.mark.parametrize("name", ["gitroot", "datetime", "user", "directory", "env"])
    def test_reserved_variable_cannot_be_overridden(self, tmp_path, fake_opencode, capsys, name):
        wf = make_workflow(tmp_path, [{"t": {"prompt": f"value={{{{{name}}}}}"}}])

        assert run_workflow(wf, dry_run=True, var_overrides={name: "hijacked"}) == 0

        err = capsys.readouterr().err
        assert f"Warning: Cannot override reserved variable '{name}', ignoring" in err
        [prompt] = planned_prompts(err)
        assert prompt.startswith("value=")
        assert "hijacked" not in prompt

    def test_override_of_undeclared_variable_is_added_with_warning(
        self, tmp_path, fake_opencode, capsys
    ):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": "Topic: {{topic}}, Extra: {{extra}}"}}],
            template_variables={"topic": "default"},
        )

        overrides = {"extra": "new_value", "undefined_var": "x"}
        assert run_workflow(wf, dry_run=True, var_overrides=overrides) == 0

        err = capsys.readouterr().err
        assert (
            "Warning: Variable 'extra' not defined in workflow template-variables, "
            "adding as new variable" in err
        )
        assert "Warning: Variable 'undefined_var' not defined" in err
        assert planned_prompts(err) == ["Topic: default, Extra: new_value"]

    @pytest.mark.parametrize(
        "variables, message",
        [
            ({"doc": "{{missing}}.md"}, "Variable 'missing' is referenced but not defined"),
            ({"a": "{{b}}", "b": "{{a}}"}, "Circular variable dependency detected"),
            ({"user": "mallory"}, "Cannot override reserved variable"),
        ],
        ids=["undefined-reference", "circular", "reserved-name"],
    )
    def test_unresolvable_template_variables_exit_1(
        self, tmp_path, fake_opencode, capsys, variables, message
    ):
        wf = make_workflow(tmp_path, [{"t": {"prompt": "hi"}}], template_variables=variables)

        assert run_workflow(wf) == 1

        assert message in capsys.readouterr().err
        assert fake_opencode.calls() == []


class TestEnsureBlock:
    def test_satisfied_ensure_block_lets_the_workflow_run(self, tmp_path, fake_opencode, capsys):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": bash_prompt("touch ran.txt")}}],
            ensure={"tools": ["opencode"], "mcps": ["linear"]},
        )

        assert run_workflow(wf) == 0

        assert (tmp_path / "ran.txt").exists()
        assert (
            "MCP availability check for 'linear' is not fully implemented"
            in capsys.readouterr().err
        )

    def test_missing_tool_fails_before_the_agent_runs(self, tmp_path, fake_opencode, capsys):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": bash_prompt("touch ran.txt")}}],
            ensure={"tools": ["agent-yaml-no-such-tool"]},
        )

        assert run_workflow(wf) == 1

        err = capsys.readouterr().err
        assert "Ensure validation failed: Missing required tools: [agent-yaml-no-such-tool]" in err
        assert fake_opencode.calls() == []


class TestRunWorkflowErrors:
    @pytest.mark.parametrize(
        "content, message",
        [
            (None, "Error: Workflow file not found"),
            ("invalid: yaml: syntax:", "Error: Invalid YAML syntax"),
            ("", "Empty workflow file"),
            ("- just\n- a list\n", "Error:"),
        ],
        ids=["missing-file", "invalid-yaml", "empty-file", "not-a-mapping"],
    )
    def test_unloadable_workflow_exits_1(self, tmp_path, fake_opencode, capsys, content, message):
        path = tmp_path / "workflow.yaml"
        if content is not None:
            path.write_text(content)

        assert run_workflow(str(path)) == 1

        assert message in capsys.readouterr().err
        assert fake_opencode.calls() == []

    @pytest.mark.parametrize(
        "fields, message",
        [
            ({}, "Field 'task' is required but missing"),
            ({"task": []}, "Workflow has no tasks"),
            (
                {"task": [{"t": {"on-error": "continue"}}]},
                "Task with neither prompt nor nested tasks",
            ),
            (
                {"on-error": "explode", "task": [{"t": {"prompt": "x"}}]},
                "Field 'on-error' must be one of ['fail', 'continue', 'skip'], got 'explode'",
            ),
            (
                {"cli-agent": "unknown", "task": [{"t": {"prompt": "x"}}]},
                f"Field 'cli-agent' must be one of {ALLOWED_AGENTS}, got 'unknown'",
            ),
        ],
        ids=[
            "missing-task",
            "empty-task-list",
            "task-without-prompt",
            "bad-on-error",
            "unknown-agent",
        ],
    )
    def test_schema_error_exits_1_before_the_agent_runs(
        self, tmp_path, fake_opencode, capsys, fields, message
    ):
        path = write_workflow(tmp_path / "workflow.yaml", {"directory": str(tmp_path), **fields})

        assert run_workflow(str(path)) == 1

        err = capsys.readouterr().err
        assert "Error: Schema validation failed:" in err
        assert message in err
        assert fake_opencode.calls() == []

    @pytest.mark.parametrize("agent, executable", [(None, "claude"), ("codex", "codex")])
    def test_missing_agent_executable_exits_1(
        self, tmp_path, monkeypatch, capsys, agent, executable
    ):
        """With no cli-agent the default is claude; PATH holds no agent at all."""
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        monkeypatch.setenv("PATH", str(empty_bin))
        wf = make_workflow(tmp_path, [{"t": {"prompt": "hi"}}], agent=agent)

        assert run_workflow(wf) == 1
        assert f"Error: CLI executable not found for '{executable}'" in capsys.readouterr().err

    def test_adapter_factory_rejection_exits_1(self, tmp_path, capsys):
        """The schema rejects unknown agents before get_adapter, so this branch needs a mock."""
        wf = make_workflow(tmp_path, [{"t": {"prompt": "hi"}}])

        with patch(
            "agent_yaml.cli.get_adapter", side_effect=UnsupportedCLIError("Unsupported CLI agent: 'x'")
        ):
            assert run_workflow(wf) == 1

        assert "Error: Unsupported CLI agent: 'x'" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "error, message",
        [
            (ExecutionError("Task failed"), "Error: Workflow execution failed: Task failed"),
            (RuntimeError("kaboom"), "Error: Unexpected error during execution: kaboom"),
        ],
        ids=["execution-error", "unexpected-error"],
    )
    def test_error_escaping_the_task_tree_exits_1(
        self, tmp_path, fake_opencode, capsys, error, message
    ):
        """Top-level steps are groups that trap task errors, so the tree itself is mocked here."""
        wf = make_workflow(tmp_path, [{"t": {"prompt": "hi"}}])

        with patch("agent_yaml.cli.execute_task_tree", side_effect=error):
            assert run_workflow(wf) == 1

        assert message in capsys.readouterr().err


class TestDryRun:
    def test_dry_run_never_invokes_the_agent(self, tmp_path, fake_opencode, capsys):
        wf = make_workflow(tmp_path, [{"t": {"prompt": bash_prompt("touch ran.txt")}}])

        assert run_workflow(wf, dry_run=True) == 0

        assert fake_opencode.calls() == []
        assert not (tmp_path / "ran.txt").exists()
        err = capsys.readouterr().err
        assert "would execute:" in err
        assert "Dry run complete. Workflow is valid." in err
        assert "Starting workflow execution" not in err

    def test_dry_run_prints_plan_to_stderr(self, tmp_path, fake_opencode, capsys):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": "Work on {{topic}} in {{stage}}"}}],
            cli_agent_config={"timeout": 3600, "skip-confirmations": True},
            template_variables={"topic": "testing", "stage": "prod"},
        )

        assert run_workflow(wf, dry_run=True) == 0

        captured = capsys.readouterr()
        assert captured.out == ""
        for line in (
            "=== DRY RUN MODE ===",
            f"Directory: {tmp_path}",
            "CLI Agent: opencode",
            "Error Strategy: fail",
            "CLI Agent Configuration:",
            "timeout: 3600",
            "skip-confirmations: True",
            "Resolved Template Variables:",
            "topic: testing (user)",
            "stage: prod (user)",
            "user: ",
            "Execution Plan:",
            "Command: opencode run",
            "--auto",
            "-- Work on testing in prod",
            "Timeout: 3600s",
        ):
            assert line in captured.err

    def test_dry_run_plan_shows_structure_ensure_and_includes(
        self, tmp_path, fake_opencode, capsys
    ):
        wf = make_workflow(
            tmp_path,
            [
                {
                    "lint": {"prompt": "Lint", "include": ["style"], "on-error": "continue"},
                    "test": {"prompt": "Test"},
                },
                {
                    "each": {
                        "prompt": "Review {{loop.item.path}}",
                        "loop": {"type": "glob", "pattern": f"{tmp_path}/*.md"},
                    }
                },
            ],
            ensure={"tools": ["opencode"], "mcps": ["linear"]},
            includes={"style": "Follow the style guide"},
        )

        assert run_workflow(wf, dry_run=True) == 0

        err = capsys.readouterr().err
        for line in (
            "Required Tools: opencode",
            "Required MCPs: linear",
            "style: Follow the style guide",
            "[Sequential Step 1]",
            "[Parallel Group - 2 tasks]",
            "Task: lint",
            "Includes: style",
            "Error strategy: continue",
            "[Sequential Step 2]",
            "[Loop: glob]",
            f"Pattern: {tmp_path}/*.md",
        ):
            assert line in err
        assert fake_opencode.calls() == []

    def test_dry_run_todo_loop_leaves_source_untouched(self, tmp_path, fake_opencode, capsys):
        todo = tmp_path / "todos.md"
        todo.write_text("- [ ] Task 1\n- [ ] Task 2\n- [ ] Task 3\n")
        wf = make_workflow(
            tmp_path,
            [
                {
                    "process": {
                        "prompt": "Process {{loop.item.text}}",
                        "loop": {"type": "todo-list", "source": str(todo), "mark-complete": True},
                    }
                }
            ],
        )

        assert run_workflow(wf, dry_run=True, verbose=True) == 0

        assert todo.read_text() == "- [ ] Task 1\n- [ ] Task 2\n- [ ] Task 3\n"
        assert fake_opencode.calls() == []
        err = capsys.readouterr().err
        assert "[Loop: todo-list]" in err
        assert f"Source: {todo}" in err
        assert "Pending items: 3" in err


class TestEnvFiles:
    def test_workflow_environment_overrides_env_file(self, tmp_path, fake_opencode):
        env_file = tmp_path / ".env"
        env_file.write_text("VAR=from_file\nONLY_FILE=file_only\n")
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": bash_prompt(record_env("VAR", "ONLY_FILE", "ONLY_YAML"))}}],
            environment={"VAR": "from_yaml", "ONLY_YAML": "yaml_only"},
        )

        assert run_workflow(wf, env_files=[str(env_file)]) == 0

        assert recorded_env(tmp_path) == {
            "VAR": "from_yaml",
            "ONLY_FILE": "file_only",
            "ONLY_YAML": "yaml_only",
        }

    def test_full_precedence_chain(self, tmp_path, fake_opencode, monkeypatch):
        """system env < .env file < workflow environment < task env."""
        monkeypatch.setenv("FROM_SYSTEM", "system")
        monkeypatch.setenv("OVERRIDE_BY_FILE", "system")
        env_file = tmp_path / ".env"
        env_file.write_text(
            "OVERRIDE_BY_FILE=file\n"
            "FROM_FILE=file_value\n"
            "OVERRIDE_BY_WORKFLOW=file\n"
            "OVERRIDE_BY_TASK=file\n"
        )
        expected = {
            "FROM_SYSTEM": "system",
            "OVERRIDE_BY_FILE": "file",
            "FROM_FILE": "file_value",
            "FROM_WORKFLOW": "workflow_value",
            "OVERRIDE_BY_WORKFLOW": "workflow",
            "FROM_TASK": "task_value",
            "OVERRIDE_BY_TASK": "task",
        }
        wf = make_workflow(
            tmp_path,
            [
                {
                    "t": {
                        "prompt": bash_prompt(record_env(*expected)),
                        "env": {"FROM_TASK": "task_value", "OVERRIDE_BY_TASK": "task"},
                    }
                }
            ],
            environment={
                "FROM_WORKFLOW": "workflow_value",
                "OVERRIDE_BY_WORKFLOW": "workflow",
                "OVERRIDE_BY_TASK": "workflow",
            },
        )

        assert run_workflow(wf, env_files=[str(env_file)]) == 0
        assert recorded_env(tmp_path) == expected

    def test_env_file_values_fill_env_template_variables(self, tmp_path, fake_opencode, capsys):
        env_file = tmp_path / ".env"
        env_file.write_text("API_URL=https://example.test\n")
        wf = make_workflow(tmp_path, [{"t": {"prompt": "Call {{env.API_URL}}"}}])

        assert run_workflow(wf, env_files=[str(env_file)], dry_run=True) == 0
        assert planned_prompts(capsys.readouterr().err) == ["Call https://example.test"]

    def test_env_file_flags_apply_in_order(self, tmp_path, fake_opencode, monkeypatch):
        base = tmp_path / ".env"
        base.write_text("SHARED=base\nBASE_ONLY=base\n")
        local = tmp_path / ".env.local"
        local.write_text("SHARED=local\n")
        wf = make_workflow(
            tmp_path, [{"t": {"prompt": bash_prompt(record_env("SHARED", "BASE_ONLY"))}}]
        )

        flags = ["--env-file", str(base), "--env-file", str(local)]
        assert run_main(monkeypatch, "run", wf, *flags) == 0
        assert recorded_env(tmp_path) == {"SHARED": "local", "BASE_ONLY": "base"}

    def test_verbose_reports_env_file_loading(self, tmp_path, fake_opencode, capsys):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR=test_value\n")
        wf = make_workflow(tmp_path, [{"t": {"prompt": "Test"}}])

        assert run_workflow(wf, env_files=[str(env_file)], verbose=True) == 0

        err = capsys.readouterr().err
        assert "Loading environment from 1 .env file(s)..." in err
        assert "Loaded 1 variable(s) from .env files" in err

    def test_missing_env_file_exits_1_before_the_agent_runs(self, tmp_path, fake_opencode, capsys):
        missing = tmp_path / "nonexistent.env"
        wf = make_workflow(tmp_path, [{"t": {"prompt": "Test"}}])

        assert run_workflow(wf, env_files=[str(missing)]) == 1

        assert f"Error: Environment file not found: {missing}" in capsys.readouterr().err
        assert fake_opencode.calls() == []

    def test_dry_run_lists_env_file_variables(self, tmp_path, fake_opencode, capsys):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR=my_value\n")
        wf = make_workflow(tmp_path, [{"t": {"prompt": "Test"}}])

        assert run_workflow(wf, env_files=[str(env_file)], dry_run=True) == 0

        err = capsys.readouterr().err
        assert "=== DRY RUN MODE ===" in err
        assert "MY_VAR=my_value (workflow)" in err
        assert fake_opencode.calls() == []


class TestRunFlags:
    def test_cli_agent_flag_replaces_the_workflow_agent(self, tmp_path, fake_opencode, monkeypatch):
        wf = make_workflow(
            tmp_path, [{"t": {"prompt": bash_prompt("touch ran.txt")}}], agent="gemini"
        )

        assert run_main(monkeypatch, "run", wf, "--cli-agent", "opencode") == 0

        assert (tmp_path / "ran.txt").exists()
        [call] = fake_opencode.calls()
        assert call["argv"][0] == "run"

    @pytest.mark.parametrize("command", ["run", "validate"])
    def test_unknown_cli_agent_flag_is_a_schema_error(
        self, tmp_path, fake_opencode, monkeypatch, capsys, command
    ):
        wf = make_workflow(tmp_path, [{"t": {"prompt": "hi"}}])

        assert run_main(monkeypatch, command, wf, "--cli-agent", "nope") == 1

        err = capsys.readouterr().err
        assert (
            "Schema validation failed: Field 'cli-agent' must be one of "
            f"{ALLOWED_AGENTS}, got 'nope'" in err
        )
        assert fake_opencode.calls() == []

    @pytest.mark.parametrize(
        "flags, expected_model",
        [
            ([], "anthropic/task-model"),
            (["--model", MODEL], MODEL),
        ],
        ids=["task-config-wins-without-flag", "flag-beats-task-config"],
    )
    def test_model_flag_beats_workflow_and_task_config(
        self, tmp_path, fake_opencode, monkeypatch, flags, expected_model
    ):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": "hi", "cli-agent-config": {"model": "anthropic/task-model"}}}],
            cli_agent_config={"model": "anthropic/workflow-model"},
        )

        assert run_main(monkeypatch, "run", wf, *flags) == 0

        argv = fake_opencode.calls()[0]["argv"]
        assert argv.count("--model") == 1
        assert argv[argv.index("--model") + 1] == expected_model

    def test_model_flag_is_shown_in_the_dry_run_plan(
        self, tmp_path, fake_opencode, monkeypatch, capsys
    ):
        wf = make_workflow(tmp_path, [{"t": {"prompt": "hi"}}])

        assert run_main(monkeypatch, "run", wf, "--dry-run", "--model", MODEL) == 0

        err = capsys.readouterr().err
        assert f"Model (CLI override): {MODEL}" in err
        assert f"--model {MODEL}" in err
        assert fake_opencode.calls() == []

    def test_directory_flag_sets_agent_cwd_and_directory_variable(
        self, tmp_path, fake_opencode, monkeypatch
    ):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        wf = make_workflow(
            tmp_path, [{"t": {"prompt": bash_prompt('printf "%s" "{{directory}}" > seen.txt')}}]
        )

        assert run_main(monkeypatch, "run", wf, "--directory", str(elsewhere)) == 0

        assert fake_opencode.calls()[0]["cwd"] == str(elsewhere)
        assert (elsewhere / "seen.txt").read_text() == str(elsewhere)
        assert not (tmp_path / "seen.txt").exists()

    def test_var_flags_reach_the_prompt(self, tmp_path, fake_opencode, monkeypatch):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": "{{greeting}}, {{name}}"}}],
            template_variables={"greeting": "Hello", "name": "default"},
        )

        assert run_main(monkeypatch, "run", wf, "--var", "name=world", "--var", "greeting=Hi") == 0
        assert fake_opencode.calls()[0]["prompt"] == "Hi, world"

    def test_debug_flag_streams_agent_output_and_logs_it(
        self, tmp_path, fake_opencode, monkeypatch, capsys
    ):
        wf = make_workflow(
            tmp_path,
            [{"t": {"prompt": bash_prompt('echo "agent says $((6 * 7))"')}}],
            template_variables={"workspace": str(tmp_path)},
        )

        assert run_main(monkeypatch, "run", wf, "--debug") == 0

        assert "--print-logs" in fake_opencode.calls()[0]["argv"]
        assert "agent says 42" in capsys.readouterr().out
        [log] = (tmp_path / "logs").glob("*.log")
        assert "agent says 42" in log.read_text()

    @pytest.mark.parametrize("script, exit_code", [("true", 0), ("exit 4", 1)])
    def test_exit_code_reflects_the_workflow_result(
        self, tmp_path, fake_opencode, monkeypatch, script, exit_code
    ):
        wf = make_workflow(tmp_path, [{"t": {"prompt": bash_prompt(script)}}])

        assert run_main(monkeypatch, "run", wf) == exit_code
        assert len(fake_opencode.calls()) == 1


class TestValidateCommand:
    def test_valid_workflow_exits_0_without_running_the_agent(
        self, tmp_path, fake_opencode, monkeypatch, capsys
    ):
        wf = make_workflow(
            tmp_path, [{"t": {"prompt": bash_prompt("touch ran.txt")}}], agent="gemini"
        )

        assert run_main(monkeypatch, "validate", "--cli-agent", "opencode", wf) == 0

        assert fake_opencode.calls() == []
        assert not (tmp_path / "ran.txt").exists()
        err = capsys.readouterr().err
        assert "Using CLI agent: opencode" in err
        assert "Dry run complete. Workflow is valid." in err

    @pytest.mark.parametrize(
        "content, message",
        [
            ("task: [unclosed", "Invalid YAML syntax"),
            ("directory: {dir}\n", "Field 'task' is required but missing"),
            (
                "directory: {dir}\non-error: explode\ntask:\n  - t:\n      prompt: hi\n",
                "Field 'on-error' must be one of",
            ),
        ],
        ids=["invalid-yaml", "missing-task", "bad-on-error"],
    )
    def test_invalid_workflow_exits_1(
        self, tmp_path, fake_opencode, monkeypatch, capsys, content, message
    ):
        path = tmp_path / "workflow.yaml"
        path.write_text(content.format(dir=tmp_path))

        assert run_main(monkeypatch, "validate", "--cli-agent", "opencode", str(path)) == 1
        assert message in capsys.readouterr().err


class TestMainArguments:
    def test_run_passes_defaults_to_run_workflow(self, tmp_path, monkeypatch):
        workflow = str(tmp_path / "workflow.yaml")

        with patch("agent_yaml.cli.run_workflow", return_value=0) as run:
            assert run_main(monkeypatch, "run", workflow) == 0

        run.assert_called_once()
        assert run.call_args.args == (workflow,)
        defaults = {
            "resume": False,
            "dry_run": False,
            "verbose": False,
            "debug": False,
            "var_overrides": {},
            "directory_override": None,
            "env_files": [],
            "cli_agent_override": None,
            "model_override": None,
        }
        assert {key: run.call_args.kwargs[key] for key in defaults} == defaults

    @pytest.mark.parametrize(
        "flags, kwarg, value",
        [
            (["--resume"], "resume", True),
            (["--dry-run"], "dry_run", True),
            (["--verbose"], "verbose", True),
            (["-v"], "verbose", True),
            (["--debug"], "debug", True),
            (
                ["--var", "topic=test", "--var", "count=5"],
                "var_overrides",
                {"topic": "test", "count": "5"},
            ),
            (
                ["--env-file", ".env", "--env-file", ".env.local"],
                "env_files",
                [".env", ".env.local"],
            ),
            (["--directory", "/srv/work"], "directory_override", "/srv/work"),
            (["-d", "/srv/work"], "directory_override", "/srv/work"),
            (["--cli-agent", "codex"], "cli_agent_override", "codex"),
            (["--model", MODEL], "model_override", MODEL),
        ],
        ids=[
            "resume",
            "dry-run",
            "verbose",
            "verbose-short",
            "debug",
            "var",
            "env-file",
            "directory",
            "directory-short",
            "cli-agent",
            "model",
        ],
    )
    def test_run_flag_maps_to_run_workflow_argument(
        self, tmp_path, monkeypatch, flags, kwarg, value
    ):
        with patch("agent_yaml.cli.run_workflow", return_value=0) as run:
            assert run_main(monkeypatch, "run", str(tmp_path / "workflow.yaml"), *flags) == 0

        assert run.call_args.kwargs[kwarg] == value

    def test_no_command_prints_help_and_exits_1(self, monkeypatch, capsys):
        assert run_main(monkeypatch) == 1
        assert "usage: agent-yaml" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "var, message",
        [
            ("invalid", "Error: Invalid variable format: 'invalid'. Expected 'key=value'"),
            ("=value", "Error: Invalid variable format: '=value'. Key cannot be empty"),
        ],
        ids=["no-equals", "empty-key"],
    )
    def test_malformed_var_exits_1_before_running(
        self, tmp_path, fake_opencode, monkeypatch, capsys, var, message
    ):
        wf = make_workflow(tmp_path, [{"t": {"prompt": "hi"}}])

        assert run_main(monkeypatch, "run", wf, "--var", var) == 1

        assert message in capsys.readouterr().err
        assert fake_opencode.calls() == []

    @pytest.mark.parametrize(
        "args, message",
        [
            (["run"], "the following arguments are required: workflow"),
            (["frobnicate"], "invalid choice: 'frobnicate'"),
            (["validate", "workflow.yaml", "--model", "x"], "unrecognized arguments: --model x"),
        ],
        ids=["run-without-workflow", "unknown-command", "validate-has-no-model-flag"],
    )
    def test_usage_errors_exit_2(self, monkeypatch, capsys, args, message):
        assert run_main(monkeypatch, *args) == 2
        assert message in capsys.readouterr().err


class TestParseVarOverrides:
    @pytest.mark.parametrize(
        "args, expected",
        [
            ([], {}),
            (["topic=testing"], {"topic": "testing"}),
            (
                ["topic=testing", "env=prod", "count=5"],
                {"topic": "testing", "env": "prod", "count": "5"},
            ),
            (["topic = testing", "env= prod"], {"topic": "testing", "env": "prod"}),
            (["url=http://example.com?a=b"], {"url": "http://example.com?a=b"}),
            (["empty="], {"empty": ""}),
            (["topic=first", "topic=second"], {"topic": "second"}),
        ],
        ids=[
            "no-args",
            "single",
            "multiple",
            "spaces-trimmed",
            "equals-in-value",
            "empty-value",
            "last-wins",
        ],
    )
    def test_parses_key_value_pairs(self, args, expected):
        assert parse_var_overrides(args) == expected

    @pytest.mark.parametrize(
        "arg, message",
        [
            ("invalid", "Invalid variable format: 'invalid'. Expected 'key=value'"),
            ("=value", "Invalid variable format: '=value'. Key cannot be empty"),
            ("  =value", "Key cannot be empty"),
        ],
        ids=["no-equals", "empty-key", "blank-key"],
    )
    def test_rejects_malformed_pairs(self, arg, message):
        with pytest.raises(ValueError, match=re.escape(message)):
            parse_var_overrides([arg])


class TestModuleEntryPoint:
    def test_python_m_src_cli_runs_a_workflow(self, tmp_path, fake_opencode):
        wf = make_workflow(
            tmp_path, [{"t": {"prompt": bash_prompt("echo hello > hello.txt")}}], agent="gemini"
        )

        result = subprocess.run(
            [sys.executable, "-m", "agent_yaml.cli", "run", wf, "--cli-agent", "opencode"],
            cwd=tmp_path,
            env=os.environ,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert (tmp_path / "hello.txt").read_text() == "hello\n"
        assert "Workflow completed successfully" in result.stderr
        assert len(fake_opencode.calls()) == 1
