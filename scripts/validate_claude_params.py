#!/usr/bin/env python3
"""Live matrix for the claude adapter (shared harness framework)."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness_matrix import PROMPT_WRITE, Case, main, make_fixtures, surface_cases  # noqa: E402
from agent_yaml.adapters.claude import ClaudeAdapter  # noqa: E402

DEFAULT_MODEL = os.environ.get("CLAUDE_VALIDATION_MODEL", "haiku-5.5")


def cases(model):
    adapter = ClaudeAdapter()
    base = {"model": model}
    extra = [
        Case(
            "json-schema",
            {**base, "json-schema": '{"type":"object"}'},
            expect_stdout=None,
            expect_json=True,
            note="--json-schema constrains the printed output",
            tags=["output"],
        ),
        Case(
            "session-id",
            {**base, "session-id": "__UUID__"},
            note="--session-id creates the session",
            tags=["session"],
        ),
        Case(
            "continue",
            {**base, "continue": True},
            note="--continue resumes the seeded session",
            tags=["session"],
        ),
        Case(
            "tools-write",
            {**base, "tools": ["default"], "skip-confirmations": True},
            prompt=PROMPT_WRITE,
            expect_stdout=None,
            expect_file="marker.txt",
            note="tools plus skip-confirmations lets the agent write",
            tags=["tools"],
        ),
    ]
    return surface_cases(adapter, base, extra)


def prepare(case, config, workdir, env):
    if case.name == "session-id":
        config["session-id"] = str(uuid.uuid4())
    if case.name == "continue":
        seed = ClaudeAdapter().build_command(
            {"model": config["model"], "session-id": str(uuid.uuid4())},
            "Reply with exactly: OK",
        )
        subprocess.run(
            seed, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300
        )
    return config, None


def workspace_setup(workdir, env):
    make_fixtures(workdir)


if __name__ == "__main__":
    sys.exit(
        main(
            ClaudeAdapter,
            cases,
            DEFAULT_MODEL,
            env=os.environ.copy(),
            prepare=prepare,
            workspace_setup=workspace_setup,
            descriptions=__doc__,
        )
    )
