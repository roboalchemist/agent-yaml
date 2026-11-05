"""
Template variable resolution and management.

Handles resolution of reserved and user-defined template variables.
Implements circular dependency detection using spanning tree algorithm.

Reserved variables (auto-injected, immutable):
- {{gitroot}} - Git repository root
- {{datetime}} - ISO 8601 timestamp (workflow start time)
- {{user}} - System username
- {{directory}} - Working directory (absolute path)

Variable resolution order:
1. Reserved variables (injected first)
2. User variables (topologically sorted)
3. Prompt interpolation (just-in-time)

Full Jinja2 syntax is supported:
- Conditionals: {% if var %}...{% endif %}
- Filters: {{var | default('fallback')}}
- Loops: {% for item in items %}...{% endfor %}

Reference: spec/PROJECT_SPECS.md lines 163-178 for circular dependency detection.
"""

import os
import re
from datetime import datetime
from pathlib import Path


class ReservedVariables:
    """
    Manages reserved template variables.

    Reserved variables are auto-injected and immutable. They cannot be
    overridden by user-defined variables.

    Reserved variables:
    - gitroot: Git repository root (walks up to find .git/)
    - datetime: ISO 8601 timestamp with local timezone
    - user: System username from environment
    - directory: Working directory (absolute path)
    """

    RESERVED_NAMES = ["gitroot", "datetime", "user", "directory", "env"]

    def get_reserved_vars(self, directory_path, workflow_env=None, task_env=None):
        """
        Resolve all reserved template variables.

        Args:
            directory_path: Working directory path (may be relative or contain ~)
            workflow_env: Optional dict of workflow-level environment variables
            task_env: Optional dict of task-level environment variables

        Returns:
            dict: Dictionary with keys 'gitroot', 'datetime', 'user', 'directory', 'env'.
                  All path values are absolute paths.
                  'env' is a dict containing merged environment variables.

        Examples:
            >>> rv = ReservedVariables()
            >>> vars = rv.get_reserved_vars('/home/user/project')
            >>> vars['gitroot']
            '/home/user/project'
            >>> vars['directory']
            '/home/user/project'
            >>> vars['env']['HOME']
            '/home/user'
        """
        # Resolve directory to absolute path first
        abs_directory = self._resolve_absolute_path(directory_path)

        # Build merged environment: system < workflow < task
        merged_env = os.environ.copy()
        if workflow_env:
            for key, value in workflow_env.items():
                merged_env[key] = str(value) if value is not None else ""
        if task_env:
            for key, value in task_env.items():
                merged_env[key] = str(value) if value is not None else ""

        return {
            "gitroot": self._find_git_root(abs_directory),
            "datetime": self._get_current_datetime_iso8601(),
            "user": self._get_system_user(),
            "directory": abs_directory,
            "env": merged_env,
        }

    def _find_git_root(self, directory_path):
        """
        Walk up directory tree to find git repository root.

        Searches for .git/ directory or .git file (for worktrees).
        Falls back to directory_path if no git repo found.

        Args:
            directory_path: Starting directory (must be absolute)

        Returns:
            str: Absolute path to git root, or directory_path if not in git repo
        """
        current_path = Path(directory_path).resolve()

        # Walk up the directory tree
        for parent in [current_path] + list(current_path.parents):
            git_path = parent / ".git"
            if git_path.exists():
                return str(parent)

        # Not in a git repository, return original directory
        return str(current_path)

    def _get_current_datetime_iso8601(self):
        """
        Get current datetime in ISO 8601 format with local timezone.

        Format: YYYY-MM-DDTHH:MM:SS.sss±HH:MM
        Example: 2025-10-01T23:45:30.123-07:00

        Returns:
            str: ISO 8601 formatted timestamp with milliseconds and timezone
        """
        return datetime.now().astimezone().isoformat(timespec="milliseconds")

    def _get_system_user(self):
        """
        Get system username from environment variables.

        Checks in order: USER, USERNAME, LOGNAME
        Falls back to 'unknown' if all are missing or empty.

        Returns:
            str: System username or 'unknown'
        """
        for env_var in ["USER", "USERNAME", "LOGNAME"]:
            user = os.environ.get(env_var, "").strip()
            if user:
                return user

        return "unknown"

    def _resolve_absolute_path(self, path):
        """
        Resolve path to absolute path with tilde expansion.

        Args:
            path: File path (may be relative, absolute, or contain ~)

        Returns:
            str: Absolute path
        """
        expanded = os.path.expanduser(path)
        return os.path.abspath(expanded)


