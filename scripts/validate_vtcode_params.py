#!/usr/bin/env python3
"""Live validation matrix for the vtcode adapter.

Runs every vtcode cli-agent-config option through real `vtcode exec` inference
against a configured provider/model (default: the private deepseek deployment
`chunglet/deepseek-v4.1-flash` on the Bifrost gateway), then checks the run
succeeded and, where the option changes behaviour, that the artefact exists.

Requirements:
  * `vtcode` on PATH
  * a custom provider in the platform config dir's `vtcode.toml`:

        [[custom_providers]]
        name = "bifrost"
        display_name = "Bifrost"
        base_url = "https://bifrost.roboalch.com/v1"
        api_key_env = "BIFROST_VK_MASTER"
        model = "chunglet/deepseek-v4.1-flash"
        models = ["chunglet/deepseek-v4.1-flash"]

    (macOS: ~/Library/Application Support/com.vinhnx.vtcode/vtcode.toml,
     Linux: ~/.config/vtcode/vtcode.toml)

  * the API key in the environment variable named by `api_key_env`
    (the script falls back to `gopass show -o env/BIFROST_VK_MASTER`)

Usage:
    python scripts/validate_vtcode_params.py
    python scripts/validate_vtcode_params.py --model chunglet/deepseek-v4.1-flash --provider bifrost
    python scripts/validate_vtcode_params.py --only security-level --verbose

Exit code 0 means every case passed. Failures print the command, exit code, and
output tail so the mismatch is obvious.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_yaml.adapters.vtcode import VTCodeAdapter  # noqa: E402

DEFAULT_PROVIDER = os.environ.get("VTCODE_VALIDATION_PROVIDER", "bifrost")
DEFAULT_MODEL = os.environ.get("VTCODE_VALIDATION_MODEL", "chunglet/deepseek-v4.1-flash")
PROMPT_OK = "Reply with exactly: OK"
PROMPT_WRITE = "Create a file named marker.txt containing exactly: ok"

WORKSPACE_CONFIG = """\
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


@dataclass
class Case:
    name: str
    config: dict
    prompt: str = PROMPT_OK
    expect_file: str | None = None
    expect_json: bool = False
    repeat: int = 1
    note: str = ""
    tags: list = field(default_factory=list)


def cases(provider: str, model: str) -> list[Case]:
    return [
        Case(
            "provider+model",
            {"provider": provider, "model": model},
            note="explicit provider and model reach the model call",
            tags=["core"],
        ),
        Case(
            "skip-confirmations",
            {"provider": provider, "model": model, "skip-confirmations": True},
            note="--dangerously-skip-permissions is accepted",
            tags=["flags"],
        ),
        Case(
            "security-level",
            {"provider": provider, "model": model, "security-level": "permissive"},
            note="--security-level permissive is accepted",
            tags=["flags"],
        ),
        Case(
            "max-tool-calls",
            {"provider": provider, "model": model, "max-tool-calls": 8},
            note="--max-tool-calls 8 is accepted",
            tags=["flags"],
        ),
        Case(
            "output-format=json",
            {"provider": provider, "model": model, "output-format": "json"},
            expect_json=True,
            note="--json streams parseable NDJSON events",
            tags=["output"],
        ),
        Case(
            "debug",
            {"provider": provider, "model": model, "debug": True},
            note="--verbose is accepted",
            tags=["flags"],
        ),
        Case(
            "quiet",
            {"provider": provider, "model": model, "quiet": True},
            note="--quiet is accepted",
            tags=["flags"],
        ),
        Case(
            "raw-args",
            {"provider": provider, "model": model, "raw-args": ["--max-tool-calls", "4"]},
            note="raw-args pass through untouched",
            tags=["flags"],
        ),
        Case(
            "timeout",
            {"provider": provider, "model": model, "timeout": 600},
            note="timeout is enforced by the executor, not the CLI",
            tags=["executor"],
        ),
        Case(
            "tool-write",
            {"provider": provider, "model": model, "skip-confirmations": True},
            prompt=PROMPT_WRITE,
            expect_file="marker.txt",
            note="agent writes a file through the shell tool",
            tags=["tools"],
        ),
        Case(
            "session-id+continue",
            {"provider": provider, "model": model, "session-id": "agent-yaml-matrix"},
            note="--session-id creates the session",
            tags=["session"],
        ),
        Case(
            "continue",
            {
                "provider": provider,
                "model": model,
                "continue": True,
                "session-id": "__LATEST__",
            },
            note="exec resume <session-id> continues the session created above",
            tags=["session"],
        ),
    ]


