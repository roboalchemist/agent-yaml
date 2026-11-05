"""Unit tests for agent_yaml/ensure.py (start-time `ensure:` checks)."""

from unittest.mock import patch

import pytest

from agent_yaml.ensure import (
    EnsureValidationError,
    check_mcp_available,
    check_tool_available,
    validate_ensure_block,
)

INSTALL_HINT = (
    "Install missing tools using your package manager "
    "(e.g., brew install, apt-get install, pip install)"
)


def which_finding(*installed):
    """A shutil.which stand-in that finds only the `installed` executables."""
    return lambda name: f"/usr/bin/{name}" if name in installed else None


class TestCheckToolAvailable:
    @pytest.mark.parametrize(
        "which_result, expected",
        [("/usr/bin/python", True), (None, False)],
        ids=["on-path", "missing"],
    )
    def test_reports_whether_tool_is_on_path(self, which_result, expected):
        with patch("shutil.which", return_value=which_result) as which:
            assert check_tool_available("python") is expected

        which.assert_called_once_with("python")


class TestCheckMcpAvailable:
    def test_warns_and_assumes_available(self, capsys):
        assert check_mcp_available("test-mcp") is True

        assert capsys.readouterr().err == (
            "Warning: MCP availability check for 'test-mcp' is not fully implemented\n"
        )


class TestValidateEnsureBlock:
    @pytest.mark.parametrize(
        "ensure_config",
        [None, {}, {"tools": [], "mcps": []}],
        ids=["none", "empty", "empty-lists"],
    )
    def test_nothing_required_passes(self, ensure_config):
        with patch("shutil.which") as which:
            assert validate_ensure_block(ensure_config) is True

        which.assert_not_called()

    def test_all_tools_present_passes(self):
        with patch("shutil.which", side_effect=which_finding("python", "git")) as which:
            assert validate_ensure_block({"tools": ["python", "git"]}) is True

        assert [c.args for c in which.call_args_list] == [("python",), ("git",)]

    @pytest.mark.parametrize(
        "tools, installed, listed",
        [
            (["nonexistent-tool"], (), "nonexistent-tool"),
            (["tool1", "tool2", "tool3"], (), "tool1, tool2, tool3"),
            (["python", "nonexistent-tool", "git"], ("python", "git"), "nonexistent-tool"),
        ],
        ids=["one-missing", "all-missing", "only-missing-listed"],
    )
    def test_missing_tools_raise(self, tools, installed, listed):
        with patch("shutil.which", side_effect=which_finding(*installed)):
            with pytest.raises(EnsureValidationError) as exc_info:
                validate_ensure_block({"tools": tools})

        assert str(exc_info.value) == f"Missing required tools: [{listed}]\n{INSTALL_HINT}"

    def test_mcps_warn_and_pass(self, capsys):
        assert validate_ensure_block({"mcps": ["filesystem", "github"]}) is True

        err = capsys.readouterr().err
        assert "check for 'filesystem' is not fully implemented" in err
        assert "check for 'github' is not fully implemented" in err

    @pytest.mark.parametrize(
        "tools, message",
        [
            (
                ["jq"],
                f"Missing required tools: [jq]; Missing required MCPs: [github]\n{INSTALL_HINT}",
            ),
            ([], "Missing required MCPs: [github]"),
        ],
        ids=["with-missing-tool", "mcp-only"],
    )
    def test_missing_mcps_are_reported(self, tools, message):
        """MCP detection is a stub today; this pins the message once it can report a miss."""
        with patch("shutil.which", return_value=None):
            with patch("agent_yaml.ensure.check_mcp_available", return_value=False):
                with pytest.raises(EnsureValidationError) as exc_info:
                    validate_ensure_block({"tools": tools, "mcps": ["github"]})

        assert str(exc_info.value) == message
