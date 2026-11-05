"""
Base adapter abstract class.

Defines the interface that all CLI adapters must implement.
Provides common functionality for command building and subprocess execution.

All adapters translate generic configurations to tool-specific CLI arguments:
- skip-confirmations → tool-specific flag
- additional-dirs → tool-specific workspace/directory flag
- timeout → subprocess timeout (not CLI arg)
- mcp-config-file → tool-specific MCP configuration

Reference: spec/ADAPTER_SPEC.md for complete mapping specifications.
"""

from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """Abstract base class for CLI adapters."""

    def __init__(self, tool_name, tool_config=None):
        """
        Initialize adapter.

        Args:
            tool_name: Name of the CLI tool (claude, gemini, qwen, codex)
            tool_config: Optional tool-specific configuration
        """
        self.tool_name = tool_name
        self.tool_config = tool_config or {}

    @abstractmethod
    def build_command(self, task_config, prompt):
        """
        Build CLI command from task configuration.

        Args:
            task_config: Task configuration dict
            prompt: Interpolated prompt string

        Returns:
            list: Command as list of strings (argv format)
        """
        pass

    @abstractmethod
    def check_available(self):
        """
        Check if CLI tool is available in PATH.

        Returns:
            bool: True if tool is available
        """
        pass
