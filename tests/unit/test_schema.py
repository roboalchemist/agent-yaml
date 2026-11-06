"""Workflow schema validation (agent_yaml/validator.py) through the public validate_workflow()."""

import pytest

from agent_yaml.validator import ValidationError, validate_workflow


def yaml_keys(fields):
    """Keyword arguments as YAML keys: skip_if=... becomes "skip-if"."""
    return {key.replace("_", "-"): value for key, value in fields.items()}


def task(name="t", prompt="Do the work", **fields):
    """A task-list entry {name: definition}; prompt=None leaves the prompt out."""
    definition = {} if prompt is None else {"prompt": prompt}
    definition.update(yaml_keys(fields))
    return {name: definition}


def group(name, *entries, **fields):
    """A grouping task whose child tasks are direct keys (they run in parallel)."""
    definition = yaml_keys(fields)
    for entry in entries:
        definition.update(entry)
    return {name: definition}


def workflow(*tasks, **fields):
    """A minimal valid workflow (directory + tasks, default one task) plus top-level fields."""
    return {"directory": "/work", "task": list(tasks) or [task()], **yaml_keys(fields)}


def loop_workflow(**loop):
    """A workflow whose only task loops with the given loop config."""
    return workflow(task(loop=yaml_keys(loop)))


def placed(entry, where):
    """A workflow with the task entry at the top level, in a nested `task:` list, or in a group."""
    if where == "top-level":
        return workflow(entry)
    if where == "nested":
        return workflow(task("parent", prompt=None, task=[task("first"), entry]))
    if where == "grouped":
        return workflow(group("parent", task("first"), entry))
    raise ValueError(f"unknown placement {where!r}")


def assert_invalid(wf, *fragments):
    """validate_workflow(wf) raises ValidationError whose message contains every fragment."""
    with pytest.raises(ValidationError) as exc_info:
        validate_workflow(wf)
    message = str(exc_info.value)
    for fragment in fragments:
        assert fragment in message


class TestRequiredFields:
    def test_minimal_workflow_is_valid(self):
        minimal = {"directory": "/work", "task": [{"t": {"prompt": "Do it"}}]}
        assert validate_workflow(minimal) is True

    @pytest.mark.parametrize("value", ["directory: /work", ["directory", "task"], None])
    def test_workflow_must_be_a_mapping(self, value):
        assert_invalid(value, "Workflow must be a dictionary")

    @pytest.mark.parametrize("field", ["directory", "task"])
    def test_missing_required_field(self, field):
        wf = workflow()
        del wf[field]
        assert_invalid(wf, f"Field '{field}' is required")

    def test_empty_mapping_is_rejected(self):
        assert_invalid({}, "is required but missing")

    @pytest.mark.parametrize(
        "value, type_name", [(123, "int"), (["/work"], "list"), (None, "NoneType")]
    )
    def test_directory_must_be_a_string(self, value, type_name):
        assert_invalid(
            workflow(directory=value), "Field 'directory' must be a string", f"got {type_name}"
        )

    @pytest.mark.parametrize(
        "value, type_name", [("not a list", "str"), (task(), "dict"), (None, "NoneType")]
    )
    def test_task_must_be_a_list(self, value, type_name):
        assert_invalid(workflow(task=value), "Field 'task' must be a list", f"got {type_name}")

    def test_task_list_must_not_be_empty(self):
        assert_invalid(workflow(task=[]), "Workflow has no tasks", "Suggestion:")


