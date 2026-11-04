# Templating and Variables

Every string in a workflow — prompts, paths, env values, loop sources, `when` expressions — is
rendered before use. agent-yaml uses two rendering paths and picks one per string, which is the
source of most surprises. This page documents both paths, the variables available, and the
semantics of `when` expressions.

## Two Rendering Paths

`interpolate_variables()` decides per string (`src/utils.py:76`, `src/utils.py:158`):

| Path | Chosen when the string contains | Behaviour |
|------|--------------------------------|-----------|
| Simple regex | none of the triggers below | `{{var}}`, `{{var.nested}}`, `{{var-with-hyphens}}`; every value is `str()`-ed; a missing variable renders as empty |
| Full Jinja2 | `{%`, `{#`, `{{-`, `-}}`, or a `\|` filter inside `{{ }}` | Whole Jinja2 language: conditionals, loops, filters, comments, whitespace control |

This is a per-string decision, not a per-workflow one. Two prompts in the same task can render
through different engines.

```yaml
template-variables:
  build-dir: /tmp/build
  verbose: true

task:
  - simple:
      # Simple path: hyphenated name works as-is
      prompt: "Write artifacts to {{build-dir}}"

  - jinja:
      # Any {% %} flips this string to the Jinja path
      prompt: |
        {% if verbose %}Write a detailed report.{% endif %}
        Write artifacts to {{ v['build-dir'] }}
```

---

## The Hyphen Trap

On the simple path, `{{my-var}}` resolves normally. On the Jinja path `my-var` parses as
`my minus var`, so it silently renders as empty. Verified behaviour:

```
interpolate_variables("{{base-var}}-ext", {"base-var": "value"})   -> 'value-ext'   # simple path
interpolate_variables("{{v['my-var']}}",    {"my-var": 3})         -> ''            # simple path ignores []
interpolate_variables("{% if on %}{{v['my-var']}}{% endif %}", ...)-> '3'           # Jinja path
```

Three rules follow:

1. **Prefer underscores** in `template-variables` names (`build_dir`, not `build-dir`). Underscored
   names work on both paths.
2. If you must keep a hyphen, the Jinja path needs the `v` namespace: `{{ v['build-dir'] }}`.
3. `{{ v['build-dir'] }}` on its own does nothing — a string with only that syntax still takes the
   simple path and renders empty. Combine it with a real Jinja feature, or rename the variable.

---

## Undefined Variables Fail Silently

The Jinja environment uses a `SilentUndefined` class (`src/utils.py:16`): unknown names render as
`""`, are falsy, and iterate as empty. Typos therefore produce empty prompts, not errors, and
`agent-yaml validate` will not catch them.

```
interpolate_variables("A{{missing}}B", {})                        -> 'AB'
interpolate_variables("{% if debug %}DEBUG{% endif %}done", {})    -> 'done'
interpolate_variables("{{val | default('none')}}", {})            -> 'none'
```

Use `| default(...)` for optional values, and check a rendered dry run when a prompt looks short:

```bash
agent-yaml run tasks/my-workflow.yaml --dry-run -v
```

---

## Variables Available

| Variable | Source | Notes |
|----------|--------|-------|
| `{{directory}}` | Reserved | Workflow `directory`, absolute, `~` expanded; `--directory` overrides |
| `{{gitroot}}` | Reserved | Nearest parent containing `.git` (file or dir, so worktrees work); falls back to `{{directory}}` |
| `{{datetime}}` | Reserved | ISO 8601 with local offset, e.g. `2026-02-02T12:34:56.789-08:00` — unique per run |
| `{{user}}` | Reserved | `USER`, then `USERNAME`, then `LOGNAME`, else `unknown` |
| `{{env.NAME}}` | Reserved | Merged environment (see below) |
| `{{my_var}}` | `template-variables` | Resolved in dependency order, may reference other variables |
| `{{loop.index}}` `{{loop.total}}` `{{loop.remaining}}` | Loop | `index` is 0-based |
| `{{loop.item}}` | Loop | Row/object/file for the current iteration |
| `{{loop.worker.id}}` `{{loop.worker.directory}}` | Loop + `workers` | Only injected with `directory-pool` or `git-worktrees` |
| `--var key=value` | CLI | Overrides any user variable; values always arrive as **strings** |

Reserved names cannot be overridden — defining `directory` in `template-variables` raises
`CircularDependencyError` (`src/variables.py:191`).

### Variables that reference other variables

Resolution is a topological sort over `{{...}}` references, with cycle detection
(`src/variables.py:159`):

```yaml
template-variables:
  workspace: "/tmp/run-{{datetime}}"
  prs_csv: "{{workspace}}/prs.csv"
  review_dir: "{{workspace}}/review"
```

Circular references (`a: "{{b}}"`, `b: "{{a}}"`) fail validation with an explicit error rather than
rendering empty.

---

## Jinja2 Features You Can Use

All verified against `src/utils.py` (outputs shown for the given variables):

| Template | Variables | Output |
|----------|-----------|--------|
| `{% if debug %}DEBUG{% else %}PROD{% endif %}` | `debug: false` | `PROD` |
| `{% for i in items %}{{i}},{% endfor %}` | `items: [1,2,3]` | `1,2,3,` |
| `{{val \| upper}}` | `val: "abc"` | `ABC` |
| `{{val \| default('none')}}` | — | `none` |
| `{# hidden #}ab` | — | `ab` |
| `{% raw %}{{literal}}{% endraw %}` | — | `{{literal}}` |

