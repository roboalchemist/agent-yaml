"""Unit tests for src/skip_conditions.py (task-level `skip-if:`)."""

import pytest

from src.skip_conditions import (
    FileContainsSkipCondition,
    FileExistsSkipCondition,
    SkipConditionError,
    SkipConditionResult,
    check_skip_conditions,
    create_skip_condition,
)

UNKNOWN_TYPE_MESSAGE = (
    "Unknown skip condition type: unknown-condition. Supported types: file-exists, file-contains"
)


def skip_config(condition_type, path):
    """A skip-if block of `condition_type` that is met when `path` exists and contains DONE."""
    if condition_type == "file-exists":
        return {"file-exists": path}
    return {"file-contains": {"path": path, "text": "DONE"}}


@pytest.fixture(params=["file-exists", "file-contains"])
def condition_type(request):
    return request.param


class TestFileExists:
    def test_skips_when_file_exists(self, tmp_path):
        flag = tmp_path / "deployed.flag"
        flag.write_text("")

        result = FileExistsSkipCondition(str(flag), {}, str(tmp_path)).check()

        assert result.should_skip is True
        assert result.condition_type == "file-exists"
        assert result.reason == f"file-exists condition met: {flag}"
        assert result.details == {"file": str(flag)}

    def test_does_not_skip_when_file_missing(self, tmp_path):
        missing = tmp_path / "deployed.flag"

        result = FileExistsSkipCondition(str(missing), {}, str(tmp_path)).check()

        assert result.should_skip is False
        assert result.condition_type == "file-exists"
        assert result.reason == f"file does not exist: {missing}"
        assert result.details == {"file": str(missing)}


class TestFileContains:
    def test_skips_when_text_found(self, tmp_path):
        content = "Status: SUCCESS\nAll operations completed."
        status = tmp_path / "status.txt"
        status.write_text(content)
        config = {"path": str(status), "text": "SUCCESS"}

        result = FileContainsSkipCondition(config, {}, str(tmp_path)).check()

        assert result.should_skip is True
        assert result.condition_type == "file-contains"
        assert result.reason == f"file-contains condition met: 'SUCCESS' found in {status}"
        assert result.details == {
            "file": str(status),
            "expected_text": "SUCCESS",
            "file_size": len(content),
        }

    def test_does_not_skip_when_text_missing(self, tmp_path):
        status = tmp_path / "status.txt"
        status.write_text("Status: PENDING\nWaiting for completion.")
        config = {"path": str(status), "text": "SUCCESS"}

        result = FileContainsSkipCondition(config, {}, str(tmp_path)).check()

        assert result.should_skip is False
        assert result.reason == "file does not contain expected text: 'SUCCESS'"

    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "status.txt"
        config = {"path": str(missing), "text": "x"}

        with pytest.raises(SkipConditionError) as exc_info:
            FileContainsSkipCondition(config, {}, str(tmp_path)).check()

        assert str(exc_info.value) == (
            f"file-contains skip condition: file does not exist: {missing}"
        )

    def test_unreadable_path_raises(self, tmp_path):
        """A path that exists but is not a readable file (a directory) is a skip-if error."""
        config = {"path": str(tmp_path), "text": "x"}
        condition = FileContainsSkipCondition(config, {}, str(tmp_path))

        with pytest.raises(SkipConditionError) as exc_info:
            condition.check()

        assert str(exc_info.value).startswith(f"Error reading file {tmp_path}: ")

    def test_path_and_text_are_interpolated(self, tmp_path):
        status = tmp_path / "status.txt"
        status.write_text("ALREADY_VALIDATED")
        config = {"path": "{{status_file}}", "text": "{{expected_text}}"}
        resolved_vars = {"status_file": str(status), "expected_text": "ALREADY_VALIDATED"}

        result = FileContainsSkipCondition(config, resolved_vars, str(tmp_path)).check()

        assert result.should_skip is True
        assert result.details["file"] == str(status)
        assert result.details["expected_text"] == "ALREADY_VALIDATED"

    @pytest.mark.parametrize(
        "config, message",
        [
            (
                "status.txt",
                "file-contains skip condition requires dict with 'path' and 'text' keys",
            ),
            (
                {"text": "SUCCESS"},
                "file-contains skip condition requires both 'path' and 'text' fields",
            ),
            (
                {"path": "status.txt"},
                "file-contains skip condition requires both 'path' and 'text' fields",
            ),
            (
                {"path": "status.txt", "text": ""},
                "file-contains skip condition requires both 'path' and 'text' fields",
            ),
        ],
        ids=["not-a-dict", "missing-path", "missing-text", "empty-text"],
    )
    def test_invalid_config_raises(self, tmp_path, config, message):
        condition = FileContainsSkipCondition(config, {}, str(tmp_path))

        with pytest.raises(SkipConditionError) as exc_info:
            condition.check()

        assert str(exc_info.value) == message

    @pytest.mark.parametrize("found", [True, False], ids=["found", "not-found"])
    def test_long_text_is_truncated_in_reason(self, tmp_path, found):
        long_text = "x" * 100
        status = tmp_path / "status.txt"
        status.write_text(long_text if found else "short")
        config = {"path": str(status), "text": long_text}

        result = FileContainsSkipCondition(config, {}, str(tmp_path)).check()

        truncated = "x" * 47 + "..."
        assert result.should_skip is found
        assert f"'{truncated}'" in result.reason
        assert long_text not in result.reason
        assert result.details["expected_text"] == long_text


