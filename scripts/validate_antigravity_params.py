#!/usr/bin/env python3
"""Live matrix for the antigravity adapter (shared harness framework)."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness_matrix import PROMPT_WRITE, Case, main, surface_cases  # noqa: E402
from agent_yaml.adapters.antigravity import AntigravityAdapter  # noqa: E402

DEFAULT_MODEL = os.environ.get("ANTIGRAVITY_VALIDATION_MODEL", "gemini-3.8-flash-high")


def cases(model):
    adapter = AntigravityAdapter()
    base = {"model": model}
    extra = [
        Case(
            "skip-confirmations",
            {**base, "skip-confirmations": True},
            prompt=PROMPT_WRITE,
            expect_stdout=None,
            expect_file="marker.txt",
            note="--dangerously-skip-permissions lets the agent write",
            tags=["tools"],
        ),
        Case(
            "permissions",
            {**base, "permissions": ["plan"]},
            expect_stdout=None,
            note="permissions map to --mode plan (plan mode writes artifacts, not text)",
            tags=["flags"],
        ),
        Case(
            "json-schema",
            {**base, "output-format": "json", "json-schema": "{workdir}/schema.json"},
            expect_stdout=None,
            expect_json=True,
            note="--json-schema constrains structured output",
            tags=["output"],
        ),
        Case(
            "session-id",
            {**base, "session-id": "__NEW__"},
            note="--conversation resumes the bootstrapped conversation",
            tags=["session"],
        ),
        Case(
            "continue",
            {**base, "continue": True},
            note="--continue resumes the bootstrapped conversation",
            tags=["session"],
        ),
    ]
    return surface_cases(adapter, base, extra)


def bootstrap_conversation(workdir, env, model, timeout=240):
    cmd = ["agy", "--model", model, "--output-format", "json", "-p", "Reply with exactly: OK"]
    result = subprocess.run(
        cmd, cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout).get("conversation_id")
    except json.JSONDecodeError:
        return None


def prepare(case, config, workdir, env):
    if case.name in ("session-id", "continue"):
        conversation_id = bootstrap_conversation(workdir, env, config["model"])
        if not conversation_id:
            return config, "could not bootstrap an Antigravity conversation"
        if case.name == "session-id":
            config["session-id"] = conversation_id
    return config, None


def workspace_setup(workdir, env):
    (workdir / "schema.json").write_text('{"type":"object","properties":{"ok":{"type":"boolean"}}}')


def build_env():
    env = os.environ.copy()
    env.setdefault("PATH", os.path.expanduser("~/.local/bin") + ":" + env.get("PATH", ""))
    if not env.get("GEMINI_API_KEY"):
        try:
            key = subprocess.run(
                ["gopass", "show", "-o", "env/GEMINI_API_KEY"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout.strip()
            if key:
                env["GEMINI_API_KEY"] = key
        except Exception:
            pass
    return env


if __name__ == "__main__":
    sys.exit(
        main(
            AntigravityAdapter,
            cases,
            DEFAULT_MODEL,
            env=build_env(),
            prepare=prepare,
            workspace_setup=workspace_setup,
            descriptions=__doc__,
        )
    )
