"""
CLI harness adapter registry.

Adapters share one interface (see ``base.BaseAdapter``): each declares its name,
binaries, install hint, prompt style, option spec, and live-test exemptions. The
registry, the schema validator, and the test matrices all read that metadata, so
adding a harness means writing one adapter and adding it to ``ADAPTERS``.
"""

import logging

from .antigravity import AntigravityAdapter
from .base import BaseAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .opencode import OpenCodeAdapter
from .pi import PiAdapter
from .vtcode import VTCodeAdapter

logger = logging.getLogger(__name__)


class UnsupportedCLIError(ValueError):
    """Raised when an unknown CLI agent name is requested."""


class CLINotFoundError(RuntimeError):
    """Raised when the requested CLI executable is not on PATH."""


# Ordered registry: cli-agent name -> adapter class.
ADAPTERS = {
    adapter.name: adapter
    for adapter in (
        OpenCodeAdapter,
        ClaudeAdapter,
        CodexAdapter,
        PiAdapter,
        VTCodeAdapter,
        AntigravityAdapter,
    )
}


def get_adapter(cli_agent_name):
    """
    Get an adapter instance for a CLI agent.

    Args:
        cli_agent_name: Registered adapter name (case-insensitive)

    Returns:
        BaseAdapter: Adapter instance

    Raises:
        UnsupportedCLIError: If the name is not registered
        CLINotFoundError: If the adapter's executable is not on PATH
    """
    cli_name = cli_agent_name.lower().strip()
    adapter_class = ADAPTERS.get(cli_name)
    if adapter_class is None:
        supported_agents = ", ".join(sorted(ADAPTERS))
        raise UnsupportedCLIError(
            f"Unsupported CLI agent: '{cli_agent_name}'. Supported agents are: {supported_agents}"
        )

    adapter = adapter_class()
    if not adapter.check_available():
        hint = adapter.install_hint
        raise CLINotFoundError(
            f"CLI executable not found for '{cli_agent_name}'. "
            f"Please ensure '{hint}' is installed and available in PATH. "
            f"Run 'which {hint.split()[0]}' to verify installation."
        )
    return adapter


__all__ = [
    "ADAPTERS",
    "AntigravityAdapter",
    "BaseAdapter",
    "CLINotFoundError",
    "ClaudeAdapter",
    "CodexAdapter",
    "OpenCodeAdapter",
    "PiAdapter",
    "UnsupportedCLIError",
    "VTCodeAdapter",
    "get_adapter",
]
