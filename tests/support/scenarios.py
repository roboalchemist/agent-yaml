"""
End-to-end workflow scenarios shared by the integration and live tiers.

Every agent action is a fenced ```bash block (see helpers.bash_prompt): the fake agent
(tests/support/fake_opencode.py) runs it itself, a real agent is told to run it. A
scenario is a workflow builder plus a check on the files the run left behind, so the
same assertions hold for the deterministic fake and for a real model.

    build(workdir) -> workflow dict (all paths absolute under workdir)
    check(workdir, returncode, stderr) -> raises AssertionError on failure
"""

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tests.support.helpers import bash_prompt


@dataclass(frozen=True)
class Scenario:
    name: str
    build: Callable[[Path], dict]
    check: Callable[[Path, int, str], None]
    agent_calls: int  # expected agent invocations (fake tier asserts it exactly)


def _workflow(workdir, tasks, **top_level):
    workflow = {
        "directory": str(workdir),
        "cli-agent": "opencode",
        "cli-agent-config": {"skip-confirmations": True, "timeout": 300},
    }
    workflow.update(top_level)
    workflow["task"] = tasks
    return workflow


def _read(path):
    return Path(path).read_text().strip()


# --- single task ------------------------------------------------------------------------


def _single_build(w):
    return _workflow(w, [{"hello": {"prompt": bash_prompt(f"printf 'hello' > {w}/hello.txt")}}])


def _single_check(w, rc, stderr):
    assert rc == 0, stderr
    assert _read(w / "hello.txt") == "hello"


# --- sequential tasks communicate through files ----------------------------------------


def _sequential_build(w):
    return _workflow(
        w,
        [
            {"first": {"prompt": bash_prompt(f"printf 'a' > {w}/a.txt")}},
            {"second": {"prompt": bash_prompt(f'printf "%s-b" "$(cat {w}/a.txt)" > {w}/b.txt')}},
        ],
    )


def _sequential_check(w, rc, stderr):
    assert rc == 0, stderr
    assert _read(w / "b.txt") == "a-b"


# --- object keys run concurrently --------------------------------------------------------
# Each task marks itself started, then waits (up to 120s) until all three have started.
# Run sequentially, the first task can never see the others and fails.


def _rendezvous(w, me):
    return bash_prompt(
        f"""
touch {w}/started-{me}
for i in $(seq 1 600); do
  if [ -f {w}/started-a ] && [ -f {w}/started-b ] && [ -f {w}/started-c ]; then
    printf 'ok' > {w}/done-{me}.txt
    exit 0
  fi
  sleep 0.2
done
exit 1
"""
    )


def _parallel_build(w):
    return _workflow(w, [{"together": {name: {"prompt": _rendezvous(w, name)} for name in "abc"}}])


def _parallel_check(w, rc, stderr):
    assert rc == 0, stderr
    for name in "abc":
        assert _read(w / f"done-{name}.txt") == "ok"


# --- template variables, includes, and {{env.X}} ------------------------------------------


def _templates_build(w):
    return _workflow(
        w,
        [
            {
                "compose": {
                    "prompt": "Follow the instructions included below.",
                    "include": ["script"],
                }
            }
        ],
        **{
            "template-variables": {"name": "agent", "out": "{{directory}}/greeting.txt"},
            "environment": {"GREETING_SUFFIX": "yaml"},
            "includes": {
                "script": bash_prompt("printf '%s' '{{name}}-{{env.GREETING_SUFFIX}}' > {{out}}")
            },
        },
    )


def _templates_check(w, rc, stderr):
    assert rc == 0, stderr
    assert _read(w / "greeting.txt") == "agent-yaml"


# --- workflow environment and task env reach the agent process ----------------------------


def _env_build(w):
    return _workflow(
        w,
        [
            {
                "print-env": {
                    "env": {"TASK_VAR": "from-task", "SHARED": "task-wins"},
                    "prompt": bash_prompt(
                        f'printf "%s|%s|%s" "$WF_VAR" "$TASK_VAR" "$SHARED" > {w}/env.txt'
                    ),
                }
            }
        ],
        environment={"WF_VAR": "from-workflow", "SHARED": "workflow-loses"},
    )