class TestPathResolution:
    """Both condition types resolve their path the same way."""

    def test_relative_path_resolves_against_working_dir(self, tmp_path, condition_type):
        (tmp_path / "flag.txt").write_text("DONE")

        result = check_skip_conditions(skip_config(condition_type, "flag.txt"), {}, str(tmp_path))

        assert result.should_skip is True
        assert result.details["file"] == str(tmp_path / "flag.txt")

    def test_absolute_path_ignores_working_dir(self, tmp_path, condition_type):
        flag = tmp_path / "data" / "flag.txt"
        flag.parent.mkdir()
        flag.write_text("DONE")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = check_skip_conditions(skip_config(condition_type, str(flag)), {}, str(elsewhere))

        assert result.should_skip is True
        assert result.details["file"] == str(flag)

    def test_working_dir_defaults_to_cwd(self, tmp_path, monkeypatch, condition_type):
        (tmp_path / "flag.txt").write_text("DONE")
        monkeypatch.chdir(tmp_path)

        result = check_skip_conditions(skip_config(condition_type, "flag.txt"), {})

        assert result.should_skip is True
        assert result.details["file"] == str(tmp_path / "flag.txt")

    def test_tilde_expands_to_home(self, tmp_path, monkeypatch, condition_type):
        home = tmp_path / "home"
        home.mkdir()
        (home / "flag.txt").write_text("DONE")
        monkeypatch.setenv("HOME", str(home))

        result = check_skip_conditions(skip_config(condition_type, "~/flag.txt"), {}, str(tmp_path))

        assert result.should_skip is True
        assert result.details["file"] == str(home / "flag.txt")

    def test_variables_are_interpolated(self, tmp_path, condition_type):
        (tmp_path / "flag.txt").write_text("DONE")
        config = skip_config(condition_type, "{{flag_dir}}/flag.txt")

        result = check_skip_conditions(config, {"flag_dir": str(tmp_path)}, str(tmp_path))

        assert result.should_skip is True
        assert result.details["file"] == str(tmp_path / "flag.txt")


class TestCreateSkipCondition:
    @pytest.mark.parametrize(
        "condition_type, config, condition_class",
        [
            ("file-exists", "flag.txt", FileExistsSkipCondition),
            ("file-contains", {"path": "status.txt", "text": "OK"}, FileContainsSkipCondition),
        ],
        ids=["file-exists", "file-contains"],
    )
    def test_builds_condition_for_type(self, tmp_path, condition_type, config, condition_class):
        condition = create_skip_condition(condition_type, config, {"env": "prod"}, str(tmp_path))

        assert type(condition) is condition_class
        assert condition.config == config
        assert condition.resolved_vars == {"env": "prod"}
        assert condition.working_dir == str(tmp_path)

    def test_unknown_type_raises(self):
        with pytest.raises(SkipConditionError) as exc_info:
            create_skip_condition("unknown-condition", {}, {})

        assert str(exc_info.value) == UNKNOWN_TYPE_MESSAGE


class TestCheckSkipConditions:
    def test_met_condition_is_returned_and_logged(self, tmp_path, capsys, condition_type):
        flag = tmp_path / "flag.txt"
        flag.write_text("DONE")

        result = check_skip_conditions(skip_config(condition_type, str(flag)), {}, str(tmp_path))

        assert result.should_skip is True
        assert result.condition_type == condition_type
        assert capsys.readouterr().err == f"Task skipped: {result.reason}\n"

    def test_unmet_condition_is_not_logged(self, tmp_path, capsys):
        config = {"file-exists": str(tmp_path / "missing.txt")}

        result = check_skip_conditions(config, {}, str(tmp_path))

        assert result.should_skip is False
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize(
        "config, message",
        [
            ("deployed.flag", "skip-if must be a dict, got str"),
            (["file-exists"], "skip-if must be a dict, got list"),
            ({}, "skip-if must have exactly one condition, got 0"),
            (
                {"file-exists": "a.txt", "file-contains": {"path": "b.txt", "text": "x"}},
                "skip-if must have exactly one condition, got 2",
            ),
            ({"unknown-condition": "x"}, UNKNOWN_TYPE_MESSAGE),
        ],
        ids=["string", "list", "no-condition", "two-conditions", "unknown-type"],
    )
    def test_invalid_config_raises(self, tmp_path, config, message):
        with pytest.raises(SkipConditionError) as exc_info:
            check_skip_conditions(config, {}, str(tmp_path))

        assert str(exc_info.value) == message


class TestSkipConditionResult:
    def test_to_dict(self, tmp_path):
        flag = tmp_path / "flag.txt"
        flag.write_text("")

        result = FileExistsSkipCondition(str(flag), {}, str(tmp_path)).check()

        assert result.to_dict() == {
            "condition_type": "file-exists",
            "should_skip": True,
            "reason": f"file-exists condition met: {flag}",
            "details": {"file": str(flag)},
        }

    def test_to_dict_defaults(self):
        assert SkipConditionResult("file-exists", should_skip=False).to_dict() == {
            "condition_type": "file-exists",
            "should_skip": False,
            "reason": None,
            "details": {},
        }
