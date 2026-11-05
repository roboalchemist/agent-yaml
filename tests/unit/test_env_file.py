"""Unit tests for .env parsing in agent_yaml/cli.py (parse_env_file, load_env_files)."""

import os

import pytest

from agent_yaml.cli import EnvFileError, load_env_files, parse_env_file


class TestParseEnvFile:
    @pytest.mark.parametrize(
        "text, expected",
        [
            pytest.param(
                "MY_KEY=my_value\nDB_URL=postgres://localhost\n",
                {"MY_KEY": "my_value", "DB_URL": "postgres://localhost"},
                id="key-value",
            ),
            pytest.param(
                "# This is a comment\nMY_KEY=value\n  # Indented comment\nOTHER_KEY=other_value\n",
                {"MY_KEY": "value", "OTHER_KEY": "other_value"},
                id="comment-lines",
            ),
            pytest.param(
                "KEY1=value1\n\n\nKEY2=value2\n",
                {"KEY1": "value1", "KEY2": "value2"},
                id="blank-lines",
            ),
            pytest.param("", {}, id="empty-file"),
            pytest.param("# Comment\n\n# Another comment\n   \n", {}, id="only-comments"),
            pytest.param('MESSAGE="Hello World"\n', {"MESSAGE": "Hello World"}, id="double-quotes"),
            pytest.param("MESSAGE='Hello World'\n", {"MESSAGE": "Hello World"}, id="single-quotes"),
            pytest.param(
                "INNER='has \"inner\" quotes'\n",
                {"INNER": 'has "inner" quotes'},
                id="nested-quotes",
            ),
            pytest.param(
                "MISMATCHED=\"not matched'\n",
                {"MISMATCHED": "\"not matched'"},
                id="mismatched-quotes-kept",
            ),
            pytest.param('LONE="\n', {"LONE": '"'}, id="lone-quote-kept"),
            pytest.param('EMPTY_QUOTED=""\n', {"EMPTY_QUOTED": ""}, id="empty-quotes"),
            pytest.param(
                'QUOTED_SPACE="  has spaces  "\n',
                {"QUOTED_SPACE": "  has spaces  "},
                id="quotes-keep-whitespace",
            ),
            pytest.param(
                "SPACED_VALUE=  has spaces  \n",
                {"SPACED_VALUE": "has spaces"},
                id="unquoted-value-stripped",
            ),
            pytest.param("  SPACED_KEY  =value\n", {"SPACED_KEY": "value"}, id="key-stripped"),
            pytest.param(
                "CONNECTION_STRING=host=localhost;port=5432\n",
                {"CONNECTION_STRING": "host=localhost;port=5432"},
                id="equals-in-value",
            ),
            pytest.param(
                "EMPTY_VAR=\nANOTHER_EMPTY=\n",
                {"EMPTY_VAR": "", "ANOTHER_EMPTY": ""},
                id="empty-values",
            ),
            pytest.param(
                "TOKEN=abc # rotate monthly\n",
                {"TOKEN": "abc # rotate monthly"},
                id="inline-hash-is-value",
            ),
            pytest.param(
                "export API_KEY=secret\n",
                {"export API_KEY": "secret"},
                id="export-prefix-not-special",
            ),
            pytest.param(
                "VALID=value\nINVALID_NO_EQUALS\nANOTHER=another\n",
                {"VALID": "value", "ANOTHER": "another"},
                id="no-equals-skipped",
            ),
            pytest.param("=orphan\nKEY=value\n", {"KEY": "value"}, id="empty-key-skipped"),
            pytest.param("KEY=first\nKEY=second\n", {"KEY": "second"}, id="last-duplicate-wins"),
            pytest.param(
                "KEY=value\r\nOTHER=x\r\n", {"KEY": "value", "OTHER": "x"}, id="crlf-line-endings"
            ),
        ],
    )
    def test_parses_line_formats(self, tmp_path, text, expected):
        env_file = tmp_path / ".env"
        env_file.write_text(text)

        assert parse_env_file(str(env_file)) == expected

    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "missing.env"

        with pytest.raises(EnvFileError) as exc_info:
            parse_env_file(str(missing))

        assert str(exc_info.value) == f"Environment file not found: {missing}"

    def test_directory_raises(self, tmp_path):
        with pytest.raises(EnvFileError) as exc_info:
            parse_env_file(str(tmp_path))

        assert str(exc_info.value) == f"Environment file is not a regular file: {tmp_path}"

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
    def test_unreadable_file_raises(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        env_file.chmod(0o000)

        with pytest.raises(EnvFileError) as exc_info:
            parse_env_file(str(env_file))

        assert str(exc_info.value) == f"Permission denied reading environment file: {env_file}"

    def test_tilde_expands_to_home(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("TEST=value\n")
        monkeypatch.setenv("HOME", str(tmp_path))

        assert parse_env_file("~/.env") == {"TEST": "value"}

    def test_missing_tilde_path_reports_expanded_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))

        with pytest.raises(EnvFileError) as exc_info:
            parse_env_file("~/missing.env")

        assert str(exc_info.value) == f"Environment file not found: {tmp_path / 'missing.env'}"


class TestLoadEnvFiles:
    def test_single_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")

        assert load_env_files([str(env_file)]) == {"KEY": "value"}

    @pytest.mark.parametrize(
        "order, shared",
        [(["base", "local"], "local"), (["local", "base"], "base")],
        ids=["base-then-local", "local-then-base"],
    )
    def test_later_files_override_earlier(self, tmp_path, order, shared):
        (tmp_path / "base").write_text("ONLY_BASE=base\nSHARED=base\n")
        (tmp_path / "local").write_text("ONLY_LOCAL=local\nSHARED=local\n")

        result = load_env_files([str(tmp_path / name) for name in order])

        assert result == {"ONLY_BASE": "base", "ONLY_LOCAL": "local", "SHARED": shared}

    def test_no_files(self):
        assert load_env_files([]) == {}

    def test_missing_file_raises(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        missing = tmp_path / "missing.env"

        with pytest.raises(EnvFileError) as exc_info:
            load_env_files([str(env_file), str(missing)])

        assert str(exc_info.value) == f"Environment file not found: {missing}"
