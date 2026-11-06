#!/usr/bin/env python3
"""Live validation matrix for the pi adapter.

Runs every pi cli-agent-config option against real inference, using whichever
provider/model pi is configured with (default: the Bifrost deepseek model), and
checks behaviour for options that change what the agent can do.

Usage:
    python scripts/validate_pi_params.py
    python scripts/validate_pi_params.py --model bifrost/private/deepseek-v4.1-flash-1017
    python scripts/validate_pi_params.py --verbose

Exit code 0 means every case passed. Any failure prints the command, exit code,
and output tail so the mismatch is obvious.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_yaml.adapters.pi import PiAdapter  # noqa: E402
from agent_yaml.validator import SchemaValidator  # noqa: E402

DEFAULT_MODEL = os.environ.get("PI_VALIDATION_MODEL", "")
PROMPT_OK = "Reply with exactly: OK"


@dataclass
class Case:
    name: str
    config: dict
    prompt: str = PROMPT_OK
    expect_stdout: str | None = "OK"
    expect_file: str | None = None
    forbid_file: str | None = None
    expect_json: bool = False
    expect_stderr: bool = False
    session_dir_name: str | None = None
    expect_session: bool = False
    repeat: int = 1
    note: str = ""
    tags: list = field(default_factory=list)


def cases(model: str) -> list[Case]:
    write_prompt = "Use the bash tool to run exactly: echo ok > marker.txt"
    create_prompt = "Create a file named marker.txt containing ok"
    return [
        Case("model", {"model": model}),
        Case(
            "provider+model",
            {"provider": model.split("/", 1)[0], "model": model.split("/", 1)[1]},
        ),
        Case("thinking", {"model": model, "thinking": "high"}),
        Case("skip-confirmations", {"model": model, "skip-confirmations": True}),
        Case(
            "tools=bash",
            {"model": model, "tools": ["bash"]},
            prompt=write_prompt,
            expect_stdout=None,
            expect_file="marker.txt",
        ),
        Case(
            "tools=read (no write)",
            {"model": model, "tools": ["read"]},
            prompt=create_prompt,
            expect_stdout=None,
            forbid_file="marker.txt",
        ),
        Case(
            "no-tools",
            {"model": model, "no-tools": True},
            prompt=create_prompt,
            expect_stdout=None,
            forbid_file="marker.txt",
        ),
        Case(
            "exclude-tools",
            {"model": model, "exclude-tools": ["write", "edit", "bash"]},
            prompt=create_prompt,
            expect_stdout=None,
            forbid_file="marker.txt",
        ),
        Case("output-format=json", {"model": model, "output-format": "json"}, expect_json=True, expect_stdout=None),
        Case(
            "raw-args --no-tools",
            {"model": model, "raw-args": ["--no-tools"]},
            prompt=create_prompt,
            expect_stdout=None,
            forbid_file="marker.txt",
        ),
        Case(
            "session-dir + title",
            {"model": model, "session": True, "title": "pi matrix", "session-dir": "{workdir}/sessions"},
            expect_session=True,
            session_dir_name="sessions",
        ),
        Case(
            "session=true",
            {"model": model, "session": True, "session-dir": "{workdir}/sessions"},
            expect_session=True,
            session_dir_name="sessions",
        ),
        Case(
            "session-id (repeat)",
            {"model": model, "session-id": "matrix-session", "session-dir": "{workdir}/sessions"},
            expect_session=True,
            session_dir_name="sessions",
            repeat=2,
        ),
        Case(
            "skip-confirmations=false",
            {"model": model, "skip-confirmations": False},
            note="explicit false adds --no-approve",
        ),
        Case("system-prompt", {"model": model, "system-prompt": "Be terse."}),
        Case(
            "append-system-prompt",
            {"model": model, "append-system-prompt": ["Be brief.", "No preamble."]},
        ),
        Case("no-context-files", {"model": model, "no-context-files": True}),
        Case("no-mcp", {"model": model, "no-mcp": True}),
        Case("no-builtin-tools", {"model": model, "no-builtin-tools": True}),
        Case("continue", {"model": model, "continue": True}, note="needs a prior session in cwd"),
        Case("no-extensions", {"model": model, "no-extensions": True}),
        Case("debug (accepted; verbose is TUI-only)", {"model": model, "debug": True}),
        Case(
            "unsupported options ignored",
            {
                "model": model,
                "additional-dirs": ["/tmp"],
                "mcp-servers": ["notion"],
                "mcp-config-file": "/tmp/mcp.json",
            },
            note="pi ignores all three; the run must still succeed",
        ),
        Case("timeout (not a pi flag)", {"model": model, "timeout": 60}),
    ]


def substitute(value, workdir: Path):
    if isinstance(value, str):
        return value.replace("{workdir}", str(workdir))
    if isinstance(value, list):
        return [substitute(item, workdir) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, workdir) for key, item in value.items()}
    return value


def run_case(case: Case, workdir: Path, verbose: bool) -> tuple[bool, str]:
    adapter = PiAdapter()
    config = substitute(case.config, workdir)
    if case.name == "continue":
        # `--continue` needs a prior session for this working directory.
        seed = subprocess.run(
            adapter.build_command({"model": config["model"], "session": True}, "Reply with exactly: OK"),
            cwd=workdir,
            input="",
            capture_output=True,
            text=True,
            timeout=240,
        )
        if seed.returncode != 0:
            return False, f"could not seed a session: {seed.stderr.strip()[:200]}"
    for attempt in range(case.repeat):
        cmd = adapter.build_command(config, case.prompt)
        if verbose:
            print("    argv:", cmd)
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            input="",
            capture_output=True,
            text=True,
            timeout=240,
        )
        if proc.returncode != 0:
            return False, f"rc={proc.returncode} stderr={proc.stderr.strip()[:200]}"
        if case.expect_json:
            lines = [line for line in proc.stdout.splitlines() if line.strip().startswith("{")]
            if not lines:
                return False, "no JSON lines on stdout"
            try:
                json.loads(lines[0])
            except json.JSONDecodeError as exc:
                return False, f"invalid JSON on stdout: {exc}"
        if attempt == 0 and case.expect_stdout and case.expect_stdout not in proc.stdout:
            return False, f"stdout missing {case.expect_stdout!r}"
        if case.expect_stderr and not proc.stderr.strip():
            return False, "expected verbose output on stderr"
    if case.expect_file and not (workdir / case.expect_file).exists():
        return False, f"{case.expect_file} was not created"
    if case.forbid_file and (workdir / case.forbid_file).exists():
        return False, f"{case.forbid_file} exists but tools should prevent it"
    if case.expect_session:
        session_dir = workdir / (case.session_dir_name or "sessions")
        if not session_dir.exists() or not any(session_dir.rglob("*")):
            return False, f"no session files under {session_dir}"
    return True, case.note or "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="provider/model to test (or set PI_VALIDATION_MODEL)",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--only", help="comma-separated case names")
    args = parser.parse_args()

    if not args.model or "/" not in args.model:
        parser.error("pass --model provider/model or set PI_VALIDATION_MODEL")

    matrix = cases(args.model)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        matrix = [case for case in matrix if case.name in wanted]

    covered = set()
    for case in matrix:
        covered.update(case.config)

    failures = 0
    print(f"model: {args.model}\n")
    for case in matrix:
        workdir = Path(tempfile.mkdtemp(prefix="pi-case-"))
        ok, detail = run_case(case, workdir, args.verbose)
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {case.name:28} {detail}")
        failures += 0 if ok else 1

    unknown = covered - set(SchemaValidator.PI_OPTION_SPEC)
    missing = set(SchemaValidator.PI_OPTION_SPEC) - covered
    print(f"\noptions covered: {len(covered)}/{len(SchemaValidator.PI_OPTION_SPEC)}")
    if unknown:
        print("unknown option in matrix:", sorted(unknown))
        failures += 1
    if missing:
        print("options not exercised:", sorted(missing))
        failures += 1

    print(f"\n{len(matrix) - failures if failures <= len(matrix) else 0}/{len(matrix)} cases passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
