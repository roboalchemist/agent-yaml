"""Workflow file loading (agent_yaml/parser.py)."""

import pytest
import yaml

from agent_yaml.parser import parse_workflow


def workflow_file(tmp_path, text):
    """Write text to a workflow file; returns the path as a string, the way the CLI passes it."""
    path = tmp_path / "workflow.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestParseWorkflow:
    def test_returns_the_parsed_mapping(self, tmp_path):
        path = workflow_file(tmp_path, "directory: /tmp\ntask:\n  - test:\n      prompt: 'test'\n")
        assert parse_workflow(path) == {"directory": "/tmp", "task": [{"test": {"prompt": "test"}}]}

    def test_parses_nested_task_structure(self, tmp_path):
        path = workflow_file(
            tmp_path,
            "directory: /tmp\n"
            "task:\n"
            "  - parent:\n"
            "      task:\n"
            "        - child:\n"
            "            prompt: 'nested'\n",
        )
        assert parse_workflow(path)["task"] == [
            {"parent": {"task": [{"child": {"prompt": "nested"}}]}}
        ]

    def test_reads_non_ascii_text(self, tmp_path):
        path = workflow_file(
            tmp_path,
            "directory: /tmp\ntask:\n  - résumé:\n      prompt: 'Écris « bonjour » 日本語'\n",
        )
        assert parse_workflow(path)["task"] == [{"résumé": {"prompt": "Écris « bonjour » 日本語"}}]

    def test_invalid_yaml_raises_yaml_error(self, tmp_path):
        path = workflow_file(tmp_path, "invalid: yaml: syntax: here\n  - bad indentation\n")
        with pytest.raises(yaml.YAMLError):
            parse_workflow(path)

    @pytest.mark.parametrize(
        "tagged_value", ["!!python/tuple [1, 2]", "!!python/object/apply:os.getcwd []"]
    )
    def test_python_tags_are_rejected(self, tmp_path, tagged_value):
        """Files are loaded with yaml.safe_load, so a workflow cannot build Python objects."""
        path = workflow_file(tmp_path, f"directory: {tagged_value}\ntask: []\n")
        with pytest.raises(yaml.YAMLError):
            parse_workflow(path)

    def test_missing_file_raises_file_not_found(self, tmp_path):
        missing = str(tmp_path / "missing.yaml")
        with pytest.raises(FileNotFoundError) as exc_info:
            parse_workflow(missing)
        assert "Workflow file not found" in str(exc_info.value)
        assert missing in str(exc_info.value)

    def test_comment_only_fixture_raises_value_error(self, fixtures_dir):
        path = str(fixtures_dir / "edge-cases" / "empty-workflow.yaml")
        with pytest.raises(ValueError) as exc_info:
            parse_workflow(path)
        assert "Empty workflow file" in str(exc_info.value)
        assert path in str(exc_info.value)

    @pytest.mark.parametrize(
        "text", ["", "\n   \n", "---\n"], ids=["zero-bytes", "whitespace", "document-marker"]
    )
    def test_blank_documents_raise_value_error(self, tmp_path, text):
        with pytest.raises(ValueError, match="Empty workflow file"):
            parse_workflow(workflow_file(tmp_path, text))
