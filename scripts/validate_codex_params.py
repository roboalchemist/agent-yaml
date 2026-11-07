#!/usr/bin/env python3
"""Live matrix for the codex adapter (shared harness framework)."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness_matrix import PROMPT_WRITE, Case, main, make_fixtures, surface_cases  # noqa: E402
from agent_yaml.adapters.codex import CodexAdapter  # noqa: E402

DEFAULT_MODEL = os.environ.get("CODEX_VALIDATION_MODEL", "gpt-6-luna")


def cases(model):
    adapter = CodexAdapter()
    base = {"model": model}
    extra = [
        Case(
            "continue",
            {**base, "continue": True},
            note="exec resume --last continues the seeded session",
            tags=["session"],
        ),
        Case(
            "skip-confirmations",
            {**base, "skip-confirmations": True},
            prompt=PROMPT_WRITE,
            expect_stdout=None,
            expect_file="marker.txt",
            note="approval bypass lets the agent write",
            tags=["tools"],
        ),
    ]
    return surface_cases(adapter, base, extra)


def prepare(case, config, workdir, env):
    if case.name == "continue":
        seed = CodexAdapter().build_command({"model": config["model"]}, "Reply with exactly: OK")
        subprocess.run(
            seed, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300
        )
    return config, None


def workspace_setup(workdir, env):
    make_fixtures(workdir)


if __name__ == "__main__":
    sys.exit(
        main(
            CodexAdapter,
            cases,
            DEFAULT_MODEL,
            env=os.environ.copy(),
            prepare=prepare,
            workspace_setup=workspace_setup,
            descriptions=__doc__,
        )
    )
