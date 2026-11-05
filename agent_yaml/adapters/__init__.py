"""
CLI adapter modules for different AI agent tools.

Provides tool-specific adapters that translate generic workflow configurations
into tool-specific CLI invocations for OpenCode, Claude, Gemini, Qwen, and Codex.
"""

from .base import BaseAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .gemini import GeminiAdapter
from .opencode import OpenCodeAdapter
from .qwen import QwenAdapter


class UnsupportedCLIError(Exception):
    """Exception raised when an unsupported or unknown CLI agent is specified."""

    pass


class CLINotFoundError(Exception):
    """Exception raised when the CLI executable is not found in PATH."""

    pass


def get_adapter(cli_agent_name: str) -> BaseAdapter:
    """
    Factory function to get the appropriate adapter for a CLI agent.

    Args:
        cli_agent_name: Name of the CLI agent (opencode, claude, gemini, qwen, codex)

    Returns:
        BaseAdapter: Instance of the appropriate adapter class

    Raises:
        UnsupportedCLIError: If the CLI agent name is not recognized
        CLINotFoundError: If the CLI executable is not found in PATH

    Reference:
        spec/ADAPTER_SPEC.md lines 627-792 for capability detection and translation logic
    """
    # Normalize to lowercase for case-insensitive matching
    cli_name = cli_agent_name.lower().strip()

    # Map CLI agent names to adapter classes
    adapter_map = {
        "opencode": OpenCodeAdapter,
        "claude": ClaudeAdapter,
        "gemini": GeminiAdapter,
        "qwen": QwenAdapter,
        "codex": CodexAdapter,
    }

    # Check if CLI agent is supported
    if cli_name not in adapter_map:
        supported_agents = ", ".join(sorted(adapter_map.keys()))
        raise UnsupportedCLIError(
            f"Unsupported CLI agent: '{cli_agent_name}'. Supported agents are: {supported_agents}"
        )

    # Create adapter instance
    adapter_class = adapter_map[cli_name]
    adapter = adapter_class()

    # Validate that CLI executable is available
    if not adapter.check_available():
        # Get the expected executable name based on the adapter
        if cli_name == "claude":
            executable_hint = "claude-code or claude"
        else:
            executable_hint = cli_name

        raise CLINotFoundError(
            f"CLI executable not found for '{cli_agent_name}'. "
            f"Please ensure '{executable_hint}' is installed and available in PATH. "
            f"Run 'which {executable_hint.split()[0]}' to verify installation."
        )

    return adapter


__all__ = [
    "BaseAdapter",
    "ClaudeAdapter",
    "GeminiAdapter",
    "QwenAdapter",
    "CodexAdapter",
    "OpenCodeAdapter",
    "UnsupportedCLIError",
    "CLINotFoundError",
    "get_adapter",
]
