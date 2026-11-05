"""Unit tests for agent_yaml/utils.py: interpolate_variables (prompt templates) and evaluate_expression."""

import pytest
from jinja2 import TemplateSyntaxError

from agent_yaml.utils import evaluate_expression, interpolate_variables

IF_ELSE = "{% if value %}YES{% else %}NO{% endif %}"
LEVELS = "{% if level == 'high' %}HIGH{% elif level == 'medium' %}MEDIUM{% else %}LOW{% endif %}"
AND = "{% if a and b %}BOTH{% else %}NOT BOTH{% endif %}"
OR = "{% if a or b %}AT LEAST ONE{% else %}NEITHER{% endif %}"
NOT = "{% if not disabled %}ENABLED{% else %}DISABLED{% endif %}"
NESTED = "{% if outer %}{% if inner %}BOTH{% else %}OUTER ONLY{% endif %}{% else %}NONE{% endif %}"
PR = "{% if pr_number %}PR #{{pr_number}}{% else %}All PRs{% endif %}"
FOR_ELSE = "{% for item in items %}{{item}}{% else %}No items{% endfor %}"


class TestSimpleInterpolation:
    """Templates with only {{name}} placeholders: regex substitution, hyphens and dots allowed."""

    @pytest.mark.parametrize(
        "template, variables, expected",
        [
            pytest.param("Hello {{name}}", {"name": "World"}, "Hello World", id="single"),
            pytest.param(
                "{{greeting}} {{name}}!",
                {"greeting": "Hello", "name": "World"},
                "Hello World!",
                id="multiple",
            ),
            pytest.param("{{ name }}", {"name": "World"}, "World", id="spaces-inside-braces"),
            pytest.param("{{base-var}}-ext", {"base-var": "value"}, "value-ext", id="hyphenated"),
            pytest.param(
                "{{loop.index}}: {{loop.item.text}}",
                {"loop": {"index": 0, "item": {"text": "task"}}},
                "0: task",
                id="dot-access",
            ),
            pytest.param("{{a.b.c.d}}", {"a": {"b": {"c": {"d": "deep"}}}}, "deep", id="deep-dots"),
            pytest.param("Count: {{count}}", {"count": 42}, "Count: 42", id="int"),
            pytest.param("Enabled: {{enabled}}", {"enabled": True}, "Enabled: True", id="bool"),
            pytest.param("Hello {{undefined}}", {}, "Hello ", id="undefined-is-empty"),
            pytest.param("{{a.b.c}}", {"a": {}}, "", id="undefined-nested-is-empty"),
            pytest.param("Plain text", {}, "Plain text", id="no-placeholders"),
            pytest.param("", {"name": "value"}, "", id="empty-template"),
        ],
    )
    def test_substitution(self, template, variables, expected):
        assert interpolate_variables(template, variables) == expected

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("Use {something} for this", id="single-braces"),
            pytest.param("This { is fine and so is this }", id="lone-single-braces"),
            pytest.param("Process }} without opening", id="lone-closing-braces"),
            pytest.param('{"key": {"nested": 1}}', id="json"),
        ],
    )
    def test_brace_text_that_is_not_a_placeholder_passes_through(self, text):
        assert interpolate_variables(text, {"something": "x", "key": "x"}) == text


