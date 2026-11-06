"""
Base adapter interface.

Every harness adapter declares the same metadata and option spec, and uses the
same helpers to build argv. The registry, the schema validator, and the live
matrix coverage guard all read that metadata instead of keeping their own copies.

Adapter contract:
- ``name``: registry key and ``cli-agent`` value
- ``executables``: binaries that satisfy the adapter (first is preferred)
- ``install_hint``: what to install when none are on PATH
- ``prompt_style`` + ``prompt_flag``/``prompt_separator``: how the prompt is passed
- ``option_spec``: every accepted ``cli-agent-config`` key with its type
- ``live_exempt``: surfaces the live matrix cannot exercise, with a reason
- ``cross_validate``: adapter-specific rules that need more than one key

Option kinds: ``str``, ``bool``, ``int`` (positive), ``number`` (positive),
``str_or_list``, ``list``, ``enum`` (``values``), and ``ignored`` (accepted and
dropped, with a remediation ``hint``).
"""

import logging
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    """One accepted ``cli-agent-config`` key."""

    kind: str
    values: tuple = ()
    hint: str = ""


STR = Option("str")
BOOL = Option("bool")
INT = Option("int")
NUMBER = Option("number")
STR_OR_LIST = Option("str_or_list")
LIST = Option("list")


def ENUM(*values):
    return Option("enum", values)


def IGNORED(hint):
    return Option("ignored", hint=hint)


IGNORED_SILENT = Option("ignored")


KIND_LABELS = {
    "str": "string",
    "bool": "boolean",
    "int": "positive integer",
    "number": "positive number",
    "str_or_list": "string or list of strings",
    "list": "list of strings",
    "enum": "string",
    "ignored": "accepted and ignored",
}


class BaseAdapter(ABC):
    """Shared behavior for CLI harness adapters."""

    name = ""
    executables = ()
    install_hint = ""
    needs_empty_stdin = False

    fallback_executable = None
    prompt_style = "positional"  # "positional" | "flag" | "separator"
    prompt_flag = None
    prompt_separator = None

    option_spec = {}
    live_exempt = {}

    def __init__(self, tool_config=None):
        self.tool_name = self.name
        self.tool_config = tool_config or {}

    @property
    def logger(self):
        return logging.getLogger(f"agent_yaml.adapters.{self.name}")

    def check_available(self):
        """True when one of the adapter's binaries is on PATH."""
        return any(shutil.which(executable) for executable in self.executables)

    def executable(self):
        """First executable found on PATH, or the preferred one."""
        for executable in self.executables:
            if shutil.which(executable):
                return executable
        return self.fallback_executable or self.executables[0]

    def warn_ignored(self, config):
        """Log the declared remediation for every ignored option that is set."""
        for key, option in self.option_spec.items():
            if option.kind == "ignored" and option.hint and config.get(key):
                self.logger.warning(
                    f"{self.name} adapter ignores '{key}'; {option.hint}"
                )

    def append_prompt(self, cmd, prompt):
        """Append the prompt using the adapter's declared style."""
        if self.prompt_style == "flag":
            cmd.extend([self.prompt_flag, prompt])
        elif self.prompt_style == "separator":
            cmd.extend([self.prompt_separator, prompt])
        else:
            if prompt.startswith("-"):
                self.logger.warning(
                    f"{self.name} adapter: prompt starts with '-'; prefixing a space so it "
                    "is not parsed as a flag"
                )
                prompt = " " + prompt
            cmd.append(prompt)
        return cmd

    @staticmethod
    def join_list(value, separator=","):
        """Join a list value, passing strings through unchanged."""
        if isinstance(value, (list, tuple)):
            return separator.join(str(item) for item in value)
        return value

    def cross_validate(self, config, fail):
        """Adapter-specific multi-key rules. Override when needed."""

    @abstractmethod
    def build_command(self, task_config, prompt):
        """Build the CLI argv for one task."""