def _env_check(w, rc, stderr):
    assert rc == 0, stderr
    assert _read(w / "env.txt") == "from-workflow|from-task|task-wins"


# --- CSV loop with filter -------------------------------------------------------------------


def _csv_build(w):
    rows = "name,status\nalpha,active\nbeta,inactive\ngamma,active\n"
    return _workflow(
        w,
        [
            {"make-csv": {"prompt": bash_prompt(f"printf '{rows}' > {w}/items.csv".replace("\n", "\\n"))}},
            {
                "per-row": {
                    "loop": {
                        "type": "csv",
                        "source": f"{w}/items.csv",
                        "skip-header": True,
                        "columns": ["name", "status"],
                        "filter": {"column": "status", "value": "active"},
                    },
                    "prompt": bash_prompt(
                        f"printf '{{{{loop.item.name}}}}' > {w}/row-{{{{loop.item.name}}}}.txt"
                    ),
                }
            },
        ],
    )


def _csv_check(w, rc, stderr):
    assert rc == 0, stderr
    assert sorted(p.name for p in w.glob("row-*.txt")) == ["row-alpha.txt", "row-gamma.txt"]
    assert _read(w / "row-gamma.txt") == "gamma"


# --- JSON loop with parallel workers ---------------------------------------------------------


def _json_build(w):
    data = b'[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]'
    # base64: no quotes or escapes for a real model to mangle (a heredoc of raw JSON
    # still came back with \" from some models).
    payload = base64.b64encode(data).decode("ascii")
    make_json = bash_prompt(f"printf '%s' '{payload}' | base64 -d > {w}/items.json")
    return _workflow(
        w,
        [
            {"make-json": {"prompt": make_json}},
            {
                "per-item": {
                    "loop": {"type": "json", "source": f"{w}/items.json", "workers": 2},
                    "prompt": bash_prompt(
                        f"printf 'item {{{{loop.item.id}}}}' > {w}/item-{{{{loop.item.id}}}}.txt"
                    ),
                }
            },
        ],
    )


def _json_check(w, rc, stderr):
    assert rc == 0, stderr
    assert sorted(p.name for p in w.glob("item-*.txt")) == [f"item-{i}.txt" for i in range(1, 5)]
    assert _read(w / "item-3.txt") == "item 3"


# --- todo-list loop marks items complete ------------------------------------------------------


def _todo_build(w):
    return _workflow(
        w,
        [
            {
                "make-todos": {
                    "prompt": bash_prompt(
                        f"printf -- '- [ ] first\\n- [ ] second\\n' > {w}/todo.md"
                    )
                }
            },
            {
                "work-todos": {
                    "loop": {"type": "todo-list", "source": f"{w}/todo.md", "mark-complete": True},
                    "prompt": bash_prompt(
                        f"printf '{{{{loop.item.text}}}}' > {w}/todo-{{{{loop.item.number}}}}.txt"
                    ),
                }
            },
        ],
    )


def _todo_check(w, rc, stderr):
    assert rc == 0, stderr
    assert _read(w / "todo-1.txt") == "first"
    assert _read(w / "todo-2.txt") == "second"
    assert _read(w / "todo.md").splitlines() == ["- [x] first", "- [x] second"]


# --- validators retry a flaky task ------------------------------------------------------------


def _retry_build(w):
    script = f"""
n=$(( $(cat {w}/attempts 2>/dev/null || echo 0) + 1 ))
printf '%s' "$n" > {w}/attempts
if [ "$n" -ge 2 ]; then printf '## Summary\\nok\\n' > {w}/report.md; else printf 'draft\\n' > {w}/report.md; fi
"""
    return _workflow(
        w,
        [
            {
                "flaky-report": {
                    "prompt": bash_prompt(script),
                    "validate": [
                        {"file-exists": f"{w}/report.md"},
                        {"contains": {"file": f"{w}/report.md", "text": "## Summary"}},
                    ],
                    "retry": {"max-attempts": 3, "on-validation-failure": "retry"},
                }
            }
        ],
    )