class TestOptionalFields:
    def test_workflow_with_every_optional_field_is_valid(self):
        wf = workflow(
            cli_agent="opencode",
            cli_agent_config={"skip-confirmations": True, "timeout": 3600},
            on_error="continue",
            template_variables={"topic": "test", "retries": 3},
            ensure={"mcps": ["notion", "linear"], "tools": ["gh", "git"]},
            environment={"LOG_LEVEL": "info"},
            includes={"use-intro": "Read the intro before starting"},
        )
        assert validate_workflow(wf) is True

    def test_name_and_description_metadata_are_allowed(self):
        """Several shipped examples carry these informational keys."""
        wf = workflow(name="JSON loop", description="Loops over the users file")
        assert validate_workflow(wf) is True

    @pytest.mark.parametrize("agent", ["opencode", "claude", "codex", "pi", "vtcode", "antigravity"])
    def test_supported_cli_agents(self, agent):
        assert validate_workflow(workflow(cli_agent=agent)) is True

    def test_unknown_cli_agent_lists_the_supported_ones(self):
        assert_invalid(
            workflow(cli_agent="invalid-agent"),
            "Field 'cli-agent' must be one of",
            "'opencode'",
            "got 'invalid-agent'",
        )

    @pytest.mark.parametrize("value, type_name", [(["claude"], "list"), (None, "NoneType")])
    def test_cli_agent_must_be_a_string(self, value, type_name):
        assert_invalid(
            workflow(cli_agent=value), "Field 'cli-agent' must be a string", f"got {type_name}"
        )

    @pytest.mark.parametrize("strategy", ["fail", "continue", "skip"])
    def test_on_error_strategies(self, strategy):
        assert validate_workflow(workflow(on_error=strategy)) is True

    def test_unknown_on_error_lists_the_strategies(self):
        assert_invalid(
            workflow(on_error="invalid-strategy"),
            "Field 'on-error' must be one of",
            "'fail'",
            "'continue'",
            "'skip'",
            "got 'invalid-strategy'",
        )

    def test_on_error_must_be_a_string(self):
        assert_invalid(workflow(on_error=True), "Field 'on-error' must be a string", "got bool")

    @pytest.mark.parametrize(
        "field", ["cli-agent-config", "template-variables", "ensure", "environment", "includes"]
    )
    @pytest.mark.parametrize("value, type_name", [("not a dict", "str"), (["a", "b"], "list")])
    def test_mapping_fields_reject_other_types(self, field, value, type_name):
        assert_invalid(
            workflow(**{field: value}), f"Field '{field}' must be a dict", f"got {type_name}"
        )


class TestEnsure:
    @pytest.mark.parametrize(
        "ensure",
        [
            pytest.param(
                {"mcps": ["notion", "linear"], "tools": ["gh", "git"]}, id="mcps-and-tools"
            ),
            pytest.param({"mcps": ["notion"]}, id="mcps-only"),
            pytest.param({"tools": ["gh"]}, id="tools-only"),
            pytest.param({}, id="empty"),
        ],
    )
    def test_valid_ensure_blocks(self, ensure):
        assert validate_workflow(workflow(ensure=ensure)) is True

    @pytest.mark.parametrize(
        "key, value, type_name",
        [("mcps", "notion", "str"), ("tools", 123, "int"), ("tools", {"gh": "*"}, "dict")],
    )
    def test_ensure_entries_must_be_lists(self, key, value, type_name):
        assert_invalid(
            workflow(ensure={key: value}),
            f"Field 'ensure.{key}' must be a list",
            f"got {type_name}",
        )


class TestEnvironment:
    @pytest.mark.parametrize(
        "environment",
        [
            pytest.param({"LOG_LEVEL": "info", "WORKSPACE": "{{gitroot}}"}, id="templated-values"),
            pytest.param({}, id="empty"),
            # Values are converted to strings when the task runs.
            pytest.param({"RETRIES": 3, "VERBOSE": False, "UNSET": None}, id="non-string-values"),
        ],
    )
    def test_valid_environment(self, environment):
        assert validate_workflow(workflow(environment=environment)) is True

    def test_environment_keys_must_be_strings(self):
        assert_invalid(
            workflow(environment={1: "one"}),
            "Environment variable key must be a string",
            "got int",
        )


class TestIncludes:
    @pytest.mark.parametrize(
        "includes",
        [
            pytest.param(
                {"intro": "Start here", "context": "Use {{intro}}", "details": "Add {{ context }}"},
                id="chain",
            ),
            pytest.param(
                {"top": "{{left}} {{right}}", "left": "{{base}}", "right": "{{base}}", "base": "x"},
                id="shared-dependency",
            ),
            pytest.param({"intro": "Start with {{topic}}"}, id="template-variable-reference"),
            pytest.param({}, id="empty"),
        ],
    )
    def test_acyclic_includes_are_valid(self, includes):
        assert validate_workflow(workflow(includes=includes)) is True

    @pytest.mark.parametrize(
        "includes, chain",
        [
            pytest.param({"intro": "Start with {{intro}}"}, "intro -> intro", id="self"),
            pytest.param(
                {"intro": "Start with {{context}}", "context": "Use {{intro}}"},
                "intro -> context -> intro",
                id="two-way",
            ),
            pytest.param(
                {"intro": "{{context}}", "context": "{{background}}", "background": "{{intro}}"},
                "intro -> context -> background -> intro",
                id="three-way",
            ),
            pytest.param(
                {"plain": "No references", "a": "See {{ b }}", "b": "See {{ a }}"},
                "a -> b -> a",
                id="later-entries-spaced-braces",
            ),
        ],
    )
    def test_circular_includes_are_rejected_with_the_chain(self, includes, chain):
        assert_invalid(workflow(includes=includes), "Circular include dependency detected", chain)


