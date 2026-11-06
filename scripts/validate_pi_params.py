#!/usr/bin/env python3
"""Live matrix for the pi adapter (shared harness framework)."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness_matrix import PROMPT_WRITE, Case, main, surface_cases  # noqa: E402
from agent_yaml.adapters.pi import PiAdapter  # noqa: E402

DEFAULT_MODEL = os.environ.get("PI_VALIDATION_MODEL", "")


def cases(model):
    adapter = PiAdapter()
    base = {"model": model}
    extra = [
        Case(
            "provider",
            {"provider": model.split("/", 1)[0], "model": model},
            note="explicit provider with model",
            tags=["core"],
        ),
        Case(
            "tools-write",
            {**base, "tools": ["bash"]},
            prompt=PROMPT_WRITE,
            expect_stdout=None,
            expect_file="marker.txt",
            note="tools allowlist permits a write",
            tags=["tools"],
        ),
        Case(
            "tools-read",
            {**base, "tools": ["read"]},
            prompt=PROMPT_WRITE,
            expect_stdout=None,
            forbid_file="marker.txt",
            note="tools allowlist blocks a write",
            tags=["tools"],
        ),
        Case(
            "exclude-tools",
            {**base, "exclude-tools": ["write", "edit", "bash"]},
            prompt=PROMPT_WRITE,
            expect_stdout=None,
            forbid_file="marker.txt",
            note="deny list blocks a write",
            tags=["tools"],
        ),
        Case(
            "session-dir",
            {**base, "session": True, "session-dir": "{workdir}/sessions"},
            session_dir="sessions",
            note="--session-dir stores the session",
            tags=["session"],
        ),
        Case(
            "session-id",
            {**base, "session-id": "matrix-session", "session-dir": "{workdir}/sessions"},
            session_dir="sessions",
            note="--session-id creates the session",
            tags=["session"],
        ),
        Case(
            "continue",
            {**base, "continue": True, "session-dir": "{workdir}/sessions"},
            note="--continue resumes the seeded session",
            tags=["session"],
        ),
        Case(
            "session-true",
            {**base, "session": True},
            note="session: true keeps persistence",
            tags=["session"],
        ),
        Case(
            "skip-confirmations=false",
            {**base, "skip-confirmations": False},
            note="explicit false adds --no-approve",
            tags=["flags"],
        ),
    ]
    return surface_cases(adapter, base, extra)


def prepare(case, config, workdir, env):
    if case.name == "continue":
        seed = PiAdapter().build_command(
            {"model": config["model"], "session": True, "session-dir": str(workdir / "sessions")},
            "Reply with exactly: OK",
        )
        subprocess.run(
            seed, cwd=workdir, env=env, input="", capture_output=True, text=True, timeout=240
        )
    return config, None


if __name__ == "__main__":
    sys.exit(main(PiAdapter, cases, DEFAULT_MODEL, descriptions=__doc__))