class TestEnvNamespace:
    """{{env.NAME}} reads the merged environment dict stored under the reserved `env` variable."""

    @pytest.mark.parametrize(
        "template, env, expected",
        [
            pytest.param("Value: {{env.GREETING}}", {"GREETING": "hi"}, "Value: hi", id="single"),
            pytest.param(
                "{{env.VAR1}} and {{env.VAR2}}",
                {"VAR1": "one", "VAR2": "two"},
                "one and two",
                id="multiple",
            ),
            pytest.param("{{env.WITH_UNDERSCORES}}", {"WITH_UNDERSCORES": "ok"}, "ok", id="names"),
            pytest.param("{{env.HOME}}/x", {"HOME": "/home/tester"}, "/home/tester/x", id="home"),
            pytest.param("{{env.PATH}}", {"PATH": "/usr/bin:/bin"}, "/usr/bin:/bin", id="colons"),
            pytest.param("{{env.SPECIAL}}", {"SPECIAL": "a b & c!"}, "a b & c!", id="specials"),
            pytest.param("{{env.KEY_VALUE}}", {"KEY_VALUE": "key=value"}, "key=value", id="equals"),
            pytest.param("{{env.LINES}}", {"LINES": "line1\nline2"}, "line1\nline2", id="newline"),
            pytest.param("START_{{env.MID}}_END", {"MID": "MID"}, "START_MID_END", id="surrounded"),
            pytest.param("Value: {{env.NOT_DEFINED}}", {}, "Value: ", id="undefined-is-empty"),
            pytest.param("{{ env.MODE | default('dev') }}", {}, "dev", id="default-filter"),
            pytest.param("{% if env.CI %}ci{% else %}local{% endif %}", {"CI": "1"}, "ci", id="if"),
        ],
    )
    def test_env_lookup(self, template, env, expected):
        assert interpolate_variables(template, {"env": env}) == expected

    def test_env_mixes_with_other_variables(self):
        variables = {"gitroot": "/repo", "env": {"SUFFIX": "test"}}
        assert interpolate_variables("{{gitroot}}/{{env.SUFFIX}}", variables) == "/repo/test"


class TestConditionals:
    @pytest.mark.parametrize(
        "variables, expected",
        [
            pytest.param({"value": True}, "YES", id="true"),
            pytest.param({"value": False}, "NO", id="false"),
            pytest.param({"value": "123"}, "YES", id="non-empty-string"),
            pytest.param({"value": ""}, "NO", id="empty-string"),
            pytest.param({"value": None}, "NO", id="none"),
            pytest.param({"value": 0}, "NO", id="zero"),
            pytest.param({"value": []}, "NO", id="empty-list"),
            pytest.param({}, "NO", id="undefined"),
        ],
    )
    def test_if_uses_python_truthiness(self, variables, expected):
        assert interpolate_variables(IF_ELSE, variables) == expected

    @pytest.mark.parametrize("debug, expected", [(True, "DEBUG MODE"), (False, "")])
    def test_if_without_else(self, debug, expected):
        template = "{% if debug %}DEBUG MODE{% endif %}"
        assert interpolate_variables(template, {"debug": debug}) == expected

    @pytest.mark.parametrize(
        "template, variables, expected",
        [
            pytest.param(LEVELS, {"level": "high"}, "HIGH", id="if"),
            pytest.param(LEVELS, {"level": "medium"}, "MEDIUM", id="elif"),
            pytest.param(LEVELS, {"level": "low"}, "LOW", id="else"),
            pytest.param(AND, {"a": True, "b": True}, "BOTH", id="and-both"),
            pytest.param(AND, {"a": True, "b": False}, "NOT BOTH", id="and-left-only"),
            pytest.param(AND, {"a": False, "b": True}, "NOT BOTH", id="and-right-only"),
            pytest.param(OR, {"a": True, "b": False}, "AT LEAST ONE", id="or-left"),
            pytest.param(OR, {"a": False, "b": True}, "AT LEAST ONE", id="or-right"),
            pytest.param(OR, {"a": False, "b": False}, "NEITHER", id="or-neither"),
            pytest.param(NOT, {"disabled": False}, "ENABLED", id="not-false"),
            pytest.param(NOT, {"disabled": True}, "DISABLED", id="not-true"),
            pytest.param(NESTED, {"outer": True, "inner": True}, "BOTH", id="nested-both"),
            pytest.param(NESTED, {"outer": True, "inner": False}, "OUTER ONLY", id="nested-outer"),
            pytest.param(NESTED, {"outer": False, "inner": True}, "NONE", id="nested-none"),
            pytest.param(PR, {"pr_number": "123"}, "PR #123", id="value-in-branch"),
            pytest.param(PR, {"pr_number": ""}, "All PRs", id="empty-value-else"),
        ],
    )
    def test_branch_selection(self, template, variables, expected):
        assert interpolate_variables(template, variables) == expected