class TestTaskStructure:
    @pytest.mark.parametrize(
        "entry",
        [
            pytest.param(task("build"), id="prompt"),
            pytest.param(
                {"lint": {"prompt": "Lint"}, "test": {"prompt": "Test"}}, id="parallel-step"
            ),
            pytest.param(
                task("parent", prompt=None, task=[task("child"), task("sibling")]),
                id="nested-task-list",
            ),
            pytest.param(group("parallel", task("a"), task("b")), id="direct-children"),
            pytest.param(
                group("parallel", task("a"), env={"MODE": "fast"}, on_error="continue"),
                id="direct-children-with-meta-fields",
            ),
            pytest.param(
                task(
                    "each",
                    prompt="Process {{loop.item.text}}",
                    loop={"type": "todo-list", "source": "todos.md"},
                ),
                id="loop-with-prompt",
            ),
            pytest.param(
                task("each", prompt=None, loop={"type": "glob", "pattern": "*.md"}),
                id="loop-without-prompt",
            ),
        ],
    )
    def test_valid_task_shapes(self, entry):
        assert validate_workflow(workflow(entry)) is True

    @pytest.mark.parametrize(
        "definition",
        [
            pytest.param({"on-error": "continue"}, id="on-error-only"),
            pytest.param({"prompt": ""}, id="empty-prompt"),
            pytest.param({"prompt": None}, id="null-prompt"),
            pytest.param({"task": []}, id="empty-task-list"),
            pytest.param({"directory": "/custom/path"}, id="directory-only"),
            pytest.param({"note": "a scalar is not a child task"}, id="scalar-field"),
            pytest.param({"env": {"MODE": "fast"}}, id="env"),
            pytest.param({"cli-agent-config": {"timeout": 60}}, id="cli-agent-config"),
            pytest.param({"validate": [{"file-exists": "out.md"}]}, id="validate"),
            pytest.param({"retry": {"max-attempts": 2}}, id="retry"),
            pytest.param({"skip-if": {"file-exists": "done.flag"}}, id="skip-if"),
            pytest.param({"include": ["use-intro"]}, id="include"),
            pytest.param({"when": "true"}, id="when"),
        ],
    )
    def test_task_without_prompt_or_children_is_rejected(self, definition):
        """Meta fields holding mappings or lists are not mistaken for child tasks."""
        assert_invalid(
            workflow({"bad-task": definition}),
            "Task with neither prompt nor nested tasks",
            "Task 'bad-task'",
        )

    @pytest.mark.parametrize(
        "where, location",
        [
            ("top-level", "task[0]"),
            ("nested", "task[0].parent.task[1]"),
            ("grouped", "task[0].parent[1]"),
        ],
    )
    def test_invalid_task_is_reported_with_its_location(self, where, location):
        wf = placed({"bad-child": {"on-error": "skip"}}, where)
        assert_invalid(wf, "Task with neither prompt", f"Task 'bad-child' at {location}")

    @pytest.mark.parametrize("where", ["top-level", "nested", "grouped"])
    def test_task_fields_are_validated_at_every_level(self, where):
        wf = placed(task("child", retry={"max-attempts": 0}), where)
        assert_invalid(wf, "'max-attempts' must be >= 1")

    @pytest.mark.parametrize(
        "entry, type_name", [("build", "str"), (42, "int"), (None, "NoneType")]
    )
    def test_task_list_entries_must_be_mappings(self, entry, type_name):
        assert_invalid(workflow(entry), "Task at task[0] must be a dict", f"got {type_name}")

    @pytest.mark.parametrize(
        "definition, type_name", [("Do the work", "str"), (42, "int"), (None, "NoneType")]
    )
    def test_task_definitions_must_be_mappings(self, definition, type_name):
        assert_invalid(
            workflow({"build": definition}),
            "Task definition for 'build'",
            "must be a dict",
            f"got {type_name}",
        )


