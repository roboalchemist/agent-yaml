"""
Live tier: real workflows, real OpenCode v2 agent, real model.

Opt-in with `pip install .[test]` plus `pytest --live` (tests here are skipped otherwise).
Requirements:
- `opencode` v2.x on PATH
- a gateway key in $GATEWAY_API_KEY, or an `op` (1Password CLI) reference that resolves to one

Environment overrides:
- AGENT_YAML_LIVE_PROVIDER   provider id in opencode.json            default gateway
- AGENT_YAML_LIVE_MODEL      model id served by that provider        default model-name
- AGENT_YAML_LIVE_BASE_URL   OpenAI-compatible base URL              default http://127.0.0.1:4000/v1
- GATEWAY_API_KEY            literal key (skips 1Password lookup)
- AGENT_YAML_LIVE_KEY_REF    `op read` reference for the key         default op://Agents/GATEWAY_KEY/credential

Every agent call runs in an isolated OpenCode home: HOME, the XDG data/state/config dirs,
and OPENCODE_CONFIG_DIR point at a session temp dir whose opencode.json only defines the
gateway provider and the live model, with apiKey "{env:GATEWAY_API_KEY}". The user's stored
credentials, plugins, skills, global AGENTS.md, and default model never apply, so the key
supplied above is the one used. XDG_CACHE_HOME stays on the real cache so OpenCode does not
re-download provider packages.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.helpers import REPO_ROOT

PROVIDER = os.environ.get("AGENT_YAML_LIVE_PROVIDER", "gateway")
MODEL_ID = os.environ.get("AGENT_YAML_LIVE_MODEL", "model-name")
LIVE_MODEL = f"{PROVIDER}/{MODEL_ID}"
KEY_ENV = "GATEWAY_API_KEY"
KEY_REF = os.environ.get("AGENT_YAML_LIVE_KEY_REF", "op://Agents/GATEWAY_KEY/credential")
BASE_URL = os.environ.get("AGENT_YAML_LIVE_BASE_URL", "http://127.0.0.1:4000/v1")


@pytest.fixture(scope="session")
def live_api_key():
    """Gateway key from $GATEWAY_API_KEY, falling back to a 1Password reference (never printed)."""
    if os.environ.get(KEY_ENV):
        return os.environ[KEY_ENV]
    if not shutil.which("op"):
        pytest.fail(
            "live tier needs a gateway key: set GATEWAY_API_KEY or AGENT_YAML_LIVE_KEY_REF "
            "(1Password CLI `op` not found)"
        )
    proc = subprocess.run(
        ["op", "read", KEY_REF, "--no-newline"], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0 or not proc.stdout:
        pytest.fail(f"`op read {KEY_REF}` failed: {proc.stderr.strip()}")
    return proc.stdout


@pytest.fixture(scope="session")
def opencode_env(tmp_path_factory, live_api_key):
    """Environment for agent-yaml subprocesses: isolated OpenCode home + live gateway key."""
    if not shutil.which("opencode"):
        pytest.fail("`opencode` not found on PATH (OpenCode v2 is required)")
    version = subprocess.run(
        ["opencode", "--version"], capture_output=True, text=True, timeout=30
    ).stdout
    match = re.search(r"(\d+)\.\d+\.\d+", version)
    if not match or int(match.group(1)) < 2:
        pytest.fail(f"OpenCode v2 required, `opencode --version` printed: {version.strip()!r}")

    home = tmp_path_factory.mktemp("opencode-home")
    config_dir = home / "config"
    config_dir.mkdir()
    (config_dir / "opencode.json").write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "autoupdate": False,
                "enabled_providers": [PROVIDER],
                "model": LIVE_MODEL,
                "permission": "allow",
                "provider": {
                    PROVIDER: {
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "Gateway",
                        "options": {
                            "baseURL": BASE_URL,
                            "apiKey": f"{{env:{KEY_ENV}}}",
                        },
                        "models": {
                            MODEL_ID: {
                                "name": MODEL_ID,
                                "attachment": True,
                                "reasoning": True,
                                "tool_call": True,
                                "limit": {"context": 1048576, "output": 393216},
                            }
                        },
                    }
                },
            },
            indent=2,
        )
    )

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("OPENCODE")
        and key not in ("ANTHROPIC_API_KEY", KEY_ENV)
    }
    env["XDG_CACHE_HOME"] = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    (home / "home").mkdir()
    env["HOME"] = str(home / "home")
    for name in ("data", "state", "config"):
        (home / "xdg" / name).mkdir(parents=True)
        env[f"XDG_{name.upper()}_HOME"] = str(home / "xdg" / name)
    env["OPENCODE_CONFIG_DIR"] = str(config_dir)
    env[KEY_ENV] = live_api_key
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )

    # Preflight: prove the key, the model, and tool calling work before running 13 scenarios.
    preflight_dir = home / "preflight"
    preflight_dir.mkdir()
    preflight_env = {**env, "PWD": str(preflight_dir)}
    proc = subprocess.run(
        [
            "opencode",
            "run",
            "--standalone",
            "--model",
            LIVE_MODEL,
            "--",
            "Use the bash tool to run exactly `echo PONG > preflight.txt`, "
            "then reply with the single word DONE.",
        ],
        cwd=preflight_dir,
        env=preflight_env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    marker = preflight_dir / "preflight.txt"
    if proc.returncode != 0 or not marker.exists() or "PONG" not in marker.read_text():
        pytest.fail(
            f"OpenCode preflight failed (rc={proc.returncode}) for {LIVE_MODEL} "
            f"at {BASE_URL}; expected preflight.txt containing PONG.\n"
            f"stdout: {proc.stdout[-800:]}\nstderr: {proc.stderr[-1500:]}"
        )
    return env


class WorkflowRun:
    """Result of one `agent-yaml run` subprocess."""

    def __init__(self, proc, workdir):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr
        self.workdir = workdir

    def describe(self):
        return f"exit code {self.returncode}\n--- stderr (tail) ---\n{self.stderr[-3000:]}"


@pytest.fixture
def run_workflow(opencode_env, tmp_path):
    """
    Run a workflow through `python -m src.cli run` with the live agent and model.

    The workflow's directory is overridden to `workdir` (default: tmp_path) and the
    process runs with cwd=workdir, so relative loop sources and validator paths
    (resolved against the process cwd) land in the same place as the agent's files.
    """

    def _run(workflow, *extra_args, workdir=None, timeout=900):
        workdir = Path(workdir or tmp_path)
        cmd = [
            sys.executable, "-m", "src.cli", "run", str(workflow),
            "--cli-agent", "opencode", "--model", LIVE_MODEL,
            "--directory", str(workdir), *extra_args,
        ]
        # opencode's shell tool resolves relative paths against $PWD, which subprocess
        # does not update when cwd= is used.
        run_env = {**opencode_env, "PWD": str(workdir)}
        proc = subprocess.run(
            cmd, cwd=workdir, env=run_env, capture_output=True, text=True, timeout=timeout
        )
        return WorkflowRun(proc, workdir)

    return _run
