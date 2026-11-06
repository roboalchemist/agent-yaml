#!/usr/bin/env python3
"""Live validation matrix for the antigravity adapter.

Runs every antigravity cli-agent-config option through real `agy -p` inference
and checks the run succeeded and, where the option changes behaviour, that the
artefact exists.

Authentication (either works):
  * a signed-in Google account (`agy` opens the browser once), which needs no
    environment variable and is the default, or
  * a Gemini API key: `{"modelProvider": "gemini"}` in
    ~/.gemini/antigravity-cli/settings.json plus `GEMINI_API_KEY` exported
    (the script falls back to `gopass show -o env/GEMINI_API_KEY`)

Usage:
    python scripts/validate_antigravity_params.py
    python scripts/validate_antigravity_params.py --model gemini-4-argon --effort high
    python scripts/validate_antigravity_params.py --only skip-confirmations --verbose

Exit code 0 means every case passed.
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

from agent_yaml.adapters.antigravity import AntigravityAdapter  # noqa: E402

DEFAULT_MODEL = os.environ.get("ANTIGRAVITY_VALIDATION_MODEL", "gemini-3.8-flash-high")
PROMPT_OK = "Reply with exactly: OK"
PROMPT_WRITE = "Create a file named marker.txt containing exactly: ok"


@dataclass
class Case:
    name: str
    config: dict
    prompt: str = PROMPT_OK
    expect_stdout: str | None = "OK"
    expect_file: str | None = None
    expect_json_object: bool = False
    expect_ndjson: bool = False
    note: str = ""
    tags: list = field(default_factory=list)


def cases(model: str) -> list[Case]:
    return [
        Case(
            "model",
            {"model": model},
            note="--model reaches the model call and the answer lands on stdout",
            tags=["core"],
        ),
        Case(
            "effort",
            {"model": model, "effort": "high"},
            note="--effort high is accepted",
            tags=["flags"],
        ),
        Case(
            "output-format=json",
            {"model": model, "output-format": "json"},
            expect_stdout=None,
            expect_json_object=True,
            note="one JSON object with conversation_id and response",
            tags=["output"],
        ),
        Case(
            "output-format=stream-json",
            {"model": model, "output-format": "stream-json"},
            expect_stdout=None,
            expect_ndjson=True,
            note="NDJSON events on stdout",
            tags=["output"],
        ),
        Case(
            "skip-confirmations",
            {"model": model, "skip-confirmations": True},
            prompt=PROMPT_WRITE,
            expect_stdout=None,
            expect_file="marker.txt",
            note="--dangerously-skip-permissions lets the agent write a file",
            tags=["tools"],
        ),
        Case(
            "sandbox",
            {"model": model, "sandbox": True},
            note="--sandbox is accepted and the turn still completes",
            tags=["flags"],
        ),
        Case(
            "additional-dirs",
            {"model": model, "additional-dirs": ["/tmp"]},
            note="--add-dir is accepted",
            tags=["flags"],
        ),
        Case(
            "timeout",
            {"model": model, "timeout": 300},
            note="timeout maps to --print-timeout Ns",
            tags=["executor"],
        ),
        Case(
            "raw-args",
            {"model": model, "raw-args": ["--disable-slash-commands"]},
            note="raw-args pass through untouched",
            tags=["flags"],
        ),
        Case(
            "session-id",
            {"model": model, "session-id": "__NEW__"},
            note="--conversation resumes a specific conversation id",
            tags=["session"],
        ),
        Case(
            "continue",
            {"model": model, "continue": True},
            note="--continue resumes the most recent conversation",
            tags=["session"],
        ),
        Case(
            "permissions",
            {"model": model, "permissions": ["plan"]},
            expect_stdout=None,
            note="permissions map to --mode plan (plan mode produces artifacts, not a text answer)",
            tags=["flags"],
        ),
        Case(
            "json-schema",
            {
                "model": model,
                "output-format": "json",
                "json-schema": '{"type":"object","properties":{"ok":{"type":"boolean"}}}',
            },
            expect_stdout=None,
            expect_json_object=True,
            note="--json-schema constrains structured output",
            tags=["output"],
        ),
        Case(
            "settings",
            {"model": model, "settings": "{}"},
            note="--settings accepts an inline JSON object",
            tags=["flags"],
        ),
        Case(
            "log-file",
            {"model": model, "log-file": "agy-matrix.log"},
            expect_file="agy-matrix.log",
            note="--log-file writes the CLI log",
            tags=["flags"],
        ),
        Case(
            "disable-slash-commands",
            {"model": model, "disable-slash-commands": True},
            note="--disable-slash-commands is accepted",
            tags=["flags"],
        ),
    ]


def bootstrap_conversation_id(workspace: Path, env: dict, model: str, timeout: int) -> str | None:
    """Create a conversation with --output-format json and return its id."""
    cmd = [
        "agy",
        "--model",
        model,
        "--output-format",
        "json",
        "-p",
        "Reply with exactly: BOOTSTRAP",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=workspace,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout).get("conversation_id")
    except json.JSONDecodeError:
        return None


def run_case(case: Case, workspace: Path, env: dict, timeout: int, verbose: bool) -> tuple[bool, str]:
    config = dict(case.config)
    if config.get("session-id") == "__NEW__":
        conversation_id = bootstrap_conversation_id(workspace, env, config["model"], timeout)
        if not conversation_id:
            return False, "could not create a conversation to resume"
        config["session-id"] = conversation_id
        if verbose:
            print(f"  bootstrapped conversation {conversation_id}")

    cmd = AntigravityAdapter().build_command(config, case.prompt)
    try:
        result = subprocess.run(
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

    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-6:]
        return False, "exit {}: {}\n    {}".format(
            result.returncode, " ".join(cmd), "\n    ".join(tail)
        )

    if case.expect_stdout and case.expect_stdout not in result.stdout:
        return False, f"stdout missing {case.expect_stdout!r}: {result.stdout[:200]!r}"

    if case.expect_file:
        target = workspace / case.expect_file
        if not target.exists():
            return False, f"{case.expect_file} was not created (cmd: {' '.join(cmd)})"

    if case.expect_json_object:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False, f"stdout is not a JSON object: {result.stdout[:200]!r}"
        if "conversation_id" not in payload:
            return False, f"JSON output missing conversation_id: {payload}"

    if case.expect_ndjson:
        events = 0
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
                events += 1
            except json.JSONDecodeError:
                return False, f"non-JSON line in stream-json output: {line[:120]!r}"
        if not events:
            return False, "stream-json produced no events"

    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=600, help="per-case subprocess timeout")
    parser.add_argument("--only", action="append", help="run only these case names (repeatable)")
    parser.add_argument("--tag", action="append", help="run only these tags (repeatable)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not shutil.which("agy"):
        print("agy not found on PATH (install: curl -fsSL https://antigravity.google/cli/install.sh | bash)", file=sys.stderr)
        return 2

    env = os.environ.copy()
    if not env.get("GEMINI_API_KEY"):
        # Optional: only used when settings.json sets modelProvider=gemini.
        # With a signed-in account the key is not needed and is left unset.
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
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        if not env.get("GEMINI_API_KEY"):
            print("GEMINI_API_KEY not found; using agy account auth.", file=sys.stderr)

    selected = cases(args.model)
    if args.only:
        selected = [c for c in selected if c.name in args.only]
    if args.tag:
        selected = [c for c in selected if set(args.tag) & set(c.tags)]
    if not selected:
        print("no cases selected", file=sys.stderr)
        return 2

    workspace = Path(tempfile.mkdtemp(prefix="agent-yaml-agy-"))
    try:
        print(f"workspace: {workspace}")
        print(f"model: {args.model}\n")

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