class TestTaskDirectory:
    @pytest.mark.parametrize(
        "directory", ["/custom/path", "./subdir", "{{gitroot}}/subdir", "~/project"]
    )
    def test_string_directory_is_valid(self, directory):
        assert validate_workflow(workflow(task(directory=directory))) is True

    def test_nested_task_directory_is_valid(self):
        wf = workflow(task("parent", prompt=None, task=[task("child", directory="/child/dir")]))
        assert validate_workflow(wf) is True

    @pytest.mark.parametrize("value, type_name", [(123, "int"), (["/path1", "/path2"], "list")])
    def test_directory_must_be_a_string(self, value, type_name):
        assert_invalid(
            workflow(task(directory=value)),
            "Task 't'",
            "'directory' must be a string",
            f"got {type_name}",
        )


class TestTaskEnv:
    @pytest.mark.parametrize(
        "env",
        [
            pytest.param({"LOG_LEVEL": "debug", "BUILD_ID": "{{datetime}}"}, id="templated-values"),
            pytest.param({}, id="empty"),
            pytest.param({"PORT": 8080, "DEBUG": True}, id="non-string-values"),
        ],
    )
    def test_valid_task_env(self, env):
        assert validate_workflow(workflow(task(env=env))) is True

    @pytest.mark.parametrize(
        "value, type_name", [(["LOG_LEVEL=debug"], "list"), ("LOG_LEVEL=debug", "str")]
    )
    def test_env_must_be_a_mapping(self, value, type_name):
        assert_invalid(workflow(task(env=value)), "'env' must be a dict", f"got {type_name}")

    def test_env_keys_must_be_strings(self):
        assert_invalid(
            workflow(task(env={1: "one"})), "env variable key must be a string", "got int"
        )


class TestSkipIf:
    @pytest.mark.parametrize(
        "condition",
        [
            pytest.param({"file-exists": "deployed.flag"}, id="file-exists"),
            pytest.param(
                {"file-contains": {"path": "status.txt", "text": "VALIDATED"}}, id="file-contains"
            ),
        ],
    )
    def test_valid_conditions(self, condition):
        assert validate_workflow(workflow(task(skip_if=condition))) is True

    @pytest.mark.parametrize(
        "condition, fragments",
        [
            pytest.param(
                "deployed.flag",
                ("skip-if at task[0].t must be a dict", "got str"),
                id="not-a-mapping",
            ),
            pytest.param({}, ("exactly one condition", "got 0"), id="no-condition"),
            pytest.param(
                {"file-exists": "a.txt", "file-contains": {"path": "b.txt", "text": "x"}},
                ("exactly one condition", "got 2"),
                id="two-conditions",
            ),
            pytest.param(
                {"unknown-condition": "value"},
                ("invalid condition type 'unknown-condition'", "file-exists, file-contains"),
                id="unknown-type",
            ),
            pytest.param(
                {"file-exists": {"path": "a.txt"}},
                ("skip-if 'file-exists'", "requires string"),
                id="file-exists-not-a-string",
            ),
            pytest.param(
                {"file-contains": "VALIDATED"},
                ("skip-if 'file-contains'", "requires dict"),
                id="file-contains-not-a-mapping",
            ),
            pytest.param(
                {"file-contains": {"text": "VALIDATED"}},
                ("missing required field 'path'",),
                id="file-contains-without-path",
            ),
            pytest.param(
                {"file-contains": {"path": "status.txt"}},
                ("missing required field 'text'",),
                id="file-contains-without-text",
            ),
            pytest.param(
                {"file-contains": {"path": ["status.txt"], "text": "VALIDATED"}},
                ("field 'path' must be string",),
                id="file-contains-path-not-a-string",
            ),
            pytest.param(
                {"file-contains": {"path": "status.txt", "text": 42}},
                ("field 'text' must be string",),
                id="file-contains-text-not-a-string",
            ),
        ],
    )
    def test_invalid_conditions(self, condition, fragments):
        assert_invalid(workflow(task(skip_if=condition)), *fragments)


