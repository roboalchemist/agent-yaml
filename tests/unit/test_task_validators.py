"""Unit tests for src/task_validators.py (post-task `validate:` checks)."""

import time
from unittest.mock import patch

import pytest

from src.task_validators import (
    DEFAULT_COMMAND_TIMEOUT,
    CommandValidator,
    ContainsValidator,
    FileExistsValidator,
    FileNotEmptyValidator,
    JsonValidValidator,
    ValidationError,
    ValidatorResult,
    YamlValidValidator,
    create_validator,
    run_validators,
)
from tests.support.helpers import completed

# Config builders: each one passes for a file containing GOOD_CONTENT.
GOOD_CONTENT = '{"ok": true}'
CONFIG_FOR = {
    "file-exists": lambda path: path,
    "file-not-empty": lambda path: path,
    "json-valid": lambda path: path,
    "yaml-valid": lambda path: path,
    "contains": lambda path: {"file": path, "text": '"ok"'},
    "command": lambda path: {"cmd": "test -s {file}", "file": path},
}
READING_VALIDATORS = ["contains", "json-valid", "yaml-valid"]
UNKNOWN_TYPE_MESSAGE = (
    "Unknown validator type: unknown-type. Supported types: "
    "file-exists, file-not-empty, contains, json-valid, yaml-valid, command"
)


class TestPathHandling:
    """Path behavior shared by every validator that takes a file."""

    @pytest.mark.parametrize("validator_type", list(CONFIG_FOR))
    def test_missing_file_fails(self, tmp_path, validator_type):
        missing = tmp_path / "missing.json"
        config = CONFIG_FOR[validator_type](str(missing))

        result = create_validator(validator_type, config, {}).validate()

        assert result.passed is False
        assert result.validator_type == validator_type
        assert result.error_message == f"File does not exist: {missing}"
        assert result.details["file"] == str(missing)

    @pytest.mark.parametrize("validator_type", list(CONFIG_FOR))
    def test_path_variables_are_interpolated(self, tmp_path, validator_type):
        (tmp_path / "result.json").write_text(GOOD_CONTENT)
        config = CONFIG_FOR[validator_type]("{{out_dir}}/result.json")

        result = create_validator(validator_type, config, {"out_dir": str(tmp_path)}).validate()

        assert result.passed is True, result.error_message

    @pytest.mark.parametrize("validator_type", list(CONFIG_FOR))
    def test_tilde_expands_to_home(self, tmp_path, monkeypatch, validator_type):
        (tmp_path / "result.json").write_text(GOOD_CONTENT)
        monkeypatch.setenv("HOME", str(tmp_path))
        config = CONFIG_FOR[validator_type]("~/result.json")

        result = create_validator(validator_type, config, {}).validate()

        assert result.passed is True, result.error_message

    @pytest.mark.parametrize("validator_type", READING_VALIDATORS)
    def test_unreadable_path_fails(self, tmp_path, validator_type):
        """A path that exists but is not a readable file (a directory) fails instead of raising."""
        config = CONFIG_FOR[validator_type](str(tmp_path))

        result = create_validator(validator_type, config, {}).validate()

        assert result.passed is False
        assert result.error_message.startswith(f"Error reading file {tmp_path}: ")


class TestFileExistsValidator:
    def test_passes_when_file_exists(self, tmp_path):
        path = tmp_path / "output.md"
        path.write_text("")

        result = FileExistsValidator(str(path), {}).validate()

        assert result.passed is True
        assert result.validator_type == "file-exists"
        assert result.error_message is None
        assert result.details == {"file": str(path)}


class TestFileNotEmptyValidator:
    def test_passes_when_file_has_content(self, tmp_path):
        path = tmp_path / "output.md"
        path.write_text("test content")

        result = FileNotEmptyValidator(str(path), {}).validate()

        assert result.passed is True
        assert result.validator_type == "file-not-empty"
        assert result.error_message is None
        assert result.details == {"file": str(path), "size": 12}

    def test_fails_when_file_is_empty(self, tmp_path):
        path = tmp_path / "output.md"
        path.write_text("")

        result = FileNotEmptyValidator(str(path), {}).validate()

        assert result.passed is False
        assert result.error_message == f"File is empty: {path} (size: 0 bytes)"
        assert result.details == {"file": str(path), "size": 0}


