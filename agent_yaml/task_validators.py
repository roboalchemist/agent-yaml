"""
Post-task validation for agent-yaml.

Validates task output after successful execution (exit code 0).
Supports multiple validator types:
- file-exists: Check if file path exists
- file-not-empty: Check if file has content (size > 0)
- contains: Check if file contains text substring
- json-valid: Check if file contains valid JSON
- yaml-valid: Check if file contains valid YAML
- command: Run custom command/script to validate output

Validation timing:
- Runs AFTER task completes with exit code 0
- Failed validation can trigger retry (if configured)
- Validation errors respect task-level on-error strategy

Validator format:
    validate:
      - file-exists: "path.md"
      - file-not-empty: "path.md"
      - contains:
          file: "path.md"
          text: "expected string"
      - json-valid: "output.json"
      - yaml-valid: "config.yaml"
      - command:
          cmd: "python validate.py {file}"
          file: "output.md"
          timeout: 30          # optional, seconds (default 30)

Relative file paths resolve against the agent-yaml process's cwd, not the workflow
`directory`.

Reference: spec/planning.txt lines 44-80 for validator specification.
"""

import json
import os
import subprocess
import sys
from typing import Dict, List, Any, Optional

import yaml

DEFAULT_COMMAND_TIMEOUT = 30


class ValidationError(Exception):
    """Raised when task validation fails or validator configuration is invalid."""

    pass


class ValidatorResult:
    """Result of a single validator execution."""

    def __init__(
        self,
        validator_type: str,
        passed: bool,
        error_message: Optional[str] = None,
        details: Optional[Dict] = None,
    ):
        self.validator_type = validator_type
        self.passed = passed
        self.error_message = error_message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "validator_type": self.validator_type,
            "passed": self.passed,
            "error_message": self.error_message,
            "details": self.details,
        }


class BaseValidator:
    """Base class for all validators."""

    def __init__(self, config: Any, resolved_vars: Dict[str, Any]):
        """
        Initialize validator.

        Args:
            config: Validator configuration (string or dict)
            resolved_vars: Resolved variables for interpolation
        """
        self.config = config
        self.resolved_vars = resolved_vars

    def validate(self) -> ValidatorResult:
        """
        Run validation.

        Returns:
            ValidatorResult with pass/fail status and error details
        """
        raise NotImplementedError("Subclasses must implement validate()")


class FileExistsValidator(BaseValidator):
    """Validate that a file exists."""

    def validate(self) -> ValidatorResult:
        """Check if file exists at specified path."""
        from .utils import interpolate_variables

        # Config is a string path
        file_path = interpolate_variables(str(self.config), self.resolved_vars)
        file_path = os.path.abspath(os.path.expanduser(file_path))

        if os.path.exists(file_path):
            return ValidatorResult(
                validator_type="file-exists", passed=True, details={"file": file_path}
            )
        else:
            return ValidatorResult(
                validator_type="file-exists",
                passed=False,
                error_message=f"File does not exist: {file_path}",
                details={"file": file_path},
            )


class FileNotEmptyValidator(BaseValidator):
    """Validate that a file exists and has content."""

    def validate(self) -> ValidatorResult:
        """Check if file exists and size > 0."""
        from .utils import interpolate_variables

        file_path = interpolate_variables(str(self.config), self.resolved_vars)
        file_path = os.path.abspath(os.path.expanduser(file_path))

        if not os.path.exists(file_path):
            return ValidatorResult(
                validator_type="file-not-empty",
                passed=False,
                error_message=f"File does not exist: {file_path}",
                details={"file": file_path},
            )

        file_size = os.path.getsize(file_path)
        if file_size > 0:
            return ValidatorResult(
                validator_type="file-not-empty",
                passed=True,
                details={"file": file_path, "size": file_size},
            )
        else:
            return ValidatorResult(
                validator_type="file-not-empty",
                passed=False,
                error_message=f"File is empty: {file_path} (size: 0 bytes)",
                details={"file": file_path, "size": 0},
            )