class TestFilters:
    @pytest.mark.parametrize(
        "template, variables, expected",
        [
            pytest.param("{{value | default('none')}}", {}, "none", id="default-undefined"),
            pytest.param(
                "{{value | default('none')}}", {"value": "actual"}, "actual", id="default-set"
            ),
            pytest.param(
                "{{value | default('none')}}", {"value": ""}, "", id="default-keeps-empty"
            ),
            pytest.param(
                "{{value | default('none', true)}}", {"value": ""}, "none", id="default-boolean"
            ),
            pytest.param("{{name | upper}}", {"name": "hello"}, "HELLO", id="upper"),
            pytest.param("{{name | lower}}", {"name": "HELLO"}, "hello", id="lower"),
            pytest.param("{{name | capitalize}}", {"name": "hello"}, "Hello", id="capitalize"),
            pytest.param("{{name | title}}", {"name": "hello world"}, "Hello World", id="title"),
            pytest.param("{{name | trim}}", {"name": "  hello  "}, "hello", id="trim"),
            pytest.param("{{items | length}}", {"items": [1, 2, 3]}, "3", id="length"),
            pytest.param(
                "{{text | replace('world', 'universe')}}",
                {"text": "hello world"},
                "hello universe",
                id="replace",
            ),
            pytest.param("{{name | trim | upper}}", {"name": "  hello  "}, "HELLO", id="chained"),
            pytest.param(
                "{{undefined | default('fallback') | upper}}",
                {},
                "FALLBACK",
                id="chained-undefined",
            ),
        ],
    )
    def test_filter(self, template, variables, expected):
        assert interpolate_variables(template, variables) == expected

    @pytest.mark.parametrize(
        "template, expected",
        [
            pytest.param("{% if flag %}{{ v['my-var'] }}{% endif %}", "value", id="in-block"),
            pytest.param("{{ v['my-var'] | upper }}", "VALUE", id="with-filter"),
        ],
    )
    def test_v_namespace_reaches_hyphenated_names_in_jinja2_templates(self, template, expected):
        assert interpolate_variables(template, {"flag": True, "my-var": "value"}) == expected


class TestLoops:
    @pytest.mark.parametrize(
        "template, variables, expected",
        [
            pytest.param(
                "{% for item in items %}{{item}} {% endfor %}",
                {"items": ["a", "b", "c"]},
                "a b c ",
                id="simple",
            ),
            pytest.param(
                "{% for item in items %}{{loop.index}}.{{item}} {% endfor %}",
                {"items": ["a", "b"]},
                "1.a 2.b ",
                id="loop-index",
            ),
            pytest.param(
                "{% for item in items %}{{loop.index0}}:{{item}} {% endfor %}",
                {"items": ["a", "b"]},
                "0:a 1:b ",
                id="loop-index0",
            ),
            pytest.param(
                "{% for item in items %}{{item}}{% endfor %}", {"items": []}, "", id="empty-list"
            ),
            pytest.param(FOR_ELSE, {"items": ["a"]}, "a", id="for-else-with-items"),
            pytest.param(FOR_ELSE, {"items": []}, "No items", id="for-else-empty"),
            pytest.param(
                "{% for row in rows %}{% for col in row %}{{col}}{% endfor %} {% endfor %}",
                {"rows": [[1, 2], [3, 4]]},
                "12 34 ",
                id="nested",
            ),
        ],
    )
    def test_for_loop(self, template, variables, expected):
        assert interpolate_variables(template, variables) == expected