class TestContainsValidator:
    def test_passes_when_text_found(self, tmp_path):
        content = "# Report\n\nThis is a test report.\n\n## Summary\n\nAll tests passed."
        path = tmp_path / "report.md"
        path.write_text(content)

        result = ContainsValidator({"file": str(path), "text": "## Summary"}, {}).validate()

        assert result.passed is True
        assert result.validator_type == "contains"
        assert result.details == {
            "file": str(path),
            "expected_text": "## Summary",
            "file_size": len(content),
        }

    def test_fails_when_text_missing(self, tmp_path):
        path = tmp_path / "report.md"
        path.write_text("Some content without the expected text")

        result = ContainsValidator({"file": str(path), "text": "## Summary"}, {}).validate()

        assert result.passed is False
        assert result.error_message == "File does not contain expected text: '## Summary'"

    def test_long_expected_text_is_truncated_in_error(self, tmp_path):
        path = tmp_path / "report.md"
        path.write_text("Short content")
        long_text = "x" * 100

        result = ContainsValidator({"file": str(path), "text": long_text}, {}).validate()

        truncated = "x" * 47 + "..."
        assert result.passed is False
        assert result.error_message == f"File does not contain expected text: '{truncated}'"
        assert result.details["expected_text"] == long_text

    def test_file_and_text_are_interpolated(self, tmp_path):
        path = tmp_path / "report.md"
        path.write_text("Expected content for testing")
        config = {"file": "{{output_file}}", "text": "{{expected_text}}"}
        resolved_vars = {"output_file": str(path), "expected_text": "Expected content"}

        result = ContainsValidator(config, resolved_vars).validate()

        assert result.passed is True
        assert result.details["file"] == str(path)
        assert result.details["expected_text"] == "Expected content"

    @pytest.mark.parametrize(
        "config, message",
        [
            ("report.md", "Contains validator requires dict with 'file' and 'text' keys"),
            ({"text": "## Summary"}, "Contains validator requires both 'file' and 'text' fields"),
            ({"file": "report.md"}, "Contains validator requires both 'file' and 'text' fields"),
            (
                {"file": "report.md", "text": ""},
                "Contains validator requires both 'file' and 'text' fields",
            ),
        ],
        ids=["not-a-dict", "missing-file", "missing-text", "empty-text"],
    )
    def test_invalid_config_fails(self, config, message):
        result = ContainsValidator(config, {}).validate()

        assert result.passed is False
        assert result.error_message == message


class TestJsonValidValidator:
    @pytest.mark.parametrize(
        "content, parsed_type",
        [
            ('{"key": "value", "number": 42, "array": [1, 2, 3]}', "dict"),
            ("[]", "list"),
            ("42", "int"),
            ("null", "NoneType"),
        ],
        ids=["object", "array", "number", "null"],
    )
    def test_valid_json_passes(self, tmp_path, content, parsed_type):
        path = tmp_path / "output.json"
        path.write_text(content)

        result = JsonValidValidator(str(path), {}).validate()

        assert result.passed is True
        assert result.validator_type == "json-valid"
        assert result.error_message is None
        assert result.details == {"file": str(path), "size": len(content), "type": parsed_type}

    @pytest.mark.parametrize(
        "content, message_prefix",
        [
            ('{"key": "value", invalid}', "Invalid JSON at line 1, column 18: "),
            ("", "Invalid JSON at line 1, column 1: Expecting value"),
        ],
        ids=["unquoted-key", "empty-file"],
    )
    def test_invalid_json_fails(self, tmp_path, content, message_prefix):
        path = tmp_path / "output.json"
        path.write_text(content)

        result = JsonValidValidator(str(path), {}).validate()

        assert result.passed is False
        assert result.validator_type == "json-valid"
        assert result.error_message.startswith(message_prefix)