class ContainsValidator(BaseValidator):
    """Validate that a file contains specific text."""

    def validate(self) -> ValidatorResult:
        """Check if file contains specified text substring."""
        from .utils import interpolate_variables

        # Config is a dict with 'file' and 'text' keys
        if not isinstance(self.config, dict):
            return ValidatorResult(
                validator_type="contains",
                passed=False,
                error_message="Contains validator requires dict with 'file' and 'text' keys",
            )

        file_path = self.config.get("file", "")
        expected_text = self.config.get("text", "")

        if not file_path or not expected_text:
            return ValidatorResult(
                validator_type="contains",
                passed=False,
                error_message="Contains validator requires both 'file' and 'text' fields",
            )

        # Interpolate variables
        file_path = interpolate_variables(file_path, self.resolved_vars)
        file_path = os.path.abspath(os.path.expanduser(file_path))
        expected_text = interpolate_variables(expected_text, self.resolved_vars)

        # Check file exists
        if not os.path.exists(file_path):
            return ValidatorResult(
                validator_type="contains",
                passed=False,
                error_message=f"File does not exist: {file_path}",
                details={"file": file_path, "expected_text": expected_text},
            )

        # Read file and check for text
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if expected_text in content:
                return ValidatorResult(
                    validator_type="contains",
                    passed=True,
                    details={
                        "file": file_path,
                        "expected_text": expected_text,
                        "file_size": len(content),
                    },
                )
            else:
                # Truncate expected_text for error message if too long
                display_text = (
                    expected_text
                    if len(expected_text) <= 50
                    else expected_text[:47] + "..."
                )
                return ValidatorResult(
                    validator_type="contains",
                    passed=False,
                    error_message=f"File does not contain expected text: '{display_text}'",
                    details={
                        "file": file_path,
                        "expected_text": expected_text,
                        "file_size": len(content),
                    },
                )
        except IOError as e:
            return ValidatorResult(
                validator_type="contains",
                passed=False,
                error_message=f"Error reading file {file_path}: {e}",
                details={"file": file_path, "expected_text": expected_text},
            )


class JsonValidValidator(BaseValidator):
    """Validate that a file contains valid JSON."""

    def validate(self) -> ValidatorResult:
        """Check if file contains parseable JSON."""
        from .utils import interpolate_variables

        # Config is a string path
        file_path = interpolate_variables(str(self.config), self.resolved_vars)
        file_path = os.path.abspath(os.path.expanduser(file_path))

        # Check file exists
        if not os.path.exists(file_path):
            return ValidatorResult(
                validator_type="json-valid",
                passed=False,
                error_message=f"File does not exist: {file_path}",
                details={"file": file_path},
            )

        # Try to parse JSON
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Attempt to parse
            parsed = json.loads(content)

            return ValidatorResult(
                validator_type="json-valid",
                passed=True,
                details={
                    "file": file_path,
                    "size": len(content),
                    "type": type(parsed).__name__,
                },
            )

        except json.JSONDecodeError as e:
            return ValidatorResult(
                validator_type="json-valid",
                passed=False,
                error_message=f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}",
                details={"file": file_path, "error": str(e)},
            )
        except IOError as e:
            return ValidatorResult(
                validator_type="json-valid",
                passed=False,
                error_message=f"Error reading file {file_path}: {e}",
                details={"file": file_path},
            )


class YamlValidValidator(BaseValidator):
    """Validate that a file contains valid YAML."""

    def validate(self) -> ValidatorResult:
        """Check if file contains parseable YAML."""
        from .utils import interpolate_variables

        # Config is a string path
        file_path = interpolate_variables(str(self.config), self.resolved_vars)
        file_path = os.path.abspath(os.path.expanduser(file_path))

        # Check file exists
        if not os.path.exists(file_path):
            return ValidatorResult(
                validator_type="yaml-valid",
                passed=False,
                error_message=f"File does not exist: {file_path}",
                details={"file": file_path},
            )

        # Try to parse YAML
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Attempt to parse
            parsed = yaml.safe_load(content)

            return ValidatorResult(
                validator_type="yaml-valid",
                passed=True,
                details={
                    "file": file_path,
                    "size": len(content),
                    "type": type(parsed).__name__ if parsed is not None else "null",
                },
            )

        except yaml.YAMLError as e:
            error_msg = str(e)
            # Extract line number if available
            if hasattr(e, "problem_mark"):
                mark = e.problem_mark
                error_msg = f"Invalid YAML at line {mark.line + 1}, column {mark.column + 1}: {e.problem}"
            return ValidatorResult(
                validator_type="yaml-valid",
                passed=False,
                error_message=error_msg,
                details={"file": file_path, "error": str(e)},
            )
        except IOError as e:
            return ValidatorResult(
                validator_type="yaml-valid",
                passed=False,
                error_message=f"Error reading file {file_path}: {e}",
                details={"file": file_path},
            )


