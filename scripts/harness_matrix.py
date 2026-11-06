#!/usr/bin/env python3
"""Shared live-validation framework for harness adapters.

Every harness matrix uses this runner:

* one case per config surface (generated from the adapter's option spec)
* optional harness-specific behavioral cases (file writes, sessions, JSON)
* the same artifact and output checks
* the same CLI flags (--model, --timeout, --only, --tag, --verbose)

A case passes when the command exits 0 and every declared check succeeds. The
coverage report compares the case set with the adapter's option spec; ignored
options need no live case because they never reach argv, and ``live_exempt``
records why a mapped option cannot be exercised here.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PROMPT_OK = "Reply with exactly: OK"
PROMPT_WRITE = "Create a file named marker.txt containing exactly: ok"

# Representative value for every surface. Mirrors docs/CONFIG_SURFACES.md.
SAMPLES = {
    "model": "test-model",
    "provider": "test-provider",
    "session-id": "sid",
    "continue": True,
    "title": "T",
    "agent": "build",
    "permissions": ["plan"],
    "output-format": "json",
    "skip-confirmations": True,
    "debug": True,
    "raw-args": ["--custom"],
    "additional-dirs": ["/tmp"],
    "mcp-servers": ["notion"],
    "mcp-config-file": "/tmp/mcp.json",
    "tools": "read,bash",
    "exclude-tools": ["write"],
    "thinking": "high",
    "no-tools": True,
    "session": False,
    "no-extensions": True,
    "web-search": True,
    "server": "http://localhost:4096",
    "standalone": False,
    "security-level": "permissive",
    "max-tool-calls": 8,
    "quiet": True,
    "effort": "high",
    "sandbox": "read-only",
    "json-schema": "schema.json",
    "last-message-file": "/tmp/last.txt",
    "system-prompt": "Be terse.",
    "append-system-prompt": ["Be brief."],
    "settings": "{}",
    "disable-slash-commands": True,
    "max-budget": 2.5,
    "fallback-model": "sonnet",
    "project": "demo",
    "log-file": "/tmp/agy.log",
    "log-level": "debug",
    "color": "never",
    "files": ["/tmp/file.txt"],
    "images": ["/tmp/img.png"],
    "enable": ["web_search"],
    "ignore-user-config": True,
    "ignore-rules": True,
    "events-file": "/tmp/events.jsonl",
    "max-concurrent-ops": 3,
    "api-rate-limit": 20,
    "config-overrides": ["model=test"],
    "session-dir": "/tmp/sessions",
    "no-context-files": True,
    "no-mcp": True,
    "no-builtin-tools": True,
    "skills": ["/tmp/skills"],
    "extensions": ["builtin:mcp"],
    "timeout": 300,
}

AGENT_SAMPLES = {
    "provider": {"codex": "ollama"},
    "sandbox": {"codex": "read-only", "antigravity": True},
    "session": {"pi": True, "claude": False, "codex": False},
    "files": {"opencode": ["{workdir}/file.txt"]},
    "images": {"codex": ["{workdir}/img.png"]},
    "json-schema": {
        "claude": "{workdir}/schema.json",
        "codex": "{workdir}/schema.json",
        "antigravity": "{workdir}/schema.json",
    },
    "skills": {"pi": ["{workdir}/skills"]},
    "mcp-config-file": {"claude": "{workdir}/mcp.json"},
    "tools": {"vtcode": ["exec_command"]},
}

JSON_OUTPUT_SURFACES = {"output-format"}


@dataclass
class Case:
    """One matrix case: a config overlay, a prompt, and optional checks."""

    name: str
    config: dict
    prompt: str = PROMPT_OK
    expect_stdout: str | None = "OK"
    expect_file: str | None = None
    forbid_file: str | None = None
    expect_json: bool = False
    expect_json_object: bool = False
    expect_ndjson: bool = False
    expect_stderr: bool = False
    session_dir: str | None = None
    repeat: int = 1
    note: str = ""
    tags: list = field(default_factory=list)


def substitute(value, workdir):
    if isinstance(value, str):
        return value.replace("{workdir}", str(workdir))
    if isinstance(value, list):
        return [substitute(item, workdir) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, workdir) for key, item in value.items()}
    return value


def surface_cases(
    adapter,
    base_config: dict,
    extra: list[Case] | None = None,
    expect_stdout: str | None = "OK",
) -> list[Case]:
    """
    One live case per mapped, non-exempt surface.

    ``base_config`` carries the model/provider selection. Ignored options never
    reach argv, so they are skipped; ``live_exempt`` keys are added by the
    harness wrapper as behavioral cases or left exempt with a recorded reason.
    """
    extra = extra or []
    extra_names = {case.name for case in extra}
    cases = []
    for key, option in adapter.option_spec.items():
        if option.kind == "ignored":
            continue
        if key in adapter.live_exempt:
            continue
        if key in extra_names or key in base_config:
            continue
        sample = AGENT_SAMPLES.get(key, {}).get(adapter.name, SAMPLES[key])
        config = dict(base_config)
        config[key] = sample
        json_surface = key in JSON_OUTPUT_SURFACES
        cases.append(
            Case(
                name=key,
                config=config,
                expect_stdout=None if json_surface else expect_stdout,
                expect_json=json_surface,
                note=f"{key} reaches the live CLI",
                tags=["surface"],
            )
        )
    return cases + extra


def coverage(adapter, cases: list[Case]) -> tuple[set, set]:
    """Return (covered_surfaces, missing_surfaces) for an adapter spec."""
    covered = set()
    for case in cases:
        covered.update(case.config)
    covered.discard("model")
    covered.discard("provider")
    ignored = {key for key, option in adapter.option_spec.items() if option.kind == "ignored"}
    required = set(adapter.option_spec) - ignored - set(adapter.live_exempt) - {"model", "provider"}
    return covered & required, required - covered


def _parse_json_stdout(stdout: str) -> tuple[bool, str]:
    """Accept either one JSON document or newline-delimited JSON."""
    text = stdout.strip()
    if not text:
        return False, "empty stdout"
    try:
        json.loads(text)
        return True, ""
    except json.JSONDecodeError:
        pass
    lines = [line for line in text.splitlines() if line.strip()]
    try:
        for line in lines:
            json.loads(line)
    except json.JSONDecodeError as exc:
        return False, f"stdout is not JSON or NDJSON: {exc}"
    return True, ""


def run_case(
    adapter,
    case: Case,
    workdir: Path,
    env: dict,
    timeout: int,
    prepare=None,
    verbose: bool = False,
) -> tuple[bool, str]:
    """Run one case; return (passed, detail)."""
    config = substitute(case.config, workdir)
    if prepare is not None:
        config, error = prepare(case, config, workdir, env)
        if error:
            return False, error

    for attempt in range(case.repeat):
        cmd = adapter.build_command(config, case.prompt)
        if verbose:
            print("    argv:", cmd)
        try:
            proc = subprocess.run(
                cmd,
                cwd=workdir,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout}s: {' '.join(cmd)}"

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
            return False, "exit {}: {}\n    {}".format(
                proc.returncode, " ".join(cmd), "\n    ".join(tail)
            )
        if attempt == 0 and case.expect_stdout and case.expect_stdout not in proc.stdout:
            return False, f"stdout missing {case.expect_stdout!r}: {proc.stdout[:160]!r}"
        if case.expect_stderr and not proc.stderr.strip():
            return False, "expected diagnostics on stderr"

    if case.expect_file and not (workdir / case.expect_file).exists():
        return False, f"{case.expect_file} was not created (cmd: {' '.join(cmd)})"
    if case.forbid_file and (workdir / case.forbid_file).exists():
        return False, f"{case.forbid_file} exists but tools should prevent it"

    if case.expect_json or case.expect_json_object or case.expect_ndjson:
        ok, detail = _parse_json_stdout(proc.stdout)
        if not ok:
            return False, detail

    if case.session_dir:
        session_dir = workdir / case.session_dir
        if not session_dir.exists() or not any(session_dir.rglob("*")):
            return False, f"no session files under {session_dir}"

    return True, case.note or "ok"


def run(
    adapter,
    cases: list[Case],
    env: dict,
    timeout: int,
    only: list[str] | None = None,
    tags: list[str] | None = None,
    prepare=None,
    workspace_setup=None,
    verbose: bool = False,
) -> int:
    """Run the selected cases in fresh workspaces; return an exit code."""
    selected = list(cases)
    if only:
        wanted = {name.strip() for name in only}
        selected = [case for case in selected if case.name in wanted]
    if tags:
        wanted_tags = set(tags)
        selected = [case for case in selected if wanted_tags & set(case.tags)]
    if not selected:
        print("no cases selected", file=sys.stderr)
        return 2

    failures = []
    for index, case in enumerate(selected, start=1):
        workdir = Path(tempfile.mkdtemp(prefix=f"{adapter.name}-case-"))
        try:
            if workspace_setup is not None:
                workspace_setup(workdir, env)
            print(f"[{index}/{len(selected)}] {case.name}: {case.note}")
            ok, detail = run_case(adapter, case, workdir, env, timeout, prepare, verbose)
            print("  PASS" if ok else f"  FAIL\n    {detail}")
            if not ok:
                failures.append((case.name, detail))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    covered, missing = coverage(adapter, cases)
    print(f"\nsurfaces covered by the matrix: {len(covered)}")
    if missing:
        print("surfaces missing a case:", sorted(missing))
    print(f"{len(selected) - len(failures)}/{len(selected)} cases passed")
    if failures:
        print("\nfailures:")
        for name, detail in failures:
            print(f"- {name}: {detail}")
        return 1
    return 0 if not missing else 1


def main(
    adapter_cls,
    cases_fn,
    default_model: str,
    env: dict | None = None,
    prepare=None,
    workspace_setup=None,
    descriptions: str = "",
) -> int:
    """Shared CLI entry point for a harness matrix wrapper."""
    parser = argparse.ArgumentParser(description=descriptions or f"{adapter_cls.name} matrix")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--only", action="append", help="case names (repeatable)")
    parser.add_argument("--tag", action="append", help="tags (repeatable)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    adapter = adapter_cls()
    if not adapter.check_available():
        print(f"{adapter.install_hint} not found on PATH", file=sys.stderr)
        return 2

    cases = cases_fn(args.model)
    env = env if env is not None else os.environ.copy()
    print(f"harness: {adapter.name}\nmodel: {args.model}\n")
    return run(
        adapter,
        cases,
        env,
        args.timeout,
        only=args.only,
        tags=args.tag,
        prepare=prepare,
        workspace_setup=workspace_setup,
        verbose=args.verbose,
    )


def make_fixtures(workdir: Path):
    """Files and directories the surface samples point at."""
    (workdir / "schema.json").write_text('{"type":"object"}')
    (workdir / "file.txt").write_text("x")
    (workdir / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (workdir / "skills").mkdir(exist_ok=True)
    (workdir / "mcp.json").write_text('{"mcpServers": {}}')


def latest_session(workdir: Path, parent: str = ".vtcode/sessions") -> str | None:
    """Name of the newest session directory under parent, if any."""
    root = workdir / parent
    if not root.is_dir():
        return None
    entries = [path for path in root.iterdir() if path.is_dir()]
    if not entries:
        return None
    return max(entries, key=lambda path: path.stat().st_mtime).name
