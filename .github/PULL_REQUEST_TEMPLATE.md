## What changed

<!-- Summary and motivation. Link the issue if there is one. -->

## How to test

```bash
pytest -q
ruff check src tests

# manual check
agent-yaml validate <workflow>.yaml
agent-yaml run <workflow>.yaml --dry-run
```

## Checklist

- [ ] Tests cover the change (or explain why not)
- [ ] `pytest -q` and `ruff check src tests` pass
- [ ] Docs updated when behaviour or fields changed
- [ ] No secrets, private paths, or internal hostnames added
