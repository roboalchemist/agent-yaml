"""
Start-time validation of a workflow's `ensure` block.

run_workflow() calls validate_ensure_block() once, before any task runs, and fails
fast if a declared dependency is missing:
- tools: executables that must be on PATH (checked with shutil.which)
- mcps: MCP servers (detection is not implemented yet; each one logs a warning and passes)

All missing items are reported together in a single EnsureValidationError.

Ensure block format:
    ensure:
      mcps:
        - server-name
      tools:
        - executable-name

Reference: spec/YAML_SPEC.md for ensure block specification.
"""

import sys


def validate_ensure_block(ensure_config):
    """
    Validate that all required resources exist.

    Args:
        ensure_config: Ensure block configuration dict with optional 'mcps' and 'tools' lists

    Returns:
        bool: True if all resources available

    Raises:
        EnsureValidationError: If required resource is missing with list of all missing items
    """
    if not ensure_config:
        return True

    missing_tools = []
    missing_mcps = []

    # Check tools
    tools = ensure_config.get("tools", [])
    for tool in tools:
        if not check_tool_available(tool):
            missing_tools.append(tool)

    # Check MCPs
    mcps = ensure_config.get("mcps", [])
    for mcp in mcps:
        if not check_mcp_available(mcp):
            missing_mcps.append(mcp)

    # Raise error with all missing items
    if missing_tools or missing_mcps:
        error_parts = []

        if missing_tools:
            tools_list = ", ".join(missing_tools)
            error_parts.append(f"Missing required tools: [{tools_list}]")

        if missing_mcps:
            mcps_list = ", ".join(missing_mcps)
            error_parts.append(f"Missing required MCPs: [{mcps_list}]")

        # Add installation hints
        error_msg = "; ".join(error_parts)
        if missing_tools:
            error_msg += "\nInstall missing tools using your package manager (e.g., brew install, apt-get install, pip install)"

        raise EnsureValidationError(error_msg)

    return True


def check_mcp_available(mcp_name):
    """
    Check if MCP server is available.

    Note: MCP detection is not fully implemented. This function logs a warning
    and returns True. Future enhancement: check ~/.claude/mcp.json or environment.

    Args:
        mcp_name: Name of MCP server to check

    Returns:
        bool: True (assumes MCP is available with warning)
    """
    print(
        f"Warning: MCP availability check for '{mcp_name}' is not fully implemented",
        file=sys.stderr,
    )
    return True


def check_tool_available(tool_name):
    """
    Check if CLI tool exists in PATH.

    Args:
        tool_name: Name of executable to check

    Returns:
        bool: True if tool is available in PATH
    """
    import shutil

    return shutil.which(tool_name) is not None


class EnsureValidationError(Exception):
    """Raised when ensure validation fails."""

    pass
