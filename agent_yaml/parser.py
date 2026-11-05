"""
YAML workflow parser.

Responsible for loading and parsing YAML workflow files using yaml.safe_load.
Handles basic YAML syntax validation and structure extraction.

Reference: spec/YAML_SPEC.md for complete YAML format specification.
"""


def parse_workflow(file_path):
    """
    Parse a YAML workflow file.

    Args:
        file_path: Path to the YAML workflow file

    Returns:
        dict: Parsed workflow structure

    Raises:
        yaml.YAMLError: If YAML syntax is invalid
        FileNotFoundError: If workflow file doesn't exist
    """
    import os

    import yaml

    # Check if file exists
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Workflow file not found: {file_path}")

    # Load and parse YAML
    with open(file_path, "r", encoding="utf-8") as f:
        workflow = yaml.safe_load(f)

    # Check for empty workflow file
    if workflow is None:
        raise ValueError(
            "Empty workflow file\n\n"
            "Context: Workflow file is empty or contains only whitespace\n"
            f"File: {file_path}\n"
            "Expected: Valid YAML workflow with 'directory' and 'task' fields\n"
            "Found: Empty file\n"
            "Suggestion: Add a workflow definition with required fields:\n"
            "  directory: /path/to/working/dir\n"
            "  task:\n"
            "    - task-name:\n"
            '        prompt: "Your task prompt"'
        )

    return workflow
