"""Unit tests for agent_yaml/includes.py: include files, prompt composition, include cycles."""

import os

import pytest

from agent_yaml.includes import (
    CircularIncludeError,
    append_includes_to_prompt,
    detect_circular_includes,
    resolve_includes,
)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestResolveIncludes:
    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("Use sub-agents liberally", id="plain"),
            pytest.param("Line 1\nLine 2\nLine 3", id="newlines"),
            pytest.param("Unicode test: café, naïve, 日本語", id="unicode"),
        ],
    )
    def test_single_file_content_is_returned_verbatim(self, tmp_path, content):
        write(tmp_path / "include.txt", content)
        assert resolve_includes(["include.txt"], str(tmp_path), {}) == content

    def test_files_are_joined_in_list_order_with_one_space(self, tmp_path):
        write(tmp_path / "a.txt", "First part")
        write(tmp_path / "b.txt", "Second\npart")
        write(tmp_path / "c.txt", "Third part")

        result = resolve_includes(["c.txt", "a.txt", "b.txt"], str(tmp_path), {})

        assert result == "Third part First part Second\npart"

    def test_placeholders_in_content_are_left_for_the_prompt_interpolation(self, tmp_path):
        write(tmp_path / "guide.txt", "Hello {{name}}")
        assert resolve_includes(["guide.txt"], str(tmp_path), {"name": "World"}) == "Hello {{name}}"

    @pytest.mark.parametrize(
        "include_path, location, variables",
        [
            pytest.param("guide.txt", "wf/guide.txt", {}, id="relative"),
            pytest.param(
                "includes/nested/guide.txt", "wf/includes/nested/guide.txt", {}, id="nested"
            ),
            pytest.param("../shared/guide.txt", "shared/guide.txt", {}, id="parent-dir"),
            pytest.param(
                "prompts/{{topic}}-guide.txt",
                "wf/prompts/auth-guide.txt",
                {"topic": "auth"},
                id="variable",
            ),
            pytest.param(
                "{{service}}/{{topic}}-guide.txt",
                "wf/api/auth-guide.txt",
                {"service": "api", "topic": "auth"},
                id="variables",
            ),
        ],
    )
    def test_relative_paths_resolve_against_workflow_dir(
        self, tmp_path, include_path, location, variables
    ):
        write(tmp_path / location, "guide content")
        result = resolve_includes([include_path], str(tmp_path / "wf"), variables)
        assert result == "guide content"

    def test_absolute_path_ignores_workflow_dir(self, tmp_path):
        target = write(tmp_path / "shared" / "absolute.txt", "Absolute path content")
        result = resolve_includes([str(target)], str(tmp_path / "wf"), {})
        assert result == "Absolute path content"

    def test_variable_may_expand_to_an_absolute_path(self, tmp_path):
        write(tmp_path / "shared" / "rules.txt", "Shared rules")
        result = resolve_includes(
            ["{{gitroot}}/shared/rules.txt"], str(tmp_path / "wf"), {"gitroot": str(tmp_path)}
        )
        assert result == "Shared rules"

    def test_tilde_expands_to_home(self, tmp_path, monkeypatch):
        write(tmp_path / "prompts" / "home-test.txt", "Home directory test")
        monkeypatch.setenv("HOME", str(tmp_path))

        result = resolve_includes(["~/prompts/home-test.txt"], str(tmp_path / "wf"), {})

        assert result == "Home directory test"

    @pytest.mark.parametrize("include_list", [[], None])
    def test_no_includes_resolve_to_empty_string(self, tmp_path, include_list):
        assert resolve_includes(include_list, str(tmp_path), {}) == ""

    def test_missing_file_raises_with_the_resolved_path(self, tmp_path):
        with pytest.raises(FileNotFoundError) as excinfo:
            resolve_includes(["nonexistent.txt"], str(tmp_path), {})

        message = str(excinfo.value)
        assert message.startswith("Include file resolution failed")
        assert f"File not found: {tmp_path / 'nonexistent.txt'}\n" in message

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
    def test_unreadable_file_raises_permission_error(self, tmp_path):
        target = write(tmp_path / "restricted.txt", "Restricted content")
        target.chmod(0o000)
        try:
            with pytest.raises(PermissionError) as excinfo:
                resolve_includes(["restricted.txt"], str(tmp_path), {})
        finally:
            target.chmod(0o644)

        message = str(excinfo.value)
        assert message.startswith("Include file access denied")
        assert f"Permission denied reading file: {target}\n" in message