class TestCommentsAndWhitespace:
    @pytest.mark.parametrize(
        "template, expected",
        [
            pytest.param("Hello {# this is a comment #}World", "Hello World", id="comment"),
            pytest.param(
                "Before{# \ncomment\nspanning\nlines\n#}After",
                "BeforeAfter",
                id="multiline-comment",
            ),
            pytest.param(
                "{% if True %}\nContent\n{% endif %}\nAfter", "Content\nAfter", id="trim-blocks"
            ),
            pytest.param("    {% if True %}yes{% endif %}", "yes", id="lstrip-blocks"),
            pytest.param("A {{- ' B ' -}} C", "A B C", id="minus-whitespace-control"),
        ],
    )
    def test_rendering(self, template, expected):
        assert interpolate_variables(template, {}) == expected


class TestSyntaxErrors:
    @pytest.mark.parametrize(
        "template",
        [
            pytest.param("{% if debug %}DEBUG", id="unclosed-if"),
            pytest.param("{% for item in items %}{{item}}", id="unclosed-for"),
            pytest.param("{% if debug %}DEBUG{% endfor %}", id="mismatched-end-tag"),
            pytest.param("Some text {% endif %}", id="endif-without-if"),
            pytest.param("Some text {% else %} other", id="else-without-if"),
            pytest.param("Hello {# this is unclosed", id="unclosed-comment"),
        ],
    )
    def test_malformed_block_syntax_raises(self, template):
        with pytest.raises(TemplateSyntaxError):
            interpolate_variables(template, {"debug": True, "items": []})


class TestRealWorldTemplates:
    def test_pr_number_switches_between_single_pr_and_discovery_mode(self):
        template = (
            "{% if pr_number %}\n"
            "# Single PR mode\n"
            "gh pr view {{pr_number}} --repo org/repo\n"
            "{% else %}\n"
            "# Discovery mode\n"
            "gh pr list --repo org/repo\n"
            "{% endif %}"
        )

        assert (
            interpolate_variables(template, {"pr_number": "123"})
            == "# Single PR mode\ngh pr view 123 --repo org/repo\n"
        )
        assert (
            interpolate_variables(template, {"pr_number": ""})
            == "# Discovery mode\ngh pr list --repo org/repo\n"
        )

    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("production", "Deploy with caution: api\n"),
            ("staging", "Staging deployment: api\n"),
            ("dev", "Dev deployment: api\n"),
        ],
    )
    def test_environment_based_config(self, environment, expected):
        template = (
            "{% if environment == 'production' %}\n"
            "Deploy with caution: {{service}}\n"
            "{% elif environment == 'staging' %}\n"
            "Staging deployment: {{service}}\n"
            "{% else %}\n"
            "Dev deployment: {{service}}\n"
            "{% endif %}"
        )
        variables = {"environment": environment, "service": "api"}
        assert interpolate_variables(template, variables) == expected

    def test_optional_config_lines(self):
        template = (
            "cli-agent: claude\n"
            "{% if mcp_config %}mcp-config: {{mcp_config}}{% endif %}\n"
            "{% if additional_dirs %}additional-dirs: {{additional_dirs}}{% endif %}"
        )
        variables = {"mcp_config": "/path/to/mcp.json", "additional_dirs": ""}

        assert (
            interpolate_variables(template, variables)
            == "cli-agent: claude\nmcp-config: /path/to/mcp.json"
        )

    def test_multiline_prompt_with_conditionals(self):
        template = (
            "Analyze the following:\n"
            "{% if include_tests %}\n"
            "Include test files in analysis.\n"
            "{% endif %}\n"
            "{% if verbose %}\n"
            "Provide detailed explanations.\n"
            "{% else %}\n"
            "Be concise.\n"
            "{% endif %}\n"
            "Focus on: {{focus_area}}"
        )
        variables = {"include_tests": True, "verbose": False, "focus_area": "security"}

        assert interpolate_variables(template, variables) == (
            "Analyze the following:\n"
            "Include test files in analysis.\n"
            "Be concise.\n"
            "Focus on: security"
        )

    def test_list_generation_with_for(self):
        template = "Files to process:\n{% for file in files %}\n- {{file}}\n{% endfor %}"
        variables = {"files": ["main.py", "test.py", "utils.py"]}

        assert (
            interpolate_variables(template, variables)
            == "Files to process:\n- main.py\n- test.py\n- utils.py\n"
        )