class TestYamlValidValidator:
    @pytest.mark.parametrize(
        "content, parsed_type",
        [
            ("key: value\nnumber: 42\nlist:\n  - item1\n  - item2\n", "dict"),
            ("- item1\n- item2\n", "list"),
            ("", "null"),
        ],
        ids=["mapping", "sequence", "empty-file-is-null"],
    )
    def test_valid_yaml_passes(self, tmp_path, content, parsed_type):
        path = tmp_path / "config.yaml"
        path.write_text(content)

        result = YamlValidValidator(str(path), {}).validate()

        assert result.passed is True
        assert result.validator_type == "yaml-valid"
        assert result.error_message is None
        assert result.details == {"file": str(path), "size": len(content), "type": parsed_type}

    @pytest.mark.parametrize(
        "content, message_prefix",
        [
            (
                "key: value\n  invalid: indentation\n",
                "Invalid YAML at line 2, column 10: mapping values are not allowed here",
            ),
            (
                "[1, 2\n",
                "Invalid YAML at line 2, column 1: expected ',' or ']', but got '<stream end>'",
            ),
            ("bell: \x07\n", "unacceptable character #x0007"),
        ],
        ids=["bad-indentation", "unclosed-sequence", "control-character"],
    )
    def test_invalid_yaml_fails(self, tmp_path, content, message_prefix):
        path = tmp_path / "config.yaml"
        path.write_text(content)

        result = YamlValidValidator(str(path), {}).validate()

        assert result.passed is False
        assert result.validator_type == "yaml-valid"
        assert result.error_message.startswith(message_prefix)


class TestCommandValidator:
    def test_zero_exit_passes(self, tmp_path):
        path = tmp_path / "output.md"
        path.write_text("test content")

        result = CommandValidator({"cmd": "test -f {file}", "file": str(path)}, {}).validate()

        assert result.passed is True
        assert result.validator_type == "command"
        assert result.details == {"cmd": f"test -f {path}", "exit_code": 0, "stdout": ""}

    def test_nonzero_exit_fails_with_output(self):
        cmd = "echo checked; echo broken >&2; exit 3"

        result = CommandValidator({"cmd": cmd}, {}).validate()

        assert result.passed is False
        assert result.error_message == "Command failed with exit code 3"
        assert result.details == {
            "cmd": cmd,
            "exit_code": 3,
            "stdout": "checked\n",
            "stderr": "broken\n",
        }

    def test_cmd_and_file_are_interpolated(self, tmp_path):
        path = tmp_path / "output.md"
        path.write_text("Expected content")
        config = {"cmd": "grep {{search_text}} {file}", "file": "{{test_file}}"}
        resolved_vars = {"test_file": str(path), "search_text": "Expected"}

        result = CommandValidator(config, resolved_vars).validate()

        assert result.passed is True
        assert result.details["cmd"] == f"grep Expected {path}"

    def test_runs_without_file(self):
        result = CommandValidator({"cmd": "echo test | grep test"}, {}).validate()

        assert result.passed is True
        assert result.details["stdout"] == "test\n"

    @pytest.mark.parametrize(
        "config, message",
        [
            ("echo test", "Command validator requires dict with 'cmd' and optional 'file' keys"),
            ({"file": "output.md"}, "Command validator requires 'cmd' field"),
            ({"cmd": ""}, "Command validator requires 'cmd' field"),
        ],
        ids=["not-a-dict", "missing-cmd", "empty-cmd"],
    )
    def test_invalid_config_fails(self, config, message):
        result = CommandValidator(config, {}).validate()

        assert result.passed is False
        assert result.error_message == message

    def test_timeout_stops_command(self):
        start = time.monotonic()
        result = CommandValidator({"cmd": "sleep 5", "timeout": 1}, {}).validate()
        elapsed = time.monotonic() - start

        assert result.passed is False
        assert "timed out after 1" in result.error_message
        assert elapsed < 4

    def test_default_timeout(self):
        with patch("src.task_validators.subprocess.run", return_value=completed()) as run:
            result = CommandValidator({"cmd": "make check"}, {}).validate()

        assert result.passed is True
        assert DEFAULT_COMMAND_TIMEOUT == 30
        run.assert_called_once_with(
            "make check",
            shell=True,
            capture_output=True,
            text=True,
            timeout=DEFAULT_COMMAND_TIMEOUT,
        )

    def test_output_in_details_is_truncated(self):
        output = completed(returncode=1, stdout="o" * 300, stderr="e" * 300)
        with patch("src.task_validators.subprocess.run", return_value=output):
            result = CommandValidator({"cmd": "make check"}, {}).validate()

        assert result.details["stdout"] == "o" * 200
        assert result.details["stderr"] == "e" * 200

    def test_launch_error_fails(self):
        with patch("src.task_validators.subprocess.run", side_effect=OSError("no shell")):
            result = CommandValidator({"cmd": "make check"}, {}).validate()

        assert result.passed is False
        assert result.error_message == "Error executing command: no shell"