class TestAppendIncludesToPrompt:
    @pytest.mark.parametrize(
        "prompt, include_string, expected",
        [
            pytest.param(
                "Analyze the codebase",
                "Use sub-agents liberally",
                "Analyze the codebase Use sub-agents liberally",
                id="single-include",
            ),
            pytest.param(
                "Do work",
                "Use sub-agents Be thorough Test everything",
                "Do work Use sub-agents Be thorough Test everything",
                id="pre-joined-includes",
            ),
            pytest.param(
                "Generate documentation for the API",
                "Follow Google style guide Include code examples",
                "Generate documentation for the API"
                " Follow Google style guide Include code examples",
                id="spec-example",
            ),
            pytest.param(
                "Step 1: Initialize\nStep 2: Execute\nStep 3: Validate",
                "Use error handling",
                "Step 1: Initialize\nStep 2: Execute\nStep 3: Validate Use error handling",
                id="multiline-prompt",
            ),
            pytest.param(
                "Process data",
                "Use {{variable}} and check $ENV_VAR",
                "Process data Use {{variable}} and check $ENV_VAR",
                id="placeholders-kept",
            ),
            pytest.param("Complete the task", "", "Complete the task", id="empty-include"),
            pytest.param("Complete the task", None, "Complete the task", id="none-include"),
            pytest.param("Do the work", "   ", "Do the work    ", id="blank-include-appended"),
            pytest.param("", "Use best practices", " Use best practices", id="empty-prompt"),
        ],
    )
    def test_prompt_then_one_space_then_includes(self, prompt, include_string, expected):
        assert append_includes_to_prompt(prompt, include_string) == expected


class TestDetectCircularIncludes:
    @pytest.mark.parametrize(
        "includes",
        [
            pytest.param(
                {"intro": "Start here", "guide": "Follow these steps", "outro": "Finish up"},
                id="no-references",
            ),
            pytest.param(
                {"intro": "Start with {{topic}}", "guide": "Use {{context}} approach"},
                id="variables-not-includes",
            ),
            pytest.param(
                {
                    "intro": "Start with {{topic}} and {{service}}",
                    "guide": "Use {{topic}} approach",
                },
                id="several-variables",
            ),
            pytest.param(
                {"a": "Start with {{b}}", "b": "Then {{c}}", "c": "Finally {{d}}", "d": "Done"},
                id="linear-chain",
            ),
            pytest.param(
                {"intro": "Use {{common}}", "guide": "Also {{common}}", "common": "Shared"},
                id="shared-include",
            ),
            pytest.param({}, id="empty"),
            pytest.param(None, id="none"),
        ],
    )
    def test_acyclic_includes_are_accepted(self, includes):
        assert detect_circular_includes(includes) is None

    @pytest.mark.parametrize(
        "includes, chain",
        [
            pytest.param({"intro": "Start with {{intro}}"}, "intro -> intro", id="self"),
            pytest.param({"intro": "Start {{ intro }}"}, "intro -> intro", id="spaces-in-braces"),
            pytest.param(
                {"intro": "Start with {{context}}", "context": "Use {{intro}}"},
                "intro -> context -> intro",
                id="two-way",
            ),
            pytest.param(
                {"a": "{{b}}", "b": "{{c}}", "c": "{{a}}"}, "a -> b -> c -> a", id="three-way"
            ),
            pytest.param(
                {
                    "intro": "Start with {{topic}} and {{context}}",
                    "context": "Use {{background}} for {{service}}",
                    "background": "Reference {{intro}} about {{topic}}",
                },
                "intro -> context -> background -> intro",
                id="mixed-with-variables",
            ),
            pytest.param(
                {"entry": "{{a}}", "a": "{{b}}", "b": "{{a}}"},
                "a -> b -> a",
                id="entry-outside-cycle",
            ),
        ],
    )
    def test_cycle_is_reported_with_its_chain(self, includes, chain):
        with pytest.raises(CircularIncludeError) as excinfo:
            detect_circular_includes(includes)

        assert f"Found: Circular chain: {chain}\n" in str(excinfo.value)

    def test_error_message_format(self):
        includes = {
            "intro": "Start with {{context}}",
            "context": "Use {{background}}",
            "background": "Reference {{intro}}",
        }

        with pytest.raises(CircularIncludeError) as excinfo:
            detect_circular_includes(includes)

        assert str(excinfo.value).splitlines() == [
            "Circular include dependency detected",
            "",
            "Context: Include resolution for workflow includes",
            "Expected: Acyclic include dependencies",
            "Found: Circular chain: intro -> context -> background -> intro",
            "Suggestion: Break the circular reference by removing include references"
            " or using literal text",
        ]
