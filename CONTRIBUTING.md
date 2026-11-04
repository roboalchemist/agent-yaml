# Contributing

Thanks for taking a look at `agent-yaml`.

## Development setup

```bash
git clone https://github.com/roboalchemist/agent-yaml.git
cd agent-yaml
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

## Ground rules

1. **Default tests never call a model.** Unit tests mock `execute_single_task`; integration tests use
   the fake `opencode` executable in `tests/support/fake_opencode.py`.
2. **Every `examples/*.yaml` and `tasks/*.yaml` must dry-run clean** — enforced by
   `tests/integration/test_examples.py`. Update `SKIP_TASKS` there only for fragments or WIP files.
3. **Agents communicate through files.** Agent stdout is never parsed. Prompts must ask the agent to
   write files, and tests must assert on those files.
4. **Add a scenario to `tests/support/scenarios.py`** when adding user-visible behaviour.

## Pull requests

- Keep changes focused; one concern per PR.
- Add or update tests for behaviour changes.
- Run `pytest -q` and `ruff check src tests` before pushing.
- Describe the motivation and the user-visible effect in the PR body.

## Reporting bugs

Open an issue with the workflow YAML (redacted), the command you ran, and the output of
`agent-yaml validate <workflow>`.
