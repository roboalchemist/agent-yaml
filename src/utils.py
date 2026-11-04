"""
Utility functions for agent-yaml.

Provides common helper functions used across modules:
- Path resolution (absolute, relative, tilde expansion)
- Template variable interpolation (full Jinja2 support with backward compatibility)
- Git repository detection
- Error formatting and logging helpers
"""

import re
from jinja2 import Environment, BaseLoader, Undefined
from jinja2.nativetypes import NativeEnvironment


class SilentUndefined(Undefined):
    """
    Custom undefined class that returns empty string and is falsy.

    This allows:
    - {% if undefined_var %} to evaluate as False
    - {{undefined_var}} to render as empty string (not error)
    - {{undefined_var | default('fallback')}} to work correctly

    Inherits from Jinja2's Undefined to maintain compatibility with
    the Environment.undefined parameter.
    """

    def __str__(self):
        return ""

    def __repr__(self):
        return ""

    def __bool__(self):
        return False

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0

    def __eq__(self, other):
        return isinstance(other, Undefined) or other == "" or other is None

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash("")

    def _fail_with_undefined_error(self, *args, **kwargs):
        """Override to return empty string instead of raising."""
        return ""


# Create a Jinja2 environment with silent undefined for graceful handling
_jinja_env = Environment(
    loader=BaseLoader(),
    undefined=SilentUndefined,
    # Keep whitespace control for cleaner output in prompts
    trim_blocks=True,
    lstrip_blocks=True,
)

# Create a NativeEnvironment for expression evaluation
# NativeEnvironment evaluates to native Python types (bool, int, etc.)
# instead of always returning strings, which is needed for `when` conditions
_native_env = NativeEnvironment(
    loader=BaseLoader(),
    undefined=SilentUndefined,
)


def _has_jinja2_features(template_string):
    """
    Check if template uses advanced Jinja2 features.

    Returns True if the template contains:
    - Block statements: {% if %}, {% for %}, etc.
    - Filters: {{ var | filter }}
    - Comments: {# comment #}
    - Whitespace control: {{- -}}, {%- -%}

    Args:
        template_string: Template to check

    Returns:
        bool: True if advanced Jinja2 features are detected
    """
    # Check for block statements
    if "{%" in template_string:
        return True

    # Check for comments
    if "{#" in template_string:
        return True

    # Check for whitespace control syntax
    if "{{-" in template_string or "-}}" in template_string:
        return True

    # Check for filters (| inside {{ }})
    # Pattern: {{...| (with pipe inside expression)
    filter_pattern = r"\{\{[^}]*\|[^}]*\}\}"
    if re.search(filter_pattern, template_string):
        return True

    return False


def _simple_interpolate(template_string, variables):
    """
    Simple regex-based variable interpolation for backward compatibility.

    Supports:
    - Simple variables: {{var}}
    - Nested access: {{loop.item.text}}
    - Variable names with hyphens: {{var-name}}

    This is the original interpolation method that handles edge cases
    Jinja2 doesn't support (like hyphenated variable names).

    Args:
        template_string: String containing {{var}} placeholders
        variables: Dict of variable names to values (can be nested)

    Returns:
        str: String with variables substituted
    """
    # Pattern to match {{var}} or {{var.nested.path}} or {{var-with-hyphens}}
    pattern = r"\{\{([^}]+)\}\}"

    def replace_variable(match):
        var_path = match.group(1).strip()

        # Split on dots for nested access
        parts = var_path.split(".")

        # Navigate through nested dict
        value = variables
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                # Variable not found, return empty string
                return ""

        # Convert value to string
        return str(value)

    return re.sub(pattern, replace_variable, template_string)


def interpolate_variables(template_string, variables):
    """
    Interpolate template variables with Jinja2 support and backward compatibility.

    Uses a hybrid approach:
    - For simple templates (just {{var}} substitutions): uses regex for backward
      compatibility with hyphenated variable names
    - For templates with Jinja2 features ({% %}, filters, comments): uses full Jinja2

    Jinja2 features supported:
    - Variable substitution: {{var}}, {{loop.item.text}}
    - Conditionals: {% if var %}...{% elif %}...{% else %}...{% endif %}
    - Filters: {{var | default('fallback')}}, {{var | upper}}, {{var | lower}}
    - Loops in templates: {% for item in items %}...{% endfor %}
    - Comments: {# this is a comment #}
    - Whitespace control: {%- -%} and {{- -}}

    Note on variable names:
    - Simple templates support hyphenated names: {{my-var}}
    - For Jinja2 templates, use underscores: {{my_var}} or bracket notation: {{v['my-var']}}

    Args:
        template_string: String containing template syntax
        variables: Dict of variable names to values (can be nested)

    Returns:
        str: Rendered template string

    Examples:
        >>> interpolate_variables("Hello {{name}}", {"name": "World"})
        'Hello World'

        >>> interpolate_variables("{{base-var}}-ext", {"base-var": "value"})
        'value-ext'

        >>> interpolate_variables("{% if debug %}DEBUG{% endif %}", {"debug": True})
        'DEBUG'

        >>> interpolate_variables("{{val | default('none')}}", {})
        'none'
    """
    # Use simple interpolation for backward compatibility when no Jinja2 features
    if not _has_jinja2_features(template_string):
        return _simple_interpolate(template_string, variables)

    # Use full Jinja2 for advanced features
    # Add 'v' namespace for accessing hyphenated variables: {{v['my-var']}}
    variables_with_namespace = dict(variables)
    variables_with_namespace["v"] = variables

    template = _jinja_env.from_string(template_string)
    return template.render(**variables_with_namespace)