def resolve_user_variables(variables_dict, reserved_vars):
    """
    Resolve user-defined variables with circular dependency detection.

    Uses DFS with path tracking to detect circular dependencies and
    topological sort to determine resolution order.

    Args:
        variables_dict: User-defined variables from workflow
        reserved_vars: Already-resolved reserved variables

    Returns:
        dict: All resolved variables (reserved + user)

    Raises:
        CircularDependencyError: If circular reference detected
        UndefinedVariableError: If variable references undefined variable

    Example:
        >>> reserved = {"gitroot": "/repo", "datetime": "2025-01-01T00:00:00"}
        >>> user_vars = {"a": "{{b}}", "b": "value"}
        >>> result = resolve_user_variables(user_vars, reserved)
        >>> result["a"]
        'value'
    """
    from agent_yaml.utils import interpolate_variables

    if not variables_dict:
        # No user variables, just return reserved vars
        return dict(reserved_vars)

    # Check for reserved variable override attempts
    for var_name in variables_dict.keys():
        if var_name in ReservedVariables.RESERVED_NAMES:
            raise CircularDependencyError(
                f"Cannot override reserved variable\n\n"
                f"Context: User variable '{var_name}' conflicts with reserved variable\n"
                f"Expected: User variables cannot have reserved names\n"
                f"Found: Attempt to define '{var_name}' in template-variables\n"
                f"Reserved names: {ReservedVariables.RESERVED_NAMES}\n"
                f"Suggestion: Rename the variable to avoid conflict with reserved names"
            )

    # Build dependency graph
    # dependency_graph[var_name] = [list of user var names it references]
    dependency_graph = {}

    # Regex to extract {{variable}} patterns (alphanumeric, underscores, hyphens)
    variable_pattern = r"\{\{([a-zA-Z_][a-zA-Z0-9_-]*)\}\}"

    for var_name, var_value in variables_dict.items():
        # Find all {{var}} references in this variable's value
        matches = re.findall(variable_pattern, str(var_value))

        # Check which of these match other user variable names
        dependencies = []
        for referenced_var in matches:
            referenced_var = referenced_var.strip()
            # Skip reserved variables (they're always available)
            if referenced_var in ReservedVariables.RESERVED_NAMES:
                continue
            # If this variable name matches a user var name, it's a dependency
            if referenced_var in variables_dict:
                dependencies.append(referenced_var)
            else:
                # Referenced variable is not defined (not in user vars or reserved vars)
                if referenced_var not in reserved_vars:
                    all_vars = sorted(list(reserved_vars.keys()) + list(variables_dict.keys()))
                    raise UndefinedVariableError(
                        f"Variable '{referenced_var}' is referenced but not defined\n\n"
                        f"Context: Variable '{var_name}' references '{{{{referenced_var}}}}'\n"
                        f"Expected: All referenced variables must be defined\n"
                        f"Available variables: {all_vars}\n"
                        f"Suggestion: Define '{referenced_var}' in template-variables or remove the reference"
                    )

        dependency_graph[var_name] = dependencies

    # Detect cycles using DFS with path tracking
    visited = set()
    rec_stack = set()  # Recursion stack to track current path

    def dfs(node, path):
        """DFS to detect cycle. Returns cycle path if found, None otherwise."""
        if node in rec_stack:
            # Found a cycle - return the cycle path
            cycle_start_index = path.index(node)
            cycle = path[cycle_start_index:] + [node]
            return cycle

        if node in visited:
            return None

        visited.add(node)
        rec_stack.add(node)

        # Visit all dependencies
        for dependency in dependency_graph.get(node, []):
            cycle = dfs(dependency, path + [node])
            if cycle:
                return cycle

        rec_stack.remove(node)
        return None

    # Check each variable for cycles
    for var_name in variables_dict.keys():
        if var_name not in visited:
            cycle = dfs(var_name, [])
            if cycle:
                # Format cycle chain: a -> b -> c -> a
                cycle_chain = " -> ".join(cycle)
                raise CircularDependencyError(
                    f"Circular variable dependency detected\n\n"
                    f"Context: User variable resolution for template-variables\n"
                    f"Expected: Acyclic variable dependencies\n"
                    f"Found: Circular chain: {cycle_chain}\n"
                    f"Suggestion: Break the circular reference or use literal text"
                )

    # Perform topological sort using DFS
    # Variables with no dependencies should be resolved first
    sorted_vars = []
    visited = set()

    def topological_dfs(node):
        """DFS for topological sort. Adds nodes in post-order."""
        if node in visited:
            return

        visited.add(node)

        # Visit all dependencies first
        for dependency in dependency_graph.get(node, []):
            topological_dfs(dependency)

        # Add this node after all dependencies
        sorted_vars.append(node)

    # Perform topological sort
    for var_name in variables_dict.keys():
        if var_name not in visited:
            topological_dfs(var_name)

    # Resolve variables in topological order
    # Start with reserved vars
    resolved_vars = dict(reserved_vars)

    for var_name in sorted_vars:
        var_value = variables_dict[var_name]
        if not isinstance(var_value, str):
            # Keep YAML scalars/collections native (no {{}} to expand): stringifying
            # `force: false` to "False" made `when: "not {{force}}"` evaluate False.
            resolved_vars[var_name] = var_value
            continue
        # Interpolate using all currently resolved variables
        resolved_value = interpolate_variables(var_value, resolved_vars)
        resolved_vars[var_name] = resolved_value

    return resolved_vars


class CircularDependencyError(Exception):
    """Raised when circular variable dependencies are detected."""

    pass


class UndefinedVariableError(Exception):
    """Raised when a template variable is referenced but not defined."""

    pass
