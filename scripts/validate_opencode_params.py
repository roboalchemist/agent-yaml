#!/usr/bin/env python3
"""Live matrix for the opencode adapter (shared harness framework)."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness_matrix import Case, main, make_fixtures, surface_cases  # noqa: E402
from agent_yaml.adapters.opencode import OpenCodeAdapter  # noqa: E402

DEFAULT_MODEL = os.environ.get("OPENCODE_VALIDATION_MODEL", "")


def cases(model):
    adapter = OpenCodeAdapter()
    base = {"model": model}
    extra = [
        Case(
            "continue",
            {**base, "continue": True},
            note="--continue resumes the seeded session",
            tags=["session"],
        ),
        Case(
            "skip-confirmations",
            {**base, "skip-confirmations": True},
            prompt="Create a file named marker.txt containing exactly: ok",
            expect_stdout=None,
            note="--auto is accepted and the turn completes",
            tags=["flags"],
        ),
    ]
    return surface_cases(adapter, base, extra)


def prepare(case, config, workdir, env):
    if case.name == "continue":
        seed = OpenCodeAdapter().build_command({"model": config["model"]}, "Reply with exactly: OK")
        subprocess.run(
            seed, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300
        )
    return config, None


def workspace_setup(workdir, env):
    make_fixtures(workdir)


if __name__ == "__main__":
    sys.exit(
        main(
            OpenCodeAdapter,
            cases,
            DEFAULT_MODEL,
            env=os.environ.copy(),
            prepare=prepare,
            workspace_setup=workspace_setup,
            descriptions=__doc__,
        )
    )
