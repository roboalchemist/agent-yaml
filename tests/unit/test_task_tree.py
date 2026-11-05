"""Unit tests for agent_yaml.cli.execute_task_tree; single tasks and loop classes are mocked."""

import threading
from unittest.mock import DEFAULT, patch

import pytest

from agent_yaml.cli import execute_task_tree
from agent_yaml.executor import ExecutionError

LOOP_CLASSES = ["TodoListLoop", "CSVLoop", "GlobLoop", "JsonLoop"]


def task_outcomes(outcomes=None):
    """execute_single_task stand-in: per-prompt status string or exception (default "success")."""
    outcomes = outcomes or {}

    def run_task(task_name, task_def, *args):
        outcome = outcomes.get(task_def["prompt"], "success")
        if isinstance(outcome, Exception):
            raise outcome
        return {"task_name": task_name, "status": outcome, "exit_code": int(outcome == "failed")}

    return run_task


def prompts_run(single_task):
    return [call.args[1]["prompt"] for call in single_task.call_args_list]


@pytest.fixture
def resolved_vars():
    return {"topic": "test", "directory": "/work"}


@pytest.fixture
def workflow_config():
    return {"directory": "/work", "cli-agent-config": {}, "on-error": "fail"}


@pytest.fixture
def run_tree(mock_adapter, resolved_vars, workflow_config):
    """execute_task_tree bound to the mock adapter, resolved vars and workflow config."""

    def run(tree, **kwargs):
        return execute_task_tree(tree, mock_adapter, resolved_vars, workflow_config, **kwargs)

    return run


@pytest.fixture
def single_task():
    """Patched agent_yaml.cli.execute_single_task; every task succeeds unless side_effect is replaced."""
    with patch("agent_yaml.cli.execute_single_task", side_effect=task_outcomes()) as mock:
        yield mock


class TestSequentialSteps:
    def test_steps_run_one_after_another_in_order(self, run_tree, single_task):
        tree = [
            {"first": {"prompt": "First"}},
            {"second": {"prompt": "Second"}},
            {"third": {"prompt": "Third"}},
        ]

        assert run_tree(tree) == 0
        assert prompts_run(single_task) == ["First", "Second", "Third"]

    @pytest.mark.parametrize("dry_run, debug", [(False, False), (True, False), (False, True)])
    def test_task_receives_definition_context_and_flags(
        self, run_tree, single_task, mock_adapter, resolved_vars, workflow_config, dry_run, debug
    ):
        task_def = {"prompt": "Do it", "on-error": "continue"}

        assert run_tree([{"only": task_def}], dry_run=dry_run, debug=debug) == 0

        single_task.assert_called_once()
        args = single_task.call_args.args
        assert args[1] == task_def
        assert args[2] == resolved_vars
        assert args[3] is mock_adapter
        # The web runner adds internal (_-prefixed) keys for event node tracking.
        assert {k: v for k, v in args[4].items() if not k.startswith("_")} == workflow_config
        assert args[5:] == (dry_run, debug)

    @pytest.mark.parametrize(
        "failure", ["failed", ExecutionError("boom")], ids=["failed-status", "execution-error"]
    )
    def test_fail_strategy_stops_at_the_first_failing_step(self, run_tree, single_task, failure):
        single_task.side_effect = task_outcomes({"First": failure})
        tree = [{"a": {"prompt": "First"}}, {"b": {"prompt": "Second"}}]

        assert run_tree(tree, error_strategy="fail") == 1
        assert prompts_run(single_task) == ["First"]

    @pytest.mark.parametrize("strategy", ["continue", "skip"])
    def test_other_strategies_run_the_remaining_steps(self, run_tree, single_task, strategy):
        single_task.side_effect = task_outcomes({"First": "failed"})
        tree = [{"a": {"prompt": "First"}}, {"b": {"prompt": "Second"}}]

        assert run_tree(tree, error_strategy=strategy) == 0
        assert prompts_run(single_task) == ["First", "Second"]

    def test_skipped_step_does_not_stop_the_sequence(self, run_tree, single_task):
        single_task.side_effect = task_outcomes({"First": "skipped"})
        tree = [{"a": {"prompt": "First"}}, {"b": {"prompt": "Second"}}]

        assert run_tree(tree) == 0
        assert prompts_run(single_task) == ["First", "Second"]

    def test_parallel_group_finishes_before_the_next_step(self, run_tree, single_task):
        tree = [
            {
                "setup": {"task": [{"s1": {"prompt": "S1"}}, {"s2": {"prompt": "S2"}}]},
                "other": {"prompt": "O"},
            },
            {"final": {"prompt": "F"}},
        ]

        assert run_tree(tree) == 0

        prompts = prompts_run(single_task)
        assert sorted(prompts) == ["F", "O", "S1", "S2"]
        assert prompts.index("S1") < prompts.index("S2")
        assert prompts[-1] == "F"