class CommandValidator(BaseValidator):
    """Validate output by running a custom command/script."""

    def validate(self) -> ValidatorResult:
        """Execute command and check exit code (0 = pass, non-zero = fail)."""
        from .utils import interpolate_variables

        # Config is a dict with 'cmd' and optional 'file' keys
        if not isinstance(self.config, dict):
            return ValidatorResult(
                validator_type="command",
                passed=False,
                error_message="Command validator requires dict with 'cmd' and optional 'file' keys",
            )

        cmd_template = self.config.get("cmd", "")
        file_path = self.config.get("file", "")

        if not cmd_template:
            return ValidatorResult(
                validator_type="command",
                passed=False,
                error_message="Command validator requires 'cmd' field",
            )

        # Interpolate variables in command template
        cmd_str = interpolate_variables(cmd_template, self.resolved_vars)

        # If file specified, interpolate it and make {file} available
        if file_path:
            file_path = interpolate_variables(file_path, self.resolved_vars)
            file_path = os.path.abspath(os.path.expanduser(file_path))

            # Check file exists
            if not os.path.exists(file_path):
                return ValidatorResult(
                    validator_type="command",
                    passed=False,
                    error_message=f"File does not exist: {file_path}",
                    details={"file": file_path, "cmd": cmd_template},
                )

            # Replace {file} placeholder in command
            cmd_str = cmd_str.replace("{file}", file_path)

        timeout = self.config.get("timeout", DEFAULT_COMMAND_TIMEOUT)

        # Execute command
        try:
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode == 0:
                return ValidatorResult(
                    validator_type="command",
                    passed=True,
                    details={
                        "cmd": cmd_str,
                        "exit_code": result.returncode,
                        "stdout": result.stdout[:200] if result.stdout else "",
                    },
                )
            else:
                return ValidatorResult(
                    validator_type="command",
                    passed=False,
                    error_message=f"Command failed with exit code {result.returncode}",
                    details={
                        "cmd": cmd_str,
                        "exit_code": result.returncode,
                        "stdout": result.stdout[:200] if result.stdout else "",
                        "stderr": result.stderr[:200] if result.stderr else "",
                    },
                )

        except subprocess.TimeoutExpired:
            return ValidatorResult(
                validator_type="command",
                passed=False,
                error_message=f"Command timed out after {timeout} seconds",
                details={"cmd": cmd_str},
            )
        except Exception as e:
            return ValidatorResult(
                validator_type="command",
                passed=False,
                error_message=f"Error executing command: {str(e)}",
                details={"cmd": cmd_str, "error": str(e)},
            )


def create_validator(
    validator_type: str, config: Any, resolved_vars: Dict[str, Any]
) -> BaseValidator:
    """
    Factory function to create validator instances.

    Args:
        validator_type: Type of validator (file-exists, file-not-empty, contains,
                       json-valid, yaml-valid, command)
        config: Validator configuration
        resolved_vars: Resolved variables for interpolation

    Returns:
        BaseValidator instance

    Raises:
        ValidationError: If validator type is unknown
    """
    validators = {
        "file-exists": FileExistsValidator,
        "file-not-empty": FileNotEmptyValidator,
        "contains": ContainsValidator,
        "json-valid": JsonValidValidator,
        "yaml-valid": YamlValidValidator,
        "command": CommandValidator,
    }

    validator_class = validators.get(validator_type)
    if not validator_class:
        raise ValidationError(
            f"Unknown validator type: {validator_type}. "
            f"Supported types: {', '.join(validators.keys())}"
        )

    return validator_class(config, resolved_vars)


def run_validators(
    validators_config: List[Dict], resolved_vars: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Run all validators for a task.

    Args:
        validators_config: List of validator configurations from task['validate']
        resolved_vars: Resolved variables for interpolation

    Returns:
        dict with keys:
            - all_passed: bool (True if all validators passed)
            - results: List[ValidatorResult] (individual validator results)
            - failed_count: int (number of failed validators)
            - total_count: int (total number of validators)

    Example validators_config:
        [
            {"file-exists": "output.md"},
            {"file-not-empty": "output.md"},
            {"contains": {"file": "output.md", "text": "## Summary"}}
        ]
    """
    results = []
    failed_count = 0

    for validator_def in validators_config:
        # Each validator is a dict with one key (validator type) -> config
        if not isinstance(validator_def, dict):
            results.append(
                ValidatorResult(
                    validator_type="unknown",
                    passed=False,
                    error_message=f"Invalid validator definition: must be dict, got {type(validator_def).__name__}",
                )
            )
            failed_count += 1
            continue

        # Get validator type and config
        if len(validator_def) != 1:
            results.append(
                ValidatorResult(
                    validator_type="unknown",
                    passed=False,
                    error_message=f"Invalid validator definition: must have exactly one key, got {len(validator_def)}",
                )
            )
            failed_count += 1
            continue

        validator_type = list(validator_def.keys())[0]
        config = validator_def[validator_type]

        try:
            validator = create_validator(validator_type, config, resolved_vars)
            result = validator.validate()
            results.append(result)

            if not result.passed:
                failed_count += 1
                print(
                    f"  ❌ Validator failed: {validator_type} - {result.error_message}",
                    file=sys.stderr,
                )
            else:
                print(f"  ✅ Validator passed: {validator_type}", file=sys.stderr)

        except ValidationError as e:
            results.append(
                ValidatorResult(
                    validator_type=validator_type, passed=False, error_message=str(e)
                )
            )
            failed_count += 1
            print(f"  ❌ Validator error: {validator_type} - {e}", file=sys.stderr)

    return {
        "all_passed": failed_count == 0,
        "results": [r.to_dict() for r in results],
        "failed_count": failed_count,
        "total_count": len(results),
    }