def latest_session_id(workspace: Path) -> str | None:
    sessions = workspace / ".vtcode" / "sessions"
    if not sessions.is_dir():
        return None
    entries = [p for p in sessions.iterdir() if p.is_dir()]
    if not entries:
        return None
    return max(entries, key=lambda p: p.stat().st_mtime).name


def run_case(case: Case, workspace: Path, env: dict, timeout: int, verbose: bool) -> tuple[bool, str]:
    config = dict(case.config)
    if config.get("session-id") == "__LATEST__":
        session_id = latest_session_id(workspace)
        if not session_id:
            return False, "no session was created by the preceding session-id case"
        config["session-id"] = session_id
    cmd = VTCodeAdapter().build_command(config, case.prompt)
    last = None
    for attempt in range(case.repeat):
        try:
            last = subprocess.run(
                cmd,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout}s: {' '.join(cmd)}"

        if last.returncode != 0:
            tail = (last.stderr or last.stdout or "").strip().splitlines()[-6:]
            return False, "exit {}: {}\n    {}".format(
                last.returncode, " ".join(cmd), "\n    ".join(tail)
            )
        if verbose:
            print(f"  attempt {attempt + 1}/{case.repeat}: rc=0")

    if case.expect_file:
        target = workspace / case.expect_file
        if not target.exists():
            return False, f"{case.expect_file} was not created (cmd: {' '.join(cmd)})"

    if case.expect_json:
        events, bad = 0, 0
        for line in (last.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
                events += 1
            except json.JSONDecodeError:
                bad += 1
        if not events or bad:
            return False, f"expected NDJSON on stdout, got {events} events and {bad} non-JSON lines"

    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=600, help="per-case subprocess timeout")
    parser.add_argument("--only", action="append", help="run only these case names (repeatable)")
    parser.add_argument("--tag", action="append", help="run only these tags (repeatable)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not shutil.which("vtcode"):
        print("vtcode not found on PATH", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env.setdefault("VTCODE_TRUST_WORKSPACE", "full-auto")
    api_key_env = env.get("VTCODE_API_KEY_ENV", "BIFROST_VK_MASTER")
    if not env.get(api_key_env):
        try:
            env[api_key_env] = subprocess.run(
                ["gopass", "show", "-o", f"env/{api_key_env}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout.strip()
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            print(
                f"{api_key_env} is not set and gopass could not read env/{api_key_env}",
                file=sys.stderr,
            )
            return 2
        if not env[api_key_env]:
            print(f"{api_key_env} resolved to an empty value", file=sys.stderr)
            return 2

    selected = cases(args.provider, args.model)
    if args.only:
        selected = [c for c in selected if c.name in args.only]
    if args.tag:
        selected = [c for c in selected if set(args.tag) & set(c.tags)]
    if not selected:
        print("no cases selected", file=sys.stderr)
        return 2

    workspace = Path(tempfile.mkdtemp(prefix="agent-yaml-vtcode-"))
    try:
        (workspace / "vtcode.toml").write_text(WORKSPACE_CONFIG)
        print(f"workspace: {workspace}")
        print(f"model: {args.provider}/{args.model}\n")

        failures = []
        for index, case in enumerate(selected, start=1):
            print(f"[{index}/{len(selected)}] {case.name}: {case.note}")
            ok, detail = run_case(case, workspace, env, args.timeout, args.verbose)
            print("  PASS" if ok else f"  FAIL\n    {detail}")
            if not ok:
                failures.append((case.name, detail))

        print(f"\n{len(selected) - len(failures)}/{len(selected)} cases passed")
        if failures:
            print("\nfailures:")
            for name, detail in failures:
                print(f"- {name}: {detail}")
            return 1
        return 0
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