def evaluate_expression(expression, variables):
    """
    Evaluate a Jinja2 expression and return its native Python value.

    Uses NativeEnvironment to evaluate expressions to native types (bool, int, etc.)
    rather than strings. This is essential for `when` conditions that need boolean
    evaluation.

    The expression should be a Jinja2 expression like:
    - "{{var}} == 'value'" -> True/False
    - "{{a}} and {{b}}" -> True/False
    - "{{count}} > 0" -> True/False
    - "not {{skip}}" -> True/False
    - "{{env}} == 'prod' or {{force}}" -> True/False

    Supported operations:
    - Comparisons: ==, !=, <, >, <=, >=
    - Boolean logic: and, or, not
    - String operations: in, not in
    - Arithmetic: +, -, *, /, %

    Args:
        expression: Jinja2 expression string to evaluate
        variables: Dict of variable names to values

    Returns:
        Native Python value (typically bool for `when` conditions)

    Examples:
        >>> evaluate_expression("{{env}} == 'production'", {"env": "production"})
        True

        >>> evaluate_expression("{{a}} and {{b}}", {"a": True, "b": False})
        False

        >>> evaluate_expression("{{count}} > 0", {"count": 5})
        True

        >>> evaluate_expression("not {{skip}}", {"skip": False})
        True

        >>> evaluate_expression("{{env}} == 'prod' or {{force}}", {"env": "staging", "force": True})
        True
    """
    if not expression:
        return False

    # Convert {{var}} to proper Jinja2 variable reference
    # Transform "{{var}} == 'value'" to "{{ var == 'value' }}"
    # This allows NativeEnvironment to properly evaluate the expression

    # First, normalize variable references from {{var}} to Jinja2-compatible names
    # Replace {{var.path}} with var_path to avoid issues with reserved names
    # Then use NativeEnvironment to evaluate the full expression

    # Create a flat variable mapping for nested access
    # This flattens {"loop": {"item": {"text": "value"}}} to allow loop.item.text access
    flat_vars = _flatten_variables(variables)

    # Convert {{var}} syntax to direct Jinja2 variable reference
    # "{{env}} == 'prod'" -> "env == 'prod'"
    # "{{a}} and {{b}}" -> "a and b"
    # Pattern: replace {{var}} with var, handling nested paths
    pattern = r"\{\{([^}]+)\}\}"

    def replace_var(match):
        var_path = match.group(1).strip()
        # Replace dots and hyphens with underscores for valid Python identifiers
        safe_name = var_path.replace(".", "_").replace("-", "_")
        return safe_name

    converted_expr = re.sub(pattern, replace_var, expression)

    # Wrap the converted expression in {{ }} for Jinja2
    jinja_expression = "{{ " + converted_expr + " }}"

    try:
        template = _native_env.from_string(jinja_expression)
        result = template.render(**flat_vars)
        return result
    except Exception:
        # If evaluation fails, return False (expression is invalid)
        return False


def _flatten_variables(variables, prefix=""):
    """
    Flatten nested variables dict for Jinja2 expression evaluation.

    Converts {"loop": {"item": {"text": "value"}}} to:
    - {"loop": {"item": {...}}, "loop_item": {"text": "value"}, "loop_item_text": "value"}

    This allows expressions like "{{loop.item.text}}" to work when converted to "loop_item_text".

    Also handles hyphenated variable names by converting them:
    - {"my-var": "value"} -> {"my_var": "value", "my-var": "value"}

    Args:
        variables: Dict of variable names to values (can be nested)
        prefix: Prefix for nested keys (used recursively)

    Returns:
        dict: Flattened variables with both original and converted keys
    """
    result = {}

    for key, value in variables.items():
        # Add original key
        if prefix:
            flat_key = f"{prefix}_{key}"
        else:
            flat_key = key

        # Convert hyphens to underscores in the flat key
        safe_key = flat_key.replace("-", "_")
        result[safe_key] = value

        # If value is a dict, recursively flatten
        if isinstance(value, dict):
            nested = _flatten_variables(value, flat_key)
            result.update(nested)

    # Also add original keys with hyphens converted to underscores at top level
    for key, value in variables.items():
        safe_key = key.replace("-", "_")
        if safe_key not in result:
            result[safe_key] = value

    return result