class TestLeafTask:
    @pytest.mark.parametrize("status, exit_code", [("success", 0), ("skipped", 0), ("failed", 1)])
    def test_task_status_maps_to_exit_code(self, run_tree, single_task, status, exit_code):
        single_task.side_effect = task_outcomes({"Do it": status})

        assert run_tree({"prompt": "Do it"}) == exit_code
        single_task.assert_called_once()

    def test_execution_error_is_reported_and_returns_1(self, run_tree, single_task, capsys):
        single_task.side_effect = ExecutionError("Task 'x' failed with exit code 2")

        assert run_tree({"prompt": "Do it"}) == 1
        assert "Error: Task 'x' failed with exit code 2" in capsys.readouterr().err


class TestParallelGroup:
    def test_members_run_concurrently(self, run_tree, single_task):
        barrier = threading.Barrier(3, timeout=5)
        threads = set()

        def run_task(task_name, task_def, *args):
            barrier.wait()  # BrokenBarrierError after 5s unless all three tasks run at once
            threads.add(threading.get_ident())
            return {"status": "success"}

        single_task.side_effect = run_task

        assert run_tree({"a": {"prompt": "A"}, "b": {"prompt": "B"}, "c": {"prompt": "C"}}) == 0
        assert len(threads) == 3

    @pytest.mark.parametrize(
        "failure, report",
        [
            ("failed", "Task 'b' failed with exit code 1"),
            (ExecutionError("boom"), "Task 'b' failed with exit code 1"),
            (RuntimeError("kaboom"), "Task 'b' raised exception: kaboom"),
        ],
        ids=["failed-status", "execution-error", "unexpected-exception"],
    )
    def test_fail_strategy_returns_failure(self, run_tree, single_task, capsys, failure, report):
        single_task.side_effect = task_outcomes({"B": failure})
        tree = {"a": {"prompt": "A"}, "b": {"prompt": "B"}, "c": {"prompt": "C"}}

        assert run_tree(tree, error_strategy="fail", verbose=True) == 1

        err = capsys.readouterr().err
        assert report in err
        assert "Error strategy is 'fail', cancelling remaining tasks" in err

    @pytest.mark.parametrize("strategy", ["continue", "skip"])
    @pytest.mark.parametrize(
        "failure", ["failed", RuntimeError("kaboom")], ids=["failed-status", "unexpected-exception"]
    )
    def test_other_strategies_run_every_member_and_return_0(
        self, run_tree, single_task, strategy, failure
    ):
        single_task.side_effect = task_outcomes({"A": failure, "C": failure})
        tree = {"a": {"prompt": "A"}, "b": {"prompt": "B"}, "c": {"prompt": "C"}}

        assert run_tree(tree, error_strategy=strategy) == 0
        assert sorted(prompts_run(single_task)) == ["A", "B", "C"]

    def test_verbose_reports_progress_and_error_count(self, run_tree, single_task, capsys):
        single_task.side_effect = task_outcomes({"B": "failed"})
        tree = {"a": {"prompt": "A"}, "b": {"prompt": "B"}}

        assert run_tree(tree, error_strategy="continue", verbose=True) == 0

        err = capsys.readouterr().err
        for line in (
            "Executing 2 tasks in parallel",
            "Submitting task: a",
            "Submitting task: b",
            "Task 'a' completed successfully",
            "Task 'b' failed with exit code 1",
            "Completed with 1 error(s), continuing due to error strategy",
        ):
            assert line in err


