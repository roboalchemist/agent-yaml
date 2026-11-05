"""
Include file concatenation and variable interpolation.

Handles the 'include' field for prompt composition:
- String concatenation of multiple files
- Variable interpolation in included content
- File path resolution (relative to workflow file or absolute)
- Circular include dependency detection

Include format:
    include:
      - path/to/prompt-part-1.txt
      - path/to/prompt-part-2.txt

The included files are concatenated in order with variable substitution applied.

Includes can reference other includes via {{include-name}} syntax, but circular
dependencies are not allowed and will raise CircularIncludeError.

Reference: spec/YAML_SPEC.md for include specification.
"""

import os
import re

from .utils import interpolate_variables


class CircularIncludeError(Exception):
    """Raised when circular include dependencies are detected."""

    pass


def detect_circular_includes(includes_dict):
    """
    Detect circular dependencies in include definitions.

    Includes can reference other includes via {{include-name}} syntax.
    This function builds a dependency graph and detects cycles.

    Args:
        includes_dict: Dictionary of include definitions {name: value}

    Raises:
        CircularIncludeError: If circular dependency detected with chain

    Example:
        >>> includes = {
        ...     "intro": "Start with {{context}}",
        ...     "context": "Use {{background}}",
        ...     "background": "Reference {{intro}}"
        ... }
        >>> detect_circular_includes(includes)
        # Raises: CircularIncludeError with chain: intro -> context -> background -> intro
    """
    if not includes_dict:
        return

    # Build dependency graph
    # dependency_graph[include_name] = [list of include names it references]
    dependency_graph = {}

    # Regex to extract {{variable}} patterns
    variable_pattern = r"\{\{([^}]+)\}\}"

    for include_name, include_value in includes_dict.items():
        # Find all {{var}} references in this include's value
        matches = re.findall(variable_pattern, include_value)

        # Check which of these match other include names (including self-reference)
        dependencies = []
        for var_name in matches:
            var_name = var_name.strip()
            # If this variable name matches an include name, it's a dependency
            # This includes self-references (e.g., intro: "{{intro}}")
            if var_name in includes_dict:
                dependencies.append(var_name)

        dependency_graph[include_name] = dependencies

    # Detect cycles using DFS
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

    # Check each include for cycles
    for include_name in includes_dict.keys():
        if include_name not in visited:
            cycle = dfs(include_name, [])
            if cycle:
                # Format cycle chain: a -> b -> c -> a
                cycle_chain = " -> ".join(cycle)
                raise CircularIncludeError(
                    f"Circular include dependency detected\n\n"
                    f"Context: Include resolution for workflow includes\n"
                    f"Expected: Acyclic include dependencies\n"
                    f"Found: Circular chain: {cycle_chain}\n"
                    f"Suggestion: Break the circular reference by removing include references or using literal text"
                )


def resolve_includes(include_list, workflow_dir, variables):
    """
    Resolve include files and concatenate with variable interpolation.

    Args:
        include_list: List of file paths to include
        workflow_dir: Directory containing the workflow file (for relative paths)
        variables: Resolved variables for interpolation

    Returns:
        str: Concatenated and interpolated content

    Raises:
        FileNotFoundError: If included file doesn't exist
        PermissionError: If permission denied reading include file
    """
    # Handle empty or None include list
    if not include_list:
        return ""

    concatenated_parts = []

    for include_path in include_list:
        # 1. Interpolate variables in path
        include_path = interpolate_variables(include_path, variables)

        # 2. Expand user home directory (~)
        include_path = os.path.expanduser(include_path)

        # 3. Resolve relative paths relative to workflow YAML location
        if not os.path.isabs(include_path):
            include_path = os.path.join(workflow_dir, include_path)

        # 4. Normalize path
        include_path = os.path.abspath(include_path)

        # 5. Read file with error handling
        try:
            with open(include_path, "r", encoding="utf-8") as f:
                content = f.read()
                concatenated_parts.append(content)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Include file resolution failed\n\n"
                f"Context: Resolving include file for workflow\n"
                f"Expected: Include file to exist at path\n"
                f"Found: File not found: {include_path}\n"
                f"Suggestion: Verify the file path is correct and the file exists"
            )
        except PermissionError:
            raise PermissionError(
                f"Include file access denied\n\n"
                f"Context: Reading include file for workflow\n"
                f"Expected: Read permission on include file\n"
                f"Found: Permission denied reading file: {include_path}\n"
                f"Suggestion: Check file permissions and ensure the file is readable"
            )

    # 6. Concatenate with space separator
    return " ".join(concatenated_parts)


def append_includes_to_prompt(prompt_text, include_string):
    """
    Append resolved include string to prompt text with space separator.

    Takes base prompt and resolved include string and concatenates them.
    If include_string is empty or None, returns just the prompt_text.
    Otherwise appends include_string to prompt_text with single space separator.

    This implements the final step of prompt composition after includes are resolved
    and variables are interpolated. The prompt always comes first, followed by includes.

    Reference: spec/YAML_SPEC.md lines 290-305

    Args:
        prompt_text (str): The base prompt text
        include_string (str): The resolved include string (already concatenated and interpolated)

    Returns:
        str: Final prompt text with includes appended

    Examples:
        >>> append_includes_to_prompt("Do work", "Use sub-agents")
        'Do work Use sub-agents'

        >>> append_includes_to_prompt("Do work", "")
        'Do work'

        >>> append_includes_to_prompt("Do work", None)
        'Do work'

        >>> append_includes_to_prompt("", "Use sub-agents")
        ' Use sub-agents'
    """
    if not include_string:
        return prompt_text
    return f"{prompt_text} {include_string}"
