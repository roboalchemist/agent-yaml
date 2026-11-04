# Loops

A loop runs one task once per item: rows in a CSV, objects in JSON, files matching a glob, or
markdown checkboxes. Five loop types exist (`src/validator.py:370`): `todo-list`, `csv`, `glob`,
`json`, `jsonl`. This page is the field reference; for `workers`, `directory-pool` and
`git-worktrees`, read [PARALLEL_LOOPS.md](PARALLEL_LOOPS.md) first.

## Loop Types at a Glance

| `type` | Iterates over | Required | Parallel (`workers`) |
|--------|---------------|----------|----------------------|
| `todo-list` | pending `- [ ]` items in a markdown file | `source` | no (ignored) |
| `csv` | rows of a CSV | `source` | yes |
| `glob` | files matching a pattern | `pattern` | no (ignored) |
| `json` | array in a JSON file (optionally nested) | `source` | yes |
| `jsonl` | one JSON object per line | `source` | yes |

Minimal shape:

```yaml
task:
  - review:
      loop:
        type: csv
        source: "{{workspace}}/prs.csv"
      prompt: "Review {{loop.item.branch}}"
```

`source` and `pattern` accept template variables and are expanded with `~` support. A source file may
be created by an earlier task; on `--dry-run` a missing file prints a warning instead of failing
(`src/loops.py:563`).

---

## `todo-list`

```yaml
task:
  - work-through-todos:
      loop:
        type: todo-list
        source: "{{directory}}/TODO.md"
        mark-in-progress: true
        mark-complete: true
      prompt: |
        Item {{loop.item.number}} (line {{loop.item.line}}): {{loop.item.text}}
```

- Recognises `- [ ]` (pending), `- [-]` (in progress), `- [x]` (done); only pending items run
  (`src/loops.py:445`).
- `mark-in-progress: true` rewrites the box to `- [-]` before the task runs; `mark-complete: true`
  rewrites it to `- [x]` after success.
- Item fields: `text`, `number` (1-based over all checkboxes), `line` (1-based file line).
- Resume starts from the remaining pending items, so completed boxes are never reprocessed.

---

## `csv`

```yaml
task:
  - triage:
      loop:
        type: csv
        source: "{{workspace}}/prs.csv"
        skip-header: true
        columns: [number, title, branch, url]
        filter:
          column: title
          value: "docstring"
      prompt: "PR #{{loop.item.number}} on {{loop.item.branch}} (csv row {{loop.item.row}})"
```

| Field | Meaning |
|-------|---------|
| `source` | CSV path; must be UTF-8 |
| `skip-header` | Drop the first line before parsing (default `false`) |
| `columns` | Field names to use instead of reading a header row |
| `filter` | `{column, value}`; keeps rows where `row[column] == str(value)` |

### The `skip-header` × `columns` matrix

These four combinations behave differently and are intentional (`src/loops.py:1687`):

| `skip-header` | `columns` | Result |
|---------------|-----------|--------|
| `false` | absent | Header row becomes field names; data rows follow. Normal case. |
| `true` | absent | Header line dropped, then the **first data row becomes the field names** — one row is lost. |
| `false` | present | Supplied names are used, so the **header line is processed as data row 1**. |
| `true` | present | Header line dropped and supplied names used — the combination you want when you control the file. |

Item fields are the column names plus `row` (1-based CSV row). Use `{{loop.item.column_name}}`;
`{{loop.item}}` on its own renders the row dict.

---

## `glob`

```yaml
task:
  - document-files:
      loop:
        type: glob
        pattern: "{{directory}}/src/**/*.py"
        exclude: ["**/test_*.py", "**/__pycache__/**"]
        sort: modified
      prompt: |
        Document {{loop.item.filename}} ({{loop.item.extension}}) at {{loop.item.path}}
```

| Field | Meaning |
|-------|---------|
| `pattern` | Glob, recursive (`**`) supported |
| `exclude` | String or list of globs to drop |
| `sort` | `name` (A→Z), `modified`, `size`, `created` — the last three are newest/largest first (`src/loops.py:2145`) |

`{{loop.item}}` renders as the absolute path, and the item also exposes `path`, `filename`,
`extension` (`src/loops.py:2204`). An empty match set is not an error: the task body is skipped and
`No files match pattern: …` is logged.

---

## `json` and `jsonl`

```yaml
task:
  - process-open:
      loop:
        type: json
        source: "{{workspace}}/issues.json"
        path: "data.issues"
        filter:
          conditions:
            - key: "state"
              value: "open"
            - key: "labels.bug"
              value: true
          operator: AND
      prompt: "Issue {{loop.item.number}}: {{loop.item.title}}"
```

