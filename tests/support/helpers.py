"""Plain helpers shared by test modules (import with `from tests.support.helpers import ...`)."""

import subprocess
from pathlib import Path

import yaml

SUPPORT_DIR = Path(__file__).resolve().parent
TESTS_DIR = SUPPORT_DIR.parent
REPO_ROOT = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
EXAMPLES_DIR = REPO_ROOT / "examples"


def completed(returncode=0, stdout="", stderr=""):
    """A subprocess.CompletedProcess, for `patch("subprocess.run", return_value=...)`."""
    return subprocess.CompletedProcess(
        args=["agent"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def bash_prompt(script, intro="Run this shell script with your bash tool, exactly as written:"):
    """
    A prompt whose actionable part is a fenced ```bash block.

    The fake agent (tests/support/fake_opencode.py) executes the block itself; a real
    agent is told to run it. Scenario workflows built this way work in both tiers.
    """
    return f"{intro}\n\n```bash\n{script.strip()}\n```\n\nThen reply with the single word DONE."


def write_workflow(path, workflow):
    """Dump a workflow dict to YAML at `path` and return the path."""
    path = Path(path)
    path.write_text(yaml.safe_dump(workflow, sort_keys=False))
    return path
