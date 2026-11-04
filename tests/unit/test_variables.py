"""Unit tests for src/variables.py: reserved variables, the `env` namespace, user variables."""

import os
import re
from datetime import datetime

import pytest

from src.utils import evaluate_expression
from src.variables import (
    CircularDependencyError,
    ReservedVariables,
    UndefinedVariableError,
    resolve_user_variables,
)


@pytest.fixture
def reserved():
    """Already-resolved reserved variables, as resolve_user_variables receives them."""
    return {
        "gitroot": "/repo",
        "datetime": "2025-01-01T00:00:00",
        "user": "testuser",
        "directory": "/dir",
    }


def get_reserved(directory, **env_layers):
    return ReservedVariables().get_reserved_vars(str(directory), **env_layers)


class TestReservedVariables:
    def test_reserved_names(self):
        expected = ["gitroot", "datetime", "user", "directory", "env"]
        assert ReservedVariables.RESERVED_NAMES == expected

    def test_every_reserved_name_is_resolved(self, tmp_path):
        resolved = get_reserved(tmp_path)

        assert sorted(resolved) == sorted(ReservedVariables.RESERVED_NAMES)
        for name in ("gitroot", "datetime", "user", "directory"):
            assert isinstance(resolved[name], str), name
        assert isinstance(resolved["env"], dict)
        assert all(isinstance(value, str) for value in resolved["env"].values())

    def test_datetime_is_current_local_time_in_iso8601_with_milliseconds(self, tmp_path):
        before = datetime.now().astimezone()
        stamp = get_reserved(tmp_path)["datetime"]
        after = datetime.now().astimezone()

        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}", stamp)
        parsed = datetime.fromisoformat(stamp)
        # The stamp is truncated to milliseconds, so compare against a truncated lower bound.
        assert before.replace(microsecond=before.microsecond // 1000 * 1000) <= parsed <= after
        assert parsed.utcoffset() == after.utcoffset()

    @pytest.mark.parametrize(
        "env, expected",
        [
            pytest.param(
                {"USER": "alice", "USERNAME": "bob", "LOGNAME": "carol"}, "alice", id="USER-wins"
            ),
            pytest.param({"USERNAME": "bob", "LOGNAME": "carol"}, "bob", id="then-USERNAME"),
            pytest.param({"LOGNAME": "carol"}, "carol", id="then-LOGNAME"),
            pytest.param({}, "unknown", id="none-set"),
            pytest.param({"USER": "", "USERNAME": "bob"}, "bob", id="empty-skipped"),
            pytest.param({"USER": "   ", "USERNAME": "bob"}, "bob", id="blank-skipped"),
            pytest.param({"USER": "  alice  "}, "alice", id="stripped"),
        ],
    )
    def test_user_is_first_non_blank_of_user_username_logname(
        self, tmp_path, monkeypatch, env, expected
    ):
        for name in ("USER", "USERNAME", "LOGNAME"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)

        assert get_reserved(tmp_path)["user"] == expected

    def test_absolute_directory_is_kept(self, tmp_path):
        assert get_reserved(tmp_path)["directory"] == str(tmp_path)

    @pytest.mark.parametrize(
        "given, expected",
        [(".", ""), ("project", "project"), ("a/../b", "b")],
        ids=["dot", "child", "normalized"],
    )
    def test_relative_directory_is_made_absolute_against_cwd(
        self, tmp_path, monkeypatch, given, expected
    ):
        monkeypatch.chdir(tmp_path)
        resolved = ReservedVariables().get_reserved_vars(given)
        assert resolved["directory"] == str(tmp_path / expected)

    def test_tilde_directory_expands_to_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        resolved = ReservedVariables().get_reserved_vars("~/project")
        assert resolved["directory"] == str(tmp_path / "project")

    @pytest.mark.parametrize("start", ["", "src", "src/deep/er"], ids=["root", "subdir", "deep"])
    @pytest.mark.parametrize("marker", ["git-dir", "worktree-git-file"])
    def test_gitroot_is_nearest_ancestor_with_dot_git(self, tmp_path, marker, start):
        repo = tmp_path / "repo"
        (repo / start).mkdir(parents=True, exist_ok=True)
        if marker == "git-dir":
            (repo / ".git").mkdir()
        else:
            (repo / ".git").write_text("gitdir: /elsewhere/.git/worktrees/repo\n")

        assert get_reserved(repo / start)["gitroot"] == str(repo)

    def test_gitroot_is_innermost_of_nested_repositories(self, tmp_path):
        outer = tmp_path / "outer"
        inner = outer / "vendor" / "inner"
        (outer / ".git").mkdir(parents=True)
        (inner / ".git").mkdir(parents=True)
        (inner / "pkg").mkdir()

        assert get_reserved(inner / "pkg")["gitroot"] == str(inner)
        assert get_reserved(outer / "vendor")["gitroot"] == str(outer)

    def test_gitroot_falls_back_to_directory_outside_git(self, tmp_path):
        if any((parent / ".git").exists() for parent in tmp_path.parents):
            pytest.skip("pytest's tmp_path is inside a git checkout")
        work = tmp_path / "a" / "b"
        work.mkdir(parents=True)

        assert get_reserved(work)["gitroot"] == str(work)


class TestEnvNamespace:
    """The reserved `env` dict: system env merged with workflow `environment` and task `env`."""

    @pytest.mark.parametrize(
        "system, workflow, task, expected",
        [
            ("system", None, None, "system"),
            (None, "workflow", None, "workflow"),
            (None, None, "task", "task"),
            ("system", "workflow", None, "workflow"),
            ("system", None, "task", "task"),
            (None, "workflow", "task", "task"),
            ("system", "workflow", "task", "task"),
        ],
    )
    def test_precedence_is_system_then_workflow_then_task(
        self, tmp_path, monkeypatch, system, workflow, task, expected
    ):
        monkeypatch.delenv("AY_LAYERED", raising=False)
        if system is not None:
            monkeypatch.setenv("AY_LAYERED", system)
        workflow_env = None if workflow is None else {"AY_LAYERED": workflow}
        task_env = None if task is None else {"AY_LAYERED": task}

        env = get_reserved(tmp_path, workflow_env=workflow_env, task_env=task_env)["env"]

        assert env["AY_LAYERED"] == expected

    @pytest.mark.parametrize("layer", ["workflow_env", "task_env"])
    @pytest.mark.parametrize(
        "value, expected", [(42, "42"), (3.14, "3.14"), (True, "True"), (None, "")]
    )
    def test_values_are_stringified(self, tmp_path, layer, value, expected):
        env = get_reserved(tmp_path, **{layer: {"AY_VALUE": value}})["env"]
        assert env["AY_VALUE"] == expected

    @pytest.mark.parametrize(
        "workflow_env, task_env",
        [({}, None), (None, {}), (None, None)],
        ids=["wf-empty", "task-empty", "both-none"],
    )
    def test_without_overrides_env_is_the_system_env(self, tmp_path, workflow_env, task_env):
        env = get_reserved(tmp_path, workflow_env=workflow_env, task_env=task_env)["env"]
        assert env == dict(os.environ)

    def test_layers_do_not_modify_os_environ(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AY_SHARED", "system")
        monkeypatch.delenv("AY_WORKFLOW_ONLY", raising=False)

        env = get_reserved(
            tmp_path, workflow_env={"AY_SHARED": "workflow", "AY_WORKFLOW_ONLY": "workflow"}
        )["env"]

        assert env["AY_SHARED"] == "workflow"
        assert env["AY_WORKFLOW_ONLY"] == "workflow"
        assert os.environ["AY_SHARED"] == "system"
        assert "AY_WORKFLOW_ONLY" not in os.environ


class TestResolveUserVariables:
    @pytest.mark.parametrize("user_vars", [{}, None])
    def test_without_user_variables_returns_a_copy_of_reserved(self, reserved, user_vars):
        result = resolve_user_variables(user_vars, reserved)
        assert result == reserved
        assert result is not reserved

    @pytest.mark.parametrize(
        "user_vars, expected",
        [
            pytest.param(
                {"topic": "authentication", "service": "api"},
                {"topic": "authentication", "service": "api"},
                id="literals",
            ),
            pytest.param(
                {"empty": "", "plain": "plain text"},
                {"empty": "", "plain": "plain text"},
                id="empty-and-plain-text",
            ),
            pytest.param(
                {"base": "value", "derived": "{{base}}-extended"},
                {"base": "value", "derived": "value-extended"},
                id="reference",
            ),
            pytest.param(
                {"base": "value", "derived": "{{base}} and {{base}} again"},
                {"base": "value", "derived": "value and value again"},
                id="repeated-reference",
            ),
            pytest.param(
                {"base-var": "value", "derived-var": "{{base-var}}-extended"},
                {"base-var": "value", "derived-var": "value-extended"},
                id="hyphenated-names",
            ),
            pytest.param(
                {"base_var": "value", "derived_var": "{{base_var}}_extended"},
                {"base_var": "value", "derived_var": "value_extended"},
                id="underscored-names",
            ),
            pytest.param(
                {"a": "{{b}}-suffix", "b": "{{c}}-middle", "c": "base"},
                {"a": "base-middle-suffix", "b": "base-middle", "c": "base"},
                id="chain-defined-in-reverse",
            ),
            pytest.param(
                {"d": "{{c}}-d", "b": "{{a}}-b", "c": "{{b}}-c", "a": "base"},
                {"a": "base", "b": "base-b", "c": "base-b-c", "d": "base-b-c-d"},
                id="chain-defined-out-of-order",
            ),
            pytest.param(
                {
                    "path": "{{gitroot}}/src",
                    "stamp": "Created at {{datetime}}",
                    "who": "{{user}} in {{directory}}",
                },
                {
                    "path": "/repo/src",
                    "stamp": "Created at 2025-01-01T00:00:00",
                    "who": "testuser in /dir",
                },
                id="reserved-references",
            ),
        ],
    )
    def test_references_resolve_in_dependency_order(self, reserved, user_vars, expected):
        assert resolve_user_variables(user_vars, reserved) == {**reserved, **expected}

    @pytest.mark.parametrize(
        "name", ["topic", "topic_doc", "topic-doc", "topic2", "Topic", "_private", "a1-b2_c3"]
    )
    def test_forward_reference_resolves_for_every_valid_name_style(self, reserved, name):
        """`ref` is defined first, so it only resolves if `name` is tracked as a dependency."""
        user_vars = {"ref": "<{{" + name + "}}>", name: "value"}
        assert resolve_user_variables(user_vars, reserved)["ref"] == "<value>"

    def test_inputs_are_not_mutated(self, reserved):
        user_vars = {"derived": "{{base}}!", "base": "value"}
        reserved_before, user_vars_before = dict(reserved), dict(user_vars)

        assert resolve_user_variables(user_vars, reserved)["derived"] == "value!"
        assert reserved == reserved_before
        assert user_vars == user_vars_before

    @pytest.mark.parametrize(
        "user_vars, missing",
        [
            pytest.param({"a": "{{undefined_var}}"}, "undefined_var", id="undefined"),
            pytest.param(
                {"topic": "docs", "a": "{{topic}} and {{missing}}"}, "missing", id="one-of-several"
            ),
            pytest.param({"topic": "docs", "a": "{{Topic}}"}, "Topic", id="case-sensitive"),
        ],
    )
    def test_undefined_reference_raises(self, reserved, user_vars, missing):
        expected = f"Variable '{missing}' is referenced but not defined"
        with pytest.raises(UndefinedVariableError, match=re.escape(expected)):
            resolve_user_variables(user_vars, reserved)

    def test_undefined_reference_error_lists_available_variables_sorted(self, reserved):
        user_vars = {"zebra": "z", "apple": "{{missing}}", "banana": "b"}

        with pytest.raises(UndefinedVariableError) as excinfo:
            resolve_user_variables(user_vars, reserved)

        assert (
            "Available variables: "
            "['apple', 'banana', 'datetime', 'directory', 'gitroot', 'user', 'zebra']"
        ) in str(excinfo.value)

    @pytest.mark.parametrize(
        "user_vars, chain",
        [
            pytest.param({"a": "{{a}}"}, "a -> a", id="self"),
            pytest.param({"a": "{{b}}", "b": "{{a}}"}, "a -> b -> a", id="two-way"),
            pytest.param(
                {"a": "{{b}}", "b": "{{c}}", "c": "{{a}}"}, "a -> b -> c -> a", id="three-way"
            ),
            pytest.param(
                {"good": "value", "a": "{{b}}", "b": "{{a}}", "uses_good": "{{good}}"},
                "a -> b -> a",
                id="cycle-among-valid-variables",
            ),
            pytest.param(
                {"entry": "{{a}}", "a": "{{b}}", "b": "{{a}}"},
                "a -> b -> a",
                id="entry-outside-cycle",
            ),
        ],
    )
    def test_circular_reference_raises_with_the_cycle_chain(self, reserved, user_vars, chain):
        with pytest.raises(CircularDependencyError) as excinfo:
            resolve_user_variables(user_vars, reserved)

        message = str(excinfo.value)
        assert message.startswith("Circular variable dependency detected")
        assert f"Found: Circular chain: {chain}\n" in message

    @pytest.mark.parametrize("name", ["gitroot", "datetime", "user", "directory", "env"])
    def test_reserved_names_cannot_be_redefined(self, reserved, name):
        with pytest.raises(CircularDependencyError) as excinfo:
            resolve_user_variables({name: "override"}, reserved)

        message = str(excinfo.value)
        assert message.startswith("Cannot override reserved variable")
        assert f"User variable '{name}' conflicts with reserved variable" in message

    @pytest.mark.parametrize(
        "system_env, workflow_env",
        [({"AY_DATA_DIR": "data"}, None), ({}, {"AY_DATA_DIR": "data"})],
        ids=["system-env", "workflow-env"],
    )
    def test_user_variables_can_reference_env(
        self, tmp_path, monkeypatch, system_env, workflow_env
    ):
        monkeypatch.delenv("AY_DATA_DIR", raising=False)
        for name, value in system_env.items():
            monkeypatch.setenv(name, value)
        reserved_vars = get_reserved(tmp_path, workflow_env=workflow_env)

        resolved = resolve_user_variables(
            {"output-dir": "{{directory}}/{{env.AY_DATA_DIR}}/output"}, reserved_vars
        )

        assert resolved["output-dir"] == f"{tmp_path}/data/output"


class TestNativeValues:
    """Non-string template-variables (YAML bools, numbers, lists, null) are not stringified."""

    @pytest.mark.parametrize(
        "value",
        [False, True, 0, 3, 1.5, None, ["a", "b"], {"key": "value"}],
        ids=["false", "true", "zero", "int", "float", "none", "list", "dict"],
    )
    def test_non_string_values_are_kept_as_is(self, reserved, value):
        assert resolve_user_variables({"v": value}, reserved)["v"] is value

    @pytest.mark.parametrize(
        "value, rendered",
        [
            (3, "run-3"),
            (False, "run-False"),
            (1.5, "run-1.5"),
            (None, "run-None"),
            (["a", "b"], "run-['a', 'b']"),
        ],
    )
    def test_string_values_render_native_references_with_str(self, reserved, value, rendered):
        resolved = resolve_user_variables({"label": "run-{{n}}", "n": value}, reserved)

        assert resolved["label"] == rendered
        assert resolved["n"] is value

    def test_false_flag_keeps_negated_when_condition_true(self, reserved):
        resolved = resolve_user_variables({"force": False}, reserved)

        assert evaluate_expression("not {{force}}", resolved) is True
        assert evaluate_expression("{{force}}", resolved) is False
        # Stringifying would have produced "False", a truthy string:
        assert evaluate_expression("not {{force}}", {"force": "False"}) is False