class TestCreateValidator:
    @pytest.mark.parametrize(
        "validator_type, validator_class",
        [
            ("file-exists", FileExistsValidator),
            ("file-not-empty", FileNotEmptyValidator),
            ("contains", ContainsValidator),
            ("json-valid", JsonValidValidator),
            ("yaml-valid", YamlValidValidator),
            ("command", CommandValidator),
        ],
        ids=["file-exists", "file-not-empty", "contains", "json-valid", "yaml-valid", "command"],
    )
    def test_builds_validator_for_type(self, validator_type, validator_class):
        config = {"file": "output.md"}

        validator = create_validator(validator_type, config, {"env": "prod"})

        assert type(validator) is validator_class
        assert validator.config == config
        assert validator.resolved_vars == {"env": "prod"}

    def test_unknown_type_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            create_validator("unknown-type", {}, {})

        assert str(exc_info.value) == UNKNOWN_TYPE_MESSAGE


class TestRunValidators:
    def test_all_pass(self, tmp_path, capsys):
        (tmp_path / "report.md").write_text("Test content")
        validators = [
            {"file-exists": "{{out_dir}}/report.md"},
            {"file-not-empty": "{{out_dir}}/report.md"},
            {"contains": {"file": "{{out_dir}}/report.md", "text": "Test"}},
        ]

        result = run_validators(validators, {"out_dir": str(tmp_path)})

        assert result["all_passed"] is True
        assert result["failed_count"] == 0
        assert result["total_count"] == 3
        assert [(r["validator_type"], r["passed"]) for r in result["results"]] == [
            ("file-exists", True),
            ("file-not-empty", True),
            ("contains", True),
        ]
        assert capsys.readouterr().err == (
            "  ✅ Validator passed: file-exists\n"
            "  ✅ Validator passed: file-not-empty\n"
            "  ✅ Validator passed: contains\n"
        )

    def test_counts_failures_and_runs_every_validator(self, tmp_path, capsys):
        present = tmp_path / "present.txt"
        present.write_text("Test content")
        missing = tmp_path / "missing.txt"
        validators = [
            {"file-exists": str(present)},
            {"file-exists": str(missing)},
            {"file-not-empty": str(missing)},
            {"file-not-empty": str(present)},
        ]

        result = run_validators(validators, {})

        assert result["all_passed"] is False
        assert result["failed_count"] == 2
        assert result["total_count"] == 4
        assert [r["passed"] for r in result["results"]] == [True, False, False, True]
        assert result["results"][1]["error_message"] == f"File does not exist: {missing}"
        assert result["results"][2]["error_message"] == f"File does not exist: {missing}"
        assert (
            f"  ❌ Validator failed: file-exists - File does not exist: {missing}\n"
            in capsys.readouterr().err
        )

    @pytest.mark.parametrize(
        "definition, validator_type, message",
        [
            ("file-exists", "unknown", "Invalid validator definition: must be dict, got str"),
            ({}, "unknown", "Invalid validator definition: must have exactly one key, got 0"),
            (
                {"file-exists": "a.txt", "file-not-empty": "a.txt"},
                "unknown",
                "Invalid validator definition: must have exactly one key, got 2",
            ),
            ({"unknown-type": "a.txt"}, "unknown-type", UNKNOWN_TYPE_MESSAGE),
        ],
        ids=["not-a-dict", "no-keys", "two-keys", "unknown-type"],
    )
    def test_invalid_definition_fails(self, definition, validator_type, message):
        result = run_validators([definition], {})

        assert result == {
            "all_passed": False,
            "results": [
                {
                    "validator_type": validator_type,
                    "passed": False,
                    "error_message": message,
                    "details": {},
                }
            ],
            "failed_count": 1,
            "total_count": 1,
        }

    def test_empty_list_passes(self):
        assert run_validators([], {}) == {
            "all_passed": True,
            "results": [],
            "failed_count": 0,
            "total_count": 0,
        }


class TestValidatorResult:
    def test_to_dict(self, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_text("")

        result = FileNotEmptyValidator(str(empty), {}).validate()

        assert result.to_dict() == {
            "validator_type": "file-not-empty",
            "passed": False,
            "error_message": f"File is empty: {empty} (size: 0 bytes)",
            "details": {"file": str(empty), "size": 0},
        }

    def test_to_dict_defaults(self):
        assert ValidatorResult("file-exists", passed=True).to_dict() == {
            "validator_type": "file-exists",
            "passed": True,
            "error_message": None,
            "details": {},
        }