class TestWhen:
    @pytest.mark.parametrize("expression", ["{{env}} == 'production'", "not {{force}}", "true", ""])
    def test_string_expressions_are_valid(self, expression):
        assert validate_workflow(workflow(task(when=expression))) is True

    @pytest.mark.parametrize(
        "value, type_name",
        [({"expression": "{{env}} == 'production'"}, "dict"), (True, "bool"), (["a"], "list")],
    )
    def test_when_must_be_a_string(self, value, type_name):
        assert_invalid(
            workflow(task(when=value)), "when at task[0].t must be a string", f"got {type_name}"
        )


class TestValidate:
    def test_every_validator_type_is_accepted(self):
        validators = [
            {"file-exists": "out.md"},
            {"file-not-empty": "out.md"},
            {"json-valid": "out.json"},
            {"yaml-valid": "out.yaml"},
            {"contains": {"file": "out.md", "text": "## Summary"}},
            {"command": {"cmd": "make check"}},
            {"command": {"cmd": "python check.py {file}", "file": "out.md", "timeout": 120}},
        ]
        assert validate_workflow(workflow(task(validate=validators))) is True

    @pytest.mark.parametrize("timeout", [1, 0.5, 600])
    def test_command_timeout_accepts_positive_numbers(self, timeout):
        validators = [{"command": {"cmd": "make check", "timeout": timeout}}]
        assert validate_workflow(workflow(task(validate=validators))) is True

    @pytest.mark.parametrize("timeout", [0, -5, -0.5, True, False, "30"])
    def test_command_timeout_must_be_a_positive_number(self, timeout):
        validators = [{"command": {"cmd": "make check", "timeout": timeout}}]
        assert_invalid(
            workflow(task(validate=validators)),
            "Validator 'command'",
            "field 'timeout' must be a positive number",
            f"got {timeout!r}",
        )

    @pytest.mark.parametrize("kind", ["file-exists", "file-not-empty", "json-valid", "yaml-valid"])
    @pytest.mark.parametrize(
        "value, type_name", [({"path": "out.md"}, "dict"), (["out.md"], "list"), (None, "NoneType")]
    )
    def test_file_validators_require_a_path_string(self, kind, value, type_name):
        assert_invalid(
            workflow(task(validate=[{kind: value}])),
            f"Validator '{kind}'",
            "requires string (file path)",
            f"got {type_name}",
        )

    @pytest.mark.parametrize(
        "validators, fragments",
        [
            pytest.param(
                {"file-exists": "out.md"},
                ("Validators at task[0].t must be a list", "got dict"),
                id="not-a-list",
            ),
            pytest.param([], ("Validators at task[0].t cannot be empty",), id="empty-list"),
            pytest.param(
                ["file-exists"],
                ("Validator at task[0].t[0] must be a dict", "got str"),
                id="entry-not-a-mapping",
            ),
            pytest.param([{}], ("exactly one key", "got 0"), id="entry-without-type"),
            pytest.param(
                [{"file-exists": "out.md", "json-valid": "out.json"}],
                ("exactly one key", "got 2"),
                id="entry-with-two-types",
            ),
            pytest.param(
                [{"file-missing": "out.md"}],
                (
                    "invalid type 'file-missing'",
                    "file-exists, file-not-empty, contains, json-valid, yaml-valid, command",
                ),
                id="unknown-type",
            ),
            pytest.param(
                [{"contains": "## Summary"}],
                ("Validator 'contains'", "requires dict"),
                id="contains-not-a-mapping",
            ),
            pytest.param(
                [{"contains": {"text": "## Summary"}}],
                ("Validator 'contains'", "missing required field 'file'"),
                id="contains-without-file",
            ),
            pytest.param(
                [{"contains": {"file": "out.md"}}],
                ("Validator 'contains'", "missing required field 'text'"),
                id="contains-without-text",
            ),
            pytest.param(
                [{"contains": {"file": ["out.md"], "text": "## Summary"}}],
                ("Validator 'contains'", "field 'file' must be string"),
                id="contains-file-not-a-string",
            ),
            pytest.param(
                [{"contains": {"file": "out.md", "text": 42}}],
                ("Validator 'contains'", "field 'text' must be string"),
                id="contains-text-not-a-string",
            ),
            pytest.param(
                [{"command": "make check"}],
                ("Validator 'command'", "requires dict"),
                id="command-not-a-mapping",
            ),
            pytest.param(
                [{"command": {"file": "out.md"}}],
                ("Validator 'command'", "missing required field 'cmd'"),
                id="command-without-cmd",
            ),
            pytest.param(
                [{"command": {"cmd": ["make", "check"]}}],
                ("Validator 'command'", "field 'cmd' must be string"),
                id="command-cmd-not-a-string",
            ),
            pytest.param(
                [{"command": {"cmd": "make check", "file": 1}}],
                ("Validator 'command'", "field 'file' must be string"),
                id="command-file-not-a-string",
            ),
            pytest.param(
                [{"file-exists": "out.md"}, {"command": {}}],
                ("Validator 'command' at task[0].t[1]", "missing required field 'cmd'"),
                id="second-entry",
            ),
        ],
    )
    def test_invalid_validate_config(self, validators, fragments):
        assert_invalid(workflow(task(validate=validators)), *fragments)