| Field | `json` | `jsonl` | Meaning |
|-------|--------|---------|---------|
| `source` | required | required | File path |
| `path` | optional | **rejected** | Dot path to the array, numeric segments index lists (`data.issues.0.items`) |
| `filter` | optional | optional | See below |

- The final value at `path` must be an array, otherwise the run fails with the type it found.
- `jsonl` reads one object per line; a bad line fails the loop with the line number.
- **Filter** has two forms, and both compare with exact equality (no type coercion):
  - single condition: `filter: {key: "state", value: "open"}`
  - multiple: `filter: {conditions: [...], operator: AND|OR}` (`OR` when any condition matches)
  - `key` supports dot notation into nested objects (`address.city`).
- Numbers, strings and booleans are distinct: `value: "true"` will not match `true`.
- Primitive array elements (`["a", "b"]`) are wrapped so every item is an object:
  `{{loop.item.value}}`, `{{loop.item.type}}` (`string`/`number`/`boolean`/`null`), `{{loop.item._index}}`.

CSV and JSON filters deliberately differ: CSV uses `column`, JSON uses `key`.

---

## Loop Variables

| Variable | Meaning |
|----------|---------|
| `{{loop.index}}` | 0-based position in the iteration list |
| `{{loop.total}}` | Number of items being iterated |
| `{{loop.remaining}}` | `total - index` |
| `{{loop.item}}` | Current item (string form differs per type) |
| `{{loop.worker.id}}` | Worker index, only with `directory-pool`/`git-worktrees` |
| `{{loop.worker.directory}}` | Assigned directory/worktree, same condition |

Per-type item shape: `todo-list` → `text`/`number`/`line`; `csv` → columns + `row`; `glob` →
path-like string + `path`/`filename`/`extension`; `json`/`jsonl` → the object (JSONL objects also
carry `_index`), or the wrapped `value`/`type`/`_index` for primitives.

---

## Checkpoints and Resuming

Any loop type accepts `checkpoint-file` and `resume`:

```yaml
loop:
  type: json
  source: "{{workspace}}/prs.json"
  checkpoint-file: "{{workspace}}/ckpt-prs.json"
  resume: true
```

- `checkpoint-file` is expanded (template variables, `~`, absolute conversion) and its parent
  directory is created on first write.
- `resume: true` loads the file and continues after `current_index`. Without `resume`, the file is
  still written but never read.
- Writes are atomic (temp file + `os.replace`), so a killed process cannot leave a half-written
  checkpoint (`src/loops.py:2225`).
- Format:

```json
{
  "type": "json",
  "current_index": 3,
  "completed_items": ["item1", "item2", "item3"],
  "failed_items": ["item4"]
}
```

- A corrupt checkpoint raises `CheckpointValidationError` with the file path and a delete-and-restart
  suggestion rather than silently restarting.
- **`agent-yaml run --resume` is a no-op.** Resumption is always per loop, driven by `resume: true`
  plus `checkpoint-file`.

---

## Dry Runs

`--dry-run` parses the source and prints what the loop would do — type, path, item count, first 10
items, filters, checkpoint path — without calling the agent:

```bash
agent-yaml run tasks/my-workflow.yaml --dry-run
```

Both `examples/*.yaml` and `tasks/*.yaml` are dry-run by CI (`tests/integration/test_examples.py`),
so a loop that fails to parse or validate fails the suite.

---

## Limitations

1. **`workers` only parallelises `csv`, `json`, and `jsonl`.** `todo-list` and `glob` ignore it
   silently — validation accepts the field but execution is sequential.
2. **`path` is `json`-only**; `jsonl` rejects it (`src/validator.py:482`).
3. **Filters are exact-equality only** — no ranges, regex, or type coercion.
4. **CSV filter compares against `str(value)`**, so booleans/numbers in the config are stringified
   before comparison, unlike JSON filters which compare natively.
5. **No nested loops.** A loop's task body cannot start another loop.
6. **Parallel loop ordering is nondeterministic**; `completed`/`failed` lists are not ordered.

---

## Best Practices

1. **Control the source file** when you can — generate the CSV/JSON in an earlier task and use
   `skip-header: true` with explicit `columns`.
2. **Set `checkpoint-file` for anything long-running**, even at `workers: 1`.
3. **Filter early** in JSON loops rather than branching inside the prompt; it keeps prompts short
   and runs cheaper.
4. **Use `sort: modified`** for "process newest first" glob loops instead of sorting in the prompt.
5. **Log the loop identity in the prompt** (`{{loop.index}}/{{loop.total}}`) so parallel workers can
   be told apart in their own output.

---

Source of truth: `src/loops.py` (all five loop types, checkpoints, filters), `src/validator.py:349`
(loop schema). Related: [PARALLEL_LOOPS.md](PARALLEL_LOOPS.md), `examples/04-*` through
`examples/12-*`, `examples/27-*` through `examples/36-*`.