class TestLoopDispatch:
    @pytest.mark.parametrize(
        "loop_type, loop_class",
        [
            ("todo-list", "TodoListLoop"),
            ("csv", "CSVLoop"),
            ("glob", "GlobLoop"),
            ("json", "JsonLoop"),
            ("jsonl", "JsonLoop"),
        ],
    )
    def test_loop_type_selects_its_loop_class(
        self,
        run_tree,
        single_task,
        mock_adapter,
        resolved_vars,
        workflow_config,
        capsys,
        loop_type,
        loop_class,
    ):
        task = {"prompt": "Process {{loop.item}}", "loop": {"type": loop_type, "source": "items"}}

        with patch.multiple("agent_yaml.cli", **{name: DEFAULT for name in LOOP_CLASSES}) as loops:
            loops[loop_class].return_value.execute.return_value = {"status": "success"}
            assert run_tree(task, dry_run=True, verbose=True) == 0

        assert [name for name, cls in loops.items() if cls.called] == [loop_class]
        call = loops[loop_class].return_value.execute.call_args
        assert call.args[:4] == (task, task["loop"], resolved_vars, mock_adapter)
        # The web runner adds internal (_-prefixed) keys for event node tracking.
        assert {k: v for k, v in call.args[4].items() if not k.startswith("_")} == workflow_config
        assert call.args[5] is True
        single_task.assert_not_called()
        assert f"Executing loop: {loop_type}" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "status, strategy, exit_code",
        [
            ("success", "fail", 0),
            ("partial", "fail", 1),
            ("partial", "continue", 0),
            ("partial", "skip", 0),
            ("failed", "fail", 1),
            ("failed", "continue", 1),
        ],
    )
    def test_loop_status_maps_to_exit_code(self, run_tree, status, strategy, exit_code):
        task = {
            "prompt": "Process {{loop.item.name}}",
            "loop": {"type": "csv", "source": "rows.csv"},
        }

        with patch("agent_yaml.cli.CSVLoop") as loop_cls:
            loop_cls.return_value.execute.return_value = {"status": status}
            assert run_tree(task, error_strategy=strategy) == exit_code

    def test_loop_execution_error_is_reported_and_returns_1(self, run_tree, capsys):
        task = {"prompt": "Process {{loop.item}}", "loop": {"type": "json", "source": "items.json"}}

        with patch("agent_yaml.cli.JsonLoop") as loop_cls:
            loop_cls.return_value.execute.side_effect = ExecutionError(
                "JSON file not found: items.json"
            )
            assert run_tree(task) == 1

        assert (
            "Error: Loop execution failed: JSON file not found: items.json"
            in capsys.readouterr().err
        )

    def test_unknown_loop_type_returns_1_without_running_anything(
        self, run_tree, single_task, capsys
    ):
        with patch.multiple("agent_yaml.cli", **{name: DEFAULT for name in LOOP_CLASSES}) as loops:
            assert run_tree({"prompt": "Process", "loop": {"type": "unknown-loop"}}) == 1

        assert not any(cls.called for cls in loops.values())
        single_task.assert_not_called()
        assert "Error: Unknown loop type: unknown-loop" in capsys.readouterr().err


class TestUnexpectedStructures:
    def test_non_dict_steps_are_skipped_with_a_warning(self, run_tree, single_task, capsys):
        assert run_tree(["just text", 42, {"real": {"prompt": "Real"}}]) == 0

        assert prompts_run(single_task) == ["Real"]
        err = capsys.readouterr().err
        assert "Warning: Unexpected task tree structure: just text" in err
        assert "Warning: Unexpected task tree structure: 42" in err

    @pytest.mark.parametrize("tree", ["just text", 42, None], ids=["str", "int", "none"])
    def test_tree_that_is_neither_list_nor_dict_returns_1(
        self, run_tree, single_task, capsys, tree
    ):
        assert run_tree(tree) == 1

        assert f"Error: Unexpected task tree type: {type(tree)}" in capsys.readouterr().err
        single_task.assert_not_called()

    def test_group_member_of_unexpected_type_fails_the_group(self, run_tree, single_task, capsys):
        assert run_tree({"good": {"prompt": "Good"}, "bad": "not a task"}) == 1
        assert "Error: Unexpected task tree type: <class 'str'>" in capsys.readouterr().err

    @pytest.mark.parametrize("tree", [[], {}], ids=["empty-list", "empty-group"])
    def test_empty_tree_succeeds_without_running_anything(self, run_tree, single_task, tree):
        assert run_tree(tree) == 0
        single_task.assert_not_called()