def _retry_check(w, rc, stderr):
    assert rc == 0, stderr
    # A real model may run the script more than twice (extra runs still prove retry worked);
    # the fake tier is deterministic at exactly 2.
    assert int(_read(w / "attempts")) >= 2
    assert "## Summary" in _read(w / "report.md")


# --- a failing validator fails the workflow ---------------------------------------------------


def _validation_failure_build(w):
    return _workflow(
        w,
        [
            {
                "forgets-file": {
                    "prompt": bash_prompt(f"printf 'wrong' > {w}/other.txt"),
                    "validate": [{"file-exists": f"{w}/expected.txt"}],
                }
            },
            {"never-runs": {"prompt": bash_prompt(f"touch {w}/after.txt")}},
        ],
    )


def _validation_failure_check(w, rc, stderr):
    assert rc == 1
    assert "validation failed" in stderr
    assert not (w / "after.txt").exists()


# --- skip-if and when ----------------------------------------------------------------------


def _conditions_build(w):
    return _workflow(
        w,
        [
            {"make-flag": {"prompt": bash_prompt(f"touch {w}/done.flag")}},
            {
                "skipped-by-flag": {
                    "skip-if": {"file-exists": f"{w}/done.flag"},
                    "prompt": bash_prompt(f"touch {w}/skip-if-ran"),
                }
            },
            {"skipped-by-when": {"when": "{{deploy}}", "prompt": bash_prompt(f"touch {w}/when-ran")}},
            {"runs-by-when": {"when": "not {{deploy}}", "prompt": bash_prompt(f"touch {w}/not-when-ran")}},
        ],
        **{"template-variables": {"deploy": False}},
    )


def _conditions_check(w, rc, stderr):
    assert rc == 0, stderr
    assert not (w / "skip-if-ran").exists()
    assert not (w / "when-ran").exists()
    assert (w / "not-when-ran").exists()


# --- on-error: continue keeps going after a failed task -----------------------------------------


def _continue_build(w):
    return _workflow(
        w,
        [
            {"fails": {"prompt": bash_prompt(f"touch {w}/attempted; exit 3")}},
            {"still-runs": {"prompt": bash_prompt(f"touch {w}/after.txt")}},
        ],
        **{"on-error": "continue"},
    )


def _continue_check(w, rc, stderr):
    assert rc == 0, stderr
    assert (w / "attempted").exists()
    assert (w / "after.txt").exists()


# --- per-task directory -------------------------------------------------------------------------


def _directory_build(w):
    return _workflow(
        w,
        [
            {"make-subdir": {"prompt": bash_prompt(f"mkdir -p {w}/sub")}},
            {"in-subdir": {"directory": "sub", "prompt": bash_prompt("pwd -P > where.txt")}},
        ],
    )


def _directory_check(w, rc, stderr):
    assert rc == 0, stderr
    assert _read(w / "sub" / "where.txt") == str((w / "sub").resolve())


SCENARIOS = [
    Scenario("single-task", _single_build, _single_check, agent_calls=1),
    Scenario("sequential", _sequential_build, _sequential_check, agent_calls=2),
    Scenario("parallel", _parallel_build, _parallel_check, agent_calls=3),
    Scenario("templates-includes-env", _templates_build, _templates_check, agent_calls=1),
    Scenario("environment", _env_build, _env_check, agent_calls=1),
    Scenario("csv-loop", _csv_build, _csv_check, agent_calls=3),
    Scenario("json-loop-workers", _json_build, _json_check, agent_calls=5),
    Scenario("todo-loop", _todo_build, _todo_check, agent_calls=3),
    Scenario("validator-retry", _retry_build, _retry_check, agent_calls=2),
    Scenario("validator-failure", _validation_failure_build, _validation_failure_check, agent_calls=1),
    Scenario("conditions", _conditions_build, _conditions_check, agent_calls=2),
    Scenario("on-error-continue", _continue_build, _continue_check, agent_calls=2),
    Scenario("task-directory", _directory_build, _directory_check, agent_calls=2),
]