class TestRetry:
    @pytest.mark.parametrize(
        "retry",
        [
            pytest.param({"max-attempts": 3, "on-validation-failure": "retry"}, id="both-fields"),
            pytest.param({"max-attempts": 1}, id="single-attempt"),
            pytest.param({"on-validation-failure": "skip"}, id="skip"),
            pytest.param({"on-validation-failure": "fail"}, id="fail"),
        ],
    )
    def test_valid_retry_config(self, retry):
        assert validate_workflow(workflow(task(retry=retry))) is True

    @pytest.mark.parametrize(
        "retry, fragments",
        [
            pytest.param(
                3,
                ("Retry configuration at task[0].t must be a dict", "got int"),
                id="not-a-mapping",
            ),
            pytest.param(
                {"max-attempts": "3"},
                ("'max-attempts' must be an integer", "got str"),
                id="attempts-string",
            ),
            pytest.param(
                {"max-attempts": 2.5},
                ("'max-attempts' must be an integer", "got float"),
                id="attempts-float",
            ),
            pytest.param(
                {"max-attempts": 0}, ("'max-attempts' must be >= 1", "got 0"), id="attempts-zero"
            ),
            pytest.param(
                {"max-attempts": -2},
                ("'max-attempts' must be >= 1", "got -2"),
                id="attempts-negative",
            ),
            pytest.param(
                {"on-validation-failure": 1},
                ("'on-validation-failure' must be a string", "got int"),
                id="strategy-not-a-string",
            ),
            pytest.param(
                {"on-validation-failure": "ignore"},
                (
                    "'on-validation-failure' must be one of",
                    "'retry'",
                    "'skip'",
                    "'fail'",
                    "got 'ignore'",
                ),
                id="unknown-strategy",
            ),
            pytest.param(
                {"max-attempts": 2, "delay": 5},
                ("unknown field 'delay'", "max-attempts", "on-validation-failure"),
                id="unknown-field",
            ),
            pytest.param(
                {"max_attempts": 2}, ("unknown field 'max_attempts'",), id="misspelled-field"
            ),
        ],
    )
    def test_invalid_retry_config(self, retry, fragments):
        assert_invalid(workflow(task(retry=retry)), *fragments)