class TestEvaluateExpression:
    @pytest.mark.parametrize(
        "expression, variables, expected",
        [
            pytest.param("{{env}} == 'production'", {"env": "production"}, True, id="eq-true"),
            pytest.param("{{env}} == 'production'", {"env": "staging"}, False, id="eq-false"),
            pytest.param("{{env}} != 'ci'", {"env": "production"}, True, id="ne-true"),
            pytest.param("{{env}} != 'ci'", {"env": "ci"}, False, id="ne-false"),
            pytest.param("{{a}} and {{b}}", {"a": True, "b": True}, True, id="and-both"),
            pytest.param("{{a}} and {{b}}", {"a": True, "b": False}, False, id="and-one"),
            pytest.param("{{a}} and {{b}}", {"a": False, "b": False}, False, id="and-neither"),
            pytest.param("{{a}} or {{b}}", {"a": True, "b": False}, True, id="or-one"),
            pytest.param("{{a}} or {{b}}", {"a": True, "b": True}, True, id="or-both"),
            pytest.param("{{a}} or {{b}}", {"a": False, "b": False}, False, id="or-neither"),
            pytest.param("not {{skip}}", {"skip": False}, True, id="not-false"),
            pytest.param("not {{skip}}", {"skip": True}, False, id="not-true"),
            pytest.param(
                "{{a}} == 'x' or {{b}} == 'y'", {"a": "z", "b": "y"}, True, id="mixed-operators"
            ),
            pytest.param("{{count}} > 0", {"count": 5}, True, id="gt"),
            pytest.param("{{count}} < 10", {"count": 5}, True, id="lt"),
            pytest.param("{{count}} >= 5", {"count": 5}, True, id="ge"),
            pytest.param("{{count}} <= 5", {"count": 5}, True, id="le"),
            pytest.param("True", {}, True, id="true-literal"),
            pytest.param("False", {}, False, id="false-literal"),
            pytest.param("'prod' in {{env}}", {"env": "production"}, True, id="in"),
            pytest.param("'test' not in {{env}}", {"env": "production"}, True, id="not-in"),
            pytest.param(
                "{{env}} == 'prod' and {{tests-pass}} and not {{skip}}",
                {"env": "prod", "tests-pass": True, "skip": False},
                True,
                id="complex",
            ),
            pytest.param("{{tests-pass}} == True", {"tests-pass": True}, True, id="hyphenated"),
            pytest.param(
                "{{loop.item.text}} == 'x'",
                {"loop": {"item": {"text": "x"}}},
                True,
                id="dotted-path",
            ),
            pytest.param("", {}, False, id="empty-expression"),
            pytest.param(None, {}, False, id="none-expression"),
            pytest.param("{{a}} ==", {"a": 1}, False, id="invalid-syntax"),
        ],
    )
    def test_boolean_result(self, expression, variables, expected):
        assert evaluate_expression(expression, variables) is expected

    def test_undefined_variable_is_falsy_not_an_error(self):
        assert not evaluate_expression("{{undefined}}", {})

    @pytest.mark.parametrize(
        "expression, variables, expected",
        [
            pytest.param("{{n}} * 2", {"n": 21}, 42, id="arithmetic"),
            pytest.param("{{name}}", {"name": "abc"}, "abc", id="string"),
        ],
    )
    def test_returns_native_values(self, expression, variables, expected):
        result = evaluate_expression(expression, variables)
        assert result == expected
        assert type(result) is type(expected)
