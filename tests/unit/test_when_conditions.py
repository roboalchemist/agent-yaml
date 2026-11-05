"""Unit tests for agent_yaml/when_conditions.py (task-level `when:` expressions)."""

from unittest.mock import patch

import pytest

from agent_yaml.when_conditions import WhenConditionError, check_when_condition

EXECUTES = [
    pytest.param("{{env}} == 'production'", {"env": "production"}, id="equality"),
    pytest.param("True", {}, id="true-literal"),
    pytest.param(
        "{{env}} == 'production' and {{tests-passed}}",
        {"env": "production", "tests-passed": True},
        id="and-both-true",
    ),
    pytest.param(
        "{{env}} == 'prod' or {{force}}", {"env": "staging", "force": True}, id="or-force-overrides"
    ),
    pytest.param(
        "{{env}} == 'prod' or {{force}}", {"env": "prod", "force": False}, id="or-env-matches"
    ),
    pytest.param("{{env}} != 'ci'", {"env": "local"}, id="not-in-ci"),
    pytest.param("not {{force}}", {"force": False}, id="not-false"),
    pytest.param("{{count}} > 0", {"count": 5}, id="int-variable"),
    pytest.param("{{enabled}}", {"enabled": True}, id="bool-variable"),
    pytest.param("{{config.debug}} == True", {"config": {"debug": True}}, id="nested-variable"),
    pytest.param("{{env.CI}} == 'true'", {"env": {"CI": "true"}}, id="env-variable"),
    pytest.param("{{count}}", {"count": 3}, id="nonzero-int-is-truthy"),
    pytest.param("{{items}}", {"items": ["a"]}, id="non-empty-list-is-truthy"),
]

SKIPS = [
    pytest.param("{{env}} == 'production'", {"env": "staging"}, id="equality"),
    pytest.param("False", {}, id="false-literal"),
    pytest.param(
        "{{env}} == 'production' and {{tests-passed}}",
        {"env": "production", "tests-passed": False},
        id="and-one-false",
    ),
    pytest.param(
        "{{env}} == 'prod' or {{force}}", {"env": "staging", "force": False}, id="or-both-false"
    ),
    pytest.param("{{env}} != 'ci'", {"env": "ci"}, id="in-ci"),
    pytest.param("not {{force}}", {"force": True}, id="not-true"),
    pytest.param("{{undefined_var}}", {}, id="undefined-variable"),
    pytest.param("{{undefined}} == 'value'", {}, id="undefined-in-comparison"),
    pytest.param("{{count}}", {"count": 0}, id="zero-is-falsy"),
    pytest.param("{{items}}", {"items": []}, id="empty-list-is-falsy"),
    pytest.param("{{name}}", {"name": ""}, id="empty-string-is-falsy"),
]


class TestCheckWhenCondition:
    @pytest.mark.parametrize("expression, variables", EXECUTES)
    def test_truthy_expression_executes(self, capsys, expression, variables):
        result = check_when_condition(expression, variables)

        assert result.should_execute is True
        assert result.expression == expression
        assert result.reason == f"when condition satisfied: {expression}"
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("expression, variables", SKIPS)
    def test_falsy_expression_skips_and_logs(self, capsys, expression, variables):
        result = check_when_condition(expression, variables)

        assert result.should_execute is False
        assert not result.evaluated_value
        assert result.reason == (
            f"when condition not satisfied: {expression} evaluated to {result.evaluated_value!r}"
        )
        assert capsys.readouterr().err == f"Task skipped: {result.reason}\n"

    @pytest.mark.parametrize("expression", ["", "   "], ids=["empty", "whitespace"])
    def test_empty_expression_skips(self, capsys, expression):
        result = check_when_condition(expression, {"env": "production"})

        assert result.should_execute is False
        assert result.evaluated_value is None
        assert result.reason == "when expression is empty"
        assert capsys.readouterr().err == "Task skipped: when expression is empty\n"

    def test_long_expression_is_truncated_in_reason(self):
        expression = (
            "{{var}} == 'a' and {{var}} == 'b' and {{var}} == 'c' and {{var}} == 'd' "
            "and {{var}} == 'e'"
        )

        result = check_when_condition(expression, {"var": "x"})

        assert result.should_execute is False
        assert result.expression == expression
        assert result.reason == (
            f"when condition not satisfied: {expression[:57]}... evaluated to False"
        )

    @pytest.mark.parametrize("expression", ["{{a}} ==", "(((", "{{a}} +"])
    def test_invalid_syntax_evaluates_false_instead_of_raising(self, expression):
        result = check_when_condition(expression, {"a": 1})

        assert result.should_execute is False
        assert result.evaluated_value is False

    def test_evaluation_failure_raises_when_condition_error(self):
        with patch("agent_yaml.when_conditions.evaluate_expression", side_effect=RuntimeError("boom")):
            with pytest.raises(WhenConditionError) as exc_info:
                check_when_condition("{{env}} == 'prod'", {"env": "prod"})

        assert str(exc_info.value) == "Failed to evaluate when expression: boom"


class TestWhenConditionResult:
    @pytest.mark.parametrize(
        "env, should_execute, reason",
        [
            ("prod", True, "when condition satisfied: {{env}} == 'prod'"),
            (
                "staging",
                False,
                "when condition not satisfied: {{env}} == 'prod' evaluated to False",
            ),
        ],
        ids=["executes", "skips"],
    )
    def test_to_dict(self, env, should_execute, reason):
        result = check_when_condition("{{env}} == 'prod'", {"env": env})

        assert result.to_dict() == {
            "should_execute": should_execute,
            "expression": "{{env}} == 'prod'",
            "evaluated_value": should_execute,
            "reason": reason,
        }