class TestLoopConfig:
    @pytest.mark.parametrize(
        "loop",
        [
            {"type": "todo-list", "source": "todos.md"},
            {"type": "csv", "source": "users.csv"},
            {"type": "glob", "pattern": "agent_yaml/**/*.py"},
            {"type": "json", "source": "users.json"},
            {"type": "jsonl", "source": "events.jsonl"},
        ],
        ids=lambda loop: loop["type"],
    )
    def test_each_loop_type_is_accepted(self, loop):
        assert validate_workflow(workflow(task(loop=loop))) is True

    @pytest.mark.parametrize("loop, type_name", [("csv", "str"), (["csv"], "list")])
    def test_loop_must_be_a_mapping(self, loop, type_name):
        assert_invalid(
            workflow(task(loop=loop)),
            "Loop configuration at task[0].t must be a dict",
            f"got {type_name}",
        )

    @pytest.mark.parametrize(
        "loop", [{"source": "users.csv"}, {"type": "", "source": "users.csv"}, {"type": None}]
    )
    def test_loop_type_is_required(self, loop):
        assert_invalid(workflow(task(loop=loop)), "missing required field 'type'")

    def test_unknown_loop_type_lists_the_valid_types(self):
        assert_invalid(
            loop_workflow(type="yaml", source="items.yaml"),
            "invalid type 'yaml'",
            "'todo-list'",
            "'csv'",
            "'glob'",
            "'json'",
            "'jsonl'",
        )

    @pytest.mark.parametrize("workers", [1, 4])
    def test_workers_accepts_positive_integers(self, workers):
        wf = loop_workflow(type="csv", source="users.csv", workers=workers)
        assert validate_workflow(wf) is True

    @pytest.mark.parametrize(
        "workers, type_name", [("three", "str"), (2.0, "float"), (None, "NoneType")]
    )
    def test_workers_must_be_an_integer(self, workers, type_name):
        assert_invalid(
            loop_workflow(type="csv", source="users.csv", workers=workers),
            "'workers' must be an integer",
            f"got {type_name}",
        )

    @pytest.mark.parametrize("workers", [0, -2])
    def test_workers_must_be_at_least_one(self, workers):
        assert_invalid(
            loop_workflow(type="csv", source="users.csv", workers=workers),
            "'workers' must be >= 1",
            f"got {workers}",
        )

    def test_directory_pool_of_strings_is_valid(self):
        wf = loop_workflow(
            type="csv",
            source="users.csv",
            workers=2,
            directory_pool=["/tmp/dir1", "{{gitroot}}/dir2"],
        )
        assert validate_workflow(wf) is True

    @pytest.mark.parametrize(
        "pool, fragments",
        [
            pytest.param(
                "/tmp/dir1", ("'directory-pool' must be a list", "got str"), id="not-a-list"
            ),
            pytest.param([], ("'directory-pool' cannot be empty",), id="empty"),
            pytest.param(
                ["/tmp/dir1", 3],
                ("'directory-pool[1]' must be a string", "got int"),
                id="non-string-entry",
            ),
        ],
    )
    def test_invalid_directory_pool(self, pool, fragments):
        wf = loop_workflow(type="csv", source="users.csv", workers=2, directory_pool=pool)
        assert_invalid(wf, *fragments)

    @pytest.mark.parametrize(
        "git_worktrees",
        [
            pytest.param(
                {
                    "enabled": True,
                    "base": ".worktrees",
                    "branch-field": "branch",
                    "name-template": "worker-{{loop.worker.id}}",
                    "cleanup": True,
                },
                id="all-fields",
            ),
            pytest.param(
                {"enabled": True, "branch-field": "branch", "cleanup": False}, id="cleanup-off"
            ),
            pytest.param({"enabled": True, "branch-field": "branch"}, id="cleanup-omitted"),
        ],
    )
    def test_valid_git_worktrees(self, git_worktrees):
        wf = loop_workflow(
            type="csv", source="branches.csv", workers=2, git_worktrees=git_worktrees
        )
        assert validate_workflow(wf) is True

    @pytest.mark.parametrize(
        "git_worktrees, fragment",
        [
            pytest.param("enabled", "'git-worktrees' must be a dict", id="not-a-mapping"),
            pytest.param({"enabled": 1}, "'git-worktrees.enabled' must be a boolean", id="enabled"),
            pytest.param({"base": 1}, "'git-worktrees.base' must be a string", id="base"),
            pytest.param(
                {"branch-field": ["branch"]},
                "'git-worktrees.branch-field' must be a string",
                id="branch-field",
            ),
            pytest.param(
                {"name-template": 5},
                "'git-worktrees.name-template' must be a string",
                id="name-template",
            ),
            pytest.param(
                {"cleanup": "always"}, "'git-worktrees.cleanup' must be a boolean", id="cleanup"
            ),
        ],
    )
    def test_invalid_git_worktrees(self, git_worktrees, fragment):
        wf = loop_workflow(
            type="csv", source="branches.csv", workers=2, git_worktrees=git_worktrees
        )
        assert_invalid(wf, fragment)

    def test_directory_pool_and_git_worktrees_are_exclusive(self):
        wf = loop_workflow(
            type="csv",
            source="branches.csv",
            workers=2,
            directory_pool=["/tmp/dir1"],
            git_worktrees={"enabled": True, "branch-field": "branch"},
        )
        assert_invalid(wf, "Cannot use both 'directory-pool' and 'git-worktrees'")


