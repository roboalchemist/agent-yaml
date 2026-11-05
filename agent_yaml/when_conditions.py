"""
When conditions for conditional task execution.

Evaluates Jinja2 expressions to determine if a task should execute.
Supports full Jinja2 expression syntax:
- Comparisons: ==, !=, <, >, <=, >=
- Boolean logic: and, or, not
- String operations: in, not in

When condition format:
    when: "{{environment}} == 'production' and {{tests-passed}}"

When condition timing:
- Runs BEFORE task execution (after skip-if)
- If expression evaluates to false/empty/null, task is skipped
- Log skip reason to stderr with clear message
- Supports template variable interpolation

Reference: spec/planning.txt for when condition specification.
"""

import sys
from typing import Any, Dict, Optional

from .utils import evaluate_expression


class WhenConditionResult:
    """Result of a when condition evaluation."""

    def __init__(
        self,
        should_execute: bool,
        expression: str,
        evaluated_value: Any,
        reason: Optional[str] = None,
    ):
        self.should_execute = should_execute
        self.expression = expression
        self.evaluated_value = evaluated_value
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "should_execute": self.should_execute,
            "expression": self.expression,
            "evaluated_value": self.evaluated_value,
            "reason": self.reason,
        }


class WhenConditionError(Exception):
    """Raised when when condition evaluation fails."""

    pass


def check_when_condition(
    when_expression: str,
    resolved_vars: Dict[str, Any],
) -> WhenConditionResult:
    """
    Evaluate a when condition expression.

    Args:
        when_expression: Jinja2 expression string to evaluate
            Example: "{{environment}} == 'production' and {{tests-passed}}"
        resolved_vars: Resolved variables for interpolation

    Returns:
        WhenConditionResult with should_execute status and evaluation details

    Examples:
        >>> check_when_condition("{{env}} == 'prod'", {"env": "prod"})
        WhenConditionResult(should_execute=True, ...)

        >>> check_when_condition("{{env}} == 'prod'", {"env": "staging"})
        WhenConditionResult(should_execute=False, ...)

        >>> check_when_condition("{{a}} and {{b}}", {"a": True, "b": True})
        WhenConditionResult(should_execute=True, ...)

        >>> check_when_condition("", {})
        WhenConditionResult(should_execute=False, ...)
    """
    # Empty expression means skip
    if not when_expression or not when_expression.strip():
        result = WhenConditionResult(
            should_execute=False,
            expression=when_expression,
            evaluated_value=None,
            reason="when expression is empty",
        )
        print(f"Task skipped: {result.reason}", file=sys.stderr)
        return result

    # Evaluate the expression
    try:
        evaluated_value = evaluate_expression(when_expression, resolved_vars)
    except Exception as e:
        raise WhenConditionError(f"Failed to evaluate when expression: {e}")

    # Determine if we should execute based on truthiness
    should_execute = bool(evaluated_value)

    if should_execute:
        reason = f"when condition satisfied: {when_expression}"
    else:
        # Truncate long expressions for display
        display_expr = (
            when_expression if len(when_expression) <= 60 else when_expression[:57] + "..."
        )
        reason = f"when condition not satisfied: {display_expr} evaluated to {evaluated_value!r}"

    result = WhenConditionResult(
        should_execute=should_execute,
        expression=when_expression,
        evaluated_value=evaluated_value,
        reason=reason,
    )

    # Log skip decision to stderr
    if not should_execute:
        print(f"Task skipped: {result.reason}", file=sys.stderr)

    return result
