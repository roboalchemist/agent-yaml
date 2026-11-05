"""
Pre-task skip conditions for agent-yaml.

Checks conditions BEFORE task execution to enable idempotent workflows.
Supports file-based conditions:
- file-exists: Skip if file path exists
- file-contains: Skip if file contains text substring

Skip condition timing:
- Runs BEFORE task execution
- If condition matches, task is skipped without executing
- Log skip reason to stderr with clear message
- Supports template variable interpolation in paths

Skip-if format:
    skip-if:
      file-exists: "path/to/file"

    skip-if:
      file-contains:
        path: "status.txt"
        text: "SUCCESS"

Reference: spec/planning.txt for skip condition specification.
"""

import os
import sys
from typing import Any, Dict, Optional


class SkipConditionResult:
    """Result of a skip condition check."""

    def __init__(
        self,
        condition_type: str,
        should_skip: bool,
        reason: Optional[str] = None,
        details: Optional[Dict] = None,
    ):
        self.condition_type = condition_type
        self.should_skip = should_skip
        self.reason = reason
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "condition_type": self.condition_type,
            "should_skip": self.should_skip,
            "reason": self.reason,
            "details": self.details,
        }


class SkipConditionError(Exception):
    """Raised when skip condition configuration is invalid or check fails."""

    pass


class BaseSkipCondition:
    """Base class for all skip conditions."""

    def __init__(
        self, config: Any, resolved_vars: Dict[str, Any], working_dir: Optional[str] = None
    ):
        """
        Initialize skip condition.

        Args:
            config: Condition configuration (string or dict)
            resolved_vars: Resolved variables for interpolation
            working_dir: Working directory for resolving relative paths (defaults to cwd)
        """
        self.config = config
        self.resolved_vars = resolved_vars
        self.working_dir = working_dir or os.getcwd()

    def check(self) -> SkipConditionResult:
        """
        Check if task should be skipped.

        Returns:
            SkipConditionResult with should_skip status and reason
        """
        raise NotImplementedError("Subclasses must implement check()")


class FileExistsSkipCondition(BaseSkipCondition):
    """Skip task if a file exists."""

    def check(self) -> SkipConditionResult:
        """Check if file exists at specified path."""
        from .utils import interpolate_variables

        # Config is a string path
        file_path = interpolate_variables(str(self.config), self.resolved_vars)
        file_path = os.path.expanduser(file_path)

        # Resolve relative paths against working directory
        if not os.path.isabs(file_path):
            file_path = os.path.join(self.working_dir, file_path)

        file_path = os.path.abspath(file_path)

        if os.path.exists(file_path):
            return SkipConditionResult(
                condition_type="file-exists",
                should_skip=True,
                reason=f"file-exists condition met: {file_path}",
                details={"file": file_path},
            )
        else:
            return SkipConditionResult(
                condition_type="file-exists",
                should_skip=False,
                reason=f"file does not exist: {file_path}",
                details={"file": file_path},
            )


class FileContainsSkipCondition(BaseSkipCondition):
    """Skip task if a file contains specific text."""

    def check(self) -> SkipConditionResult:
        """Check if file contains specified text substring."""
        from .utils import interpolate_variables

        # Config is a dict with 'path' and 'text' keys
        if not isinstance(self.config, dict):
            raise SkipConditionError(
                "file-contains skip condition requires dict with 'path' and 'text' keys"
            )

        file_path = self.config.get("path", "")
        expected_text = self.config.get("text", "")

        if not file_path or not expected_text:
            raise SkipConditionError(
                "file-contains skip condition requires both 'path' and 'text' fields"
            )

        # Interpolate variables
        file_path = interpolate_variables(file_path, self.resolved_vars)
        file_path = os.path.expanduser(file_path)

        # Resolve relative paths against working directory
        if not os.path.isabs(file_path):
            file_path = os.path.join(self.working_dir, file_path)

        file_path = os.path.abspath(file_path)
        expected_text = interpolate_variables(expected_text, self.resolved_vars)

        # Check file exists - raise error if not (per spec requirement)
        if not os.path.exists(file_path):
            raise SkipConditionError(
                f"file-contains skip condition: file does not exist: {file_path}"
            )

        # Read file and check for text
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if expected_text in content:
                # Truncate expected_text for reason message if too long
                display_text = (
                    expected_text
                    if len(expected_text) <= 50
                    else expected_text[:47] + "..."
                )
                return SkipConditionResult(
                    condition_type="file-contains",
                    should_skip=True,
                    reason=f"file-contains condition met: '{display_text}' found in {file_path}",
                    details={
                        "file": file_path,
                        "expected_text": expected_text,
                        "file_size": len(content),
                    },
                )
            else:
                display_text = (
                    expected_text
                    if len(expected_text) <= 50
                    else expected_text[:47] + "..."
                )
                return SkipConditionResult(
                    condition_type="file-contains",
                    should_skip=False,
                    reason=f"file does not contain expected text: '{display_text}'",
                    details={
                        "file": file_path,
                        "expected_text": expected_text,
                        "file_size": len(content),
                    },
                )
        except IOError as e:
            raise SkipConditionError(f"Error reading file {file_path}: {e}")


def create_skip_condition(
    condition_type: str,
    config: Any,
    resolved_vars: Dict[str, Any],
    working_dir: Optional[str] = None,
) -> BaseSkipCondition:
    """
    Factory function to create skip condition instances.

    Args:
        condition_type: Type of condition (file-exists, file-contains)
        config: Condition configuration
        resolved_vars: Resolved variables for interpolation
        working_dir: Working directory for resolving relative paths

    Returns:
        BaseSkipCondition instance

    Raises:
        SkipConditionError: If condition type is unknown
    """
    conditions = {
        "file-exists": FileExistsSkipCondition,
        "file-contains": FileContainsSkipCondition,
    }

    condition_class = conditions.get(condition_type)
    if not condition_class:
        raise SkipConditionError(
            f"Unknown skip condition type: {condition_type}. "
            f"Supported types: {', '.join(conditions.keys())}"
        )

    return condition_class(config, resolved_vars, working_dir)


def check_skip_conditions(
    skip_config: Dict[str, Any],
    resolved_vars: Dict[str, Any],
    working_dir: Optional[str] = None,
) -> SkipConditionResult:
    """
    Check skip conditions for a task.

    Args:
        skip_config: Skip condition configuration from task['skip-if']
            Can be a dict with one condition type as key:
            {"file-exists": "path"} or {"file-contains": {"path": "...", "text": "..."}}
        resolved_vars: Resolved variables for interpolation
        working_dir: Working directory for resolving relative paths.
            Defaults to current working directory if not specified.

    Returns:
        SkipConditionResult with should_skip status

    Raises:
        SkipConditionError: If configuration is invalid

    Example skip_config:
        {"file-exists": "output.md"}
        {"file-contains": {"path": "status.txt", "text": "SUCCESS"}}
    """
    if not isinstance(skip_config, dict):
        raise SkipConditionError(
            f"skip-if must be a dict, got {type(skip_config).__name__}"
        )

    # skip-if should have exactly one key (condition type)
    if len(skip_config) != 1:
        raise SkipConditionError(
            f"skip-if must have exactly one condition, got {len(skip_config)}"
        )

    condition_type = list(skip_config.keys())[0]
    config = skip_config[condition_type]

    condition = create_skip_condition(condition_type, config, resolved_vars, working_dir)
    result = condition.check()

    # Log skip decision to stderr
    if result.should_skip:
        print(f"Task skipped: {result.reason}", file=sys.stderr)

    return result