class TestJsonLoopConfig:
    @pytest.mark.parametrize("loop_type", ["json", "jsonl"])
    def test_source_is_required(self, loop_type):
        assert_invalid(loop_workflow(type=loop_type), "'source' field is required")

    @pytest.mark.parametrize("loop_type", ["json", "jsonl"])
    def test_source_must_be_a_string(self, loop_type):
        assert_invalid(
            loop_workflow(type=loop_type, source=["users.json"]),
            "'source' must be a string",
            "got list",
        )

    def test_json_path_is_accepted(self):
        wf = loop_workflow(type="json", source="org.json", path="organization.teams.engineering")
        assert validate_workflow(wf) is True

    def test_json_path_must_be_a_string(self):
        assert_invalid(
            loop_workflow(type="json", source="org.json", path=["organization"]),
            "'path' must be a string",
            "got list",
        )

    def test_jsonl_rejects_path(self):
        assert_invalid(
            loop_workflow(type="jsonl", source="events.jsonl", path="data"),
            "'path' field not supported for jsonl",
        )

    @pytest.mark.parametrize(
        "loop_filter",
        [
            pytest.param({"key": "status", "value": "active"}, id="simple"),
            pytest.param({"key": "user.level", "value": 3}, id="simple-non-string-value"),
            pytest.param(
                {
                    "conditions": [
                        {"key": "status", "value": "active"},
                        {"key": "priority", "value": "high"},
                    ]
                },
                id="conditions-default-operator",
            ),
            pytest.param(
                {"conditions": [{"key": "status", "value": "active"}], "operator": "AND"},
                id="conditions-and",
            ),
            pytest.param(
                {
                    "conditions": [
                        {"key": "priority", "value": "high"},
                        {"key": "priority", "value": "critical"},
                    ],
                    "operator": "OR",
                },
                id="conditions-or",
            ),
        ],
    )
    @pytest.mark.parametrize("loop_type", ["json", "jsonl"])
    def test_valid_filters(self, loop_type, loop_filter):
        wf = loop_workflow(type=loop_type, source=f"items.{loop_type}", filter=loop_filter)
        assert validate_workflow(wf) is True

    @pytest.mark.parametrize(
        "loop_filter, fragments",
        [
            pytest.param(
                ["status", "active"], ("'filter' must be a dict", "got list"), id="not-a-mapping"
            ),
            pytest.param(
                {
                    "key": "status",
                    "value": "active",
                    "conditions": [{"key": "priority", "value": "high"}],
                },
                ("Cannot mix simple filter (key/value) with multiple conditions",),
                id="simple-and-conditions",
            ),
            pytest.param(
                {"key": 1, "value": "active"},
                ("filter.key must be a string", "got int"),
                id="simple-key-not-a-string",
            ),
            pytest.param(
                {"conditions": []}, ("'conditions' must be non-empty list",), id="conditions-empty"
            ),
            pytest.param(
                {"conditions": {"key": "status", "value": "active"}},
                ("'conditions' must be non-empty list",),
                id="conditions-not-a-list",
            ),
            pytest.param(
                {"conditions": ["status=active"]},
                ("conditions[0] must be a dict", "got str"),
                id="condition-not-a-mapping",
            ),
            pytest.param(
                {"conditions": [{"key": "status", "value": "active"}, {"key": "priority"}]},
                ("conditions[1] must have 'key' and 'value' fields",),
                id="condition-without-value",
            ),
            pytest.param(
                {"conditions": [{"value": "active"}]},
                ("conditions[0] must have 'key' and 'value' fields",),
                id="condition-without-key",
            ),
            pytest.param(
                {"conditions": [{"key": 7, "value": "active"}]},
                ("conditions[0].key must be a string", "got int"),
                id="condition-key-not-a-string",
            ),
            pytest.param(
                {"conditions": [{"key": "status", "value": "active"}], "operator": "XOR"},
                ("operator must be 'AND' or 'OR'", "got 'XOR'"),
                id="unknown-operator",
            ),
            pytest.param(
                {"conditions": [{"key": "status", "value": "active"}], "operator": "or"},
                ("operator must be 'AND' or 'OR'", "got 'or'"),
                id="lowercase-operator",
            ),
        ],
    )
    @pytest.mark.parametrize("loop_type", ["json", "jsonl"])
    def test_invalid_filters(self, loop_type, loop_filter, fragments):
        wf = loop_workflow(type=loop_type, source=f"items.{loop_type}", filter=loop_filter)
        assert_invalid(wf, *fragments)