Escaping literal braces matters when a prompt contains shell or Go templating. Wrap it in
`{% raw %}…{% endraw %}`; unmatched braces (`{{oops`) are left untouched on the simple path.

### Whitespace in prompt blocks

The Jinja environment sets `trim_blocks` and `lstrip_blocks` (`src/utils.py:59`), so block tags do
not leave blank lines behind:

```yaml
prompt: |
  Start.
  {% if verbose %}
  Detail line.
  {% endif %}
  End.
```

renders as `Start.\nDetail line.\nEnd.` when `verbose` is true, and `Start.\nEnd.` when false. For
finer control use whitespace modifiers (`{%-`, `-%}`), which also force the Jinja path:

```yaml
prompt: |
  a
  {%- if on %}
  b
  {%- endif %}
  c
```

renders as `abc` (verified) — the newlines around the tags are consumed.

---

## `when` Expressions Are Different

`when` runs through `evaluate_expression()` (`src/utils.py:210`), which converts `{{var}}` into flat
identifiers and evaluates the result in a `NativeEnvironment`. Types stay native, which is why
booleans work:

```yaml
task:
  - deploy:
      when: "{{environment}} == 'production' and {{tests_passed}}"
      prompt: "Deploy"
```

| Expression | Variables | Result |
|------------|-----------|--------|
| `{{env}} == 'prod'` | `env: prod` | `True` |
| `not {{force}}` | `force: False` | `True` |
| `{{count}} > 0` | `count: 5` | `True` |
| `{{loop.item.status}} == 'open'` | nested dict | `True` |
| `{{env}} in 'production staging'` | `env: staging` | `True` |
| `{{n \| int}} > 3` | `n: "5"` | `True` |

Supported: `==`, `!=`, `<`, `>`, `<=`, `>=`, `and`, `or`, `not`, `in`, `not in`, arithmetic, and
dotted access. The expression is truthiness-tested afterwards, so the task runs only when the result
is truthy.

### Four `when` traps

1. **`--var` values are strings.** `--var n=5` makes `{{n}} > 3` compare `"5"` to `3`, which raises
   internally and is swallowed → `False`, so the task is skipped. `--var n=5` with `{{n}} == 5` is
   `False`; `{{n}} == '5'` is `True`. Use `{{n | int}} > 3` or compare as strings.
2. **`{{flag}}` with `--var flag=false` is truthy.** The value is the string `"false"`. Write
   `when: "{{flag}} == 'true'"`, or put the flag in `template-variables` as a YAML boolean.
3. **Evaluation errors are silent.** Any exception inside the expression returns `False`
   (`src/utils.py:290`) and the task is skipped with a log line. A syntax typo looks identical to a
   false condition, so check stderr for `Task skipped: when condition not satisfied`.
4. **The `v` namespace does not exist here.** `{{ v['my-var'] }}` is not defined in expressions;
   use underscored names, or `{{my_var}}` where the variable is declared without a hyphen.

`skip-if` is separate, file-based, and runs **before** `when` (`src/executor.py:179`,
`src/executor.py:221`):

```yaml
- generate:
    skip-if:
      file-exists: "{{output_dir}}/report.md"
    when: "{{force}} == 'true'"
    prompt: "Write the report"
```

---

## Environment Variables

Three layers feed the agent subprocess and `{{env.*}}`:

```yaml
environment:            # workflow level
  LOG_LEVEL: debug
  OUT_DIR: "{{directory}}/out"

task:
  - build:
      env:              # task level, overrides workflow level
        LOG_LEVEL: trace
      prompt: "Build with LOG_LEVEL={{env.LOG_LEVEL}} into {{env.OUT_DIR}}"
```

Precedence, lowest to highest (`src/cli.py:355`, `src/executor.py:34`):

```
system env  <  --env-file  <  workflow environment:  <  task env:  <  --var
```

`--env-file` accepts multiple files; later files win. Env values support templates, and the merged
result is both exported to the agent CLI and readable as `{{env.NAME}}`.

---

## Limitations

1. **Interpolation always returns a string.** `{{flag}}` with `True` in a prompt becomes `'True'`;
   only `when` preserves native types.
2. **No macros, imports, or custom filters.** The loader is `BaseLoader` with no template search
   path; only Jinja built-ins (`default`, `upper`, `lower`, `int`, `join`, …) are available.
3. **The engine choice is invisible.** Adding one `{% if %}` to a string changes how every other
   `{{...}}` in that string is parsed — including hyphenated names.
4. **Silent undefined hides typos** and there is no static check for prompt variables.
5. **`{{ loop.* }}` only exists inside loops**, and `{{ loop.worker.* }}` only with
   `directory-pool` or `git-worktrees` (see [PARALLEL_LOOPS.md](PARALLEL_LOOPS.md)).

---

## Best Practices

1. **Name variables with underscores** — they work on both paths.
2. **Quote or block-scalar any value that starts with `{{`**: `prompt: "{{x}}"` is a string;
   `prompt: {{x}}` is a YAML flow mapping and fails to parse.
3. **Use `| default(...)`** for optional variables instead of relying on empty-string fallback.
4. **Prefer explicit `when` comparisons** (`== 'true'`, `| int`, `== 'prod'`) over bare truthiness.
5. **Read the rendered prompt** with `--dry-run -v` before blaming the agent for a thin result.

---

Source of truth: `src/utils.py` (interpolation, expressions), `src/variables.py` (reserved and
user variables), `src/when_conditions.py`, `src/executor.py` (env merge, gating order).
Root README sections: *Template variables*, *Environment variables*, *Skip-if and when*.
