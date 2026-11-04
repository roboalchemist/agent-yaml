"""
Deterministic stand-in for `opencode run`, used by the integration tier.

The real agent is asked to run the fenced ```bash block in its prompt; this fake runs
that block itself with bash (inherited cwd and env) and exits with the script's exit
code. A prompt without a bash block is "answered" with exit 0. The same scenario
workflows therefore work against this fake (integration tier) and against a real
model (live tier).

If FAKE_AGENT_LOG is set, one JSON line per invocation is appended to it:
{"argv": [...], "cwd": "...", "prompt": "..."}.
"""

import json
import os
import re
import subprocess
import sys

BASH_BLOCK = re.compile(r"```(?:bash|sh)\s*\n(.*?)```", re.DOTALL)


def main(argv):
    if "--" in argv:
        prompt = " ".join(argv[argv.index("--") + 1:])
    else:
        prompt = argv[-1] if argv else ""

    log_path = os.environ.get("FAKE_AGENT_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "prompt": prompt}) + "\n")

    script = "\n".join(block.strip("\n") for block in BASH_BLOCK.findall(prompt))
    if not script:
        print("DONE")
        return 0
    return subprocess.run(["bash", "-c", script]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
