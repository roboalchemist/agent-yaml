#!/usr/bin/env python3
"""Live matrix for the vtcode adapter (shared harness framework)."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness_matrix import (  # noqa: E402
    PROMPT_WRITE,
    Case,
    latest_session,
    main,
    surface_cases,
)
from agent_yaml.adapters.vtcode import VTCodeAdapter  # noqa: E402

DEFAULT_PROVIDER = os.environ.get("VTCODE_VALIDATION_PROVIDER", "bifrost")
DEFAULT_MODEL = os.environ.get("VTCODE_VALIDATION_MODEL", "chunglet/deepseek-v4.1-flash")

WORKSPACE_TOML = """\
[automation.full_auto]
enabled = true
require_profile_ack = false
allowed_tools = [
  "exec_command",
  "write_stdin",
  "apply_patch",
  "code_search",
  "task_tracker",
  "start_planning",
  "request_user_input",
]
"""


def cases(model, provider=DEFAULT_PROVIDER):
    adapter = VTCodeAdapter()
    base = {"provider": provider, "model": model}
    extra = [
        Case(
            "tool-write",
            {**base, "skip-confirmations": True},
            prompt=PROMPT_WRITE,
            expect_stdout=None,
            expect_file="marker.txt",
            note="agent writes a file through the shell tool",
            tags=["tools"],
        ),
        Case(
            "events-file",
            {**base, "events-file": "events.jsonl"},
            expect_stdout=None,
            expect_file="events.jsonl",
            note="--events writes the event stream",
            tags=["output"],
        ),
        Case(
            "last-message-file",
            {**base, "last-message-file": "last.md"},
            expect_stdout=None,
            expect_file="last.md",
            note="--last-message-file writes the final message",
            tags=["output"],
        ),
        Case(
            "config-overrides",
            {**base, "config-overrides": [f"agent.default_model={model}"]},
            expect_stdout=None,
            note="-c overrides are accepted",
            tags=["flags"],
        ),
        Case(
            "continue",
            {**base, "continue": True, "session-id": "__LATEST__"},
            expect_stdout=None,
            note="exec resume continues the seeded session",
            tags=["session"],
        ),
    ]
    return surface_cases(adapter, base, extra, expect_stdout=None)


def prepare(case, config, workdir, env):
    if case.name == "continue":
        seed = VTCodeAdapter().build_command(
            {
                "provider": config["provider"],
                "model": config["model"],
                "session-id": "matrix-seed",
            },
            "Reply with exactly: OK",
        )
        subprocess.run(
            seed, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300
        )
        session_id = latest_session(workdir)
        if not session_id:
            return config, "could not seed a vtcode session"
        config["session-id"] = session_id
    return config, None


def workspace_setup(workdir, env):
    (workdir / "vtcode.toml").write_text(WORKSPACE_TOML)


def build_env():
    env = os.environ.copy()
    env.setdefault("VTCODE_TRUST_WORKSPACE", "full-auto")
    if not env.get("BIFROST_VK_MASTER"):
        try:
            env["BIFROST_VK_MASTER"] = subprocess.run(
                ["gopass", "show", "-o", "env/BIFROST_VK_MASTER"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout.strip()
        except Exception:
            pass
    return env


if __name__ == "__main__":
    cases_fn = lambda model: cases(model)  # noqa: E731
    sys.exit(
        main(
            VTCodeAdapter,
            cases_fn,
            DEFAULT_MODEL,
            env=build_env(),
            prepare=prepare,
            workspace_setup=workspace_setup,
            descriptions=__doc__,
        )
    )
