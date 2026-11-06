# Meta-Agent YAML Configuration Specification

## Overview

This document defines the YAML configuration format for meta-agent workflows. The format allows you to orchestrate complex multi-step tasks using AI CLI tools (Claude CLI, OpenAI Codex, Gemini CLI, etc.) with template variables, parallel/sequential execution, and reusable components.

The configuration is CLI-agnostic and uses an adapter layer to translate generic settings to tool-specific invocations.

## Top-Level Structure

```yaml
directory: <string>
cli-agent: <string>           # Which AI CLI to use (opencode, claude, codex, pi, vtcode, antigravity)
cli-agent-config: <object>    # CLI-specific configuration
on-error: <string>            # Error handling strategy (fail, continue, skip)
template-variables: <object>
ensure: <object>
includes: <object>
task: <list>
```

## Field Definitions

### `directory` (string, required)

The working directory where the agent will start execution. Supports expandable paths like `~`.

**Example:**
```yaml
directory: "~/projects/example-repo"
```

---

### `cli-agent` (string, optional, default: "claude")

Specifies which AI CLI tool to use for execution.

**Supported Values:**
- `claude` - Claude CLI (claude-code)
- `codex` - OpenAI Codex CLI

**Example:**
```yaml
cli-agent: "claude"
```

---

### `cli-agent-config` (object, optional)

CLI-specific configuration that gets translated by the adapter layer to tool-specific command-line arguments.

**Common Configuration Options:**
- `skip-confirmations` (boolean): Skip all user confirmation prompts
- `additional-dirs` (list): Additional directories to add to the working context
- `timeout` (number): Timeout in seconds per CLI invocation (per task)
- `permissions` (list): Permission flags specific to the CLI tool
- `model` (string): Specific model to use (if supported by CLI)
- `mcp-config-file` (string): Path to MCP configuration file
- `raw-args` (list): Raw CLI arguments to pass through directly (tool-specific)

**Example (Generic):**
```yaml
cli-agent-config:
  skip-confirmations: true
  additional-dirs:
    - "/tmp"
    - "/private/var/tmp"
  timeout: 3600
  permissions:
    - allow-file-write
    - allow-network
  raw-args:
    - "--experimental-feature"
    - "--custom-flag=value"
```

**Adapter Translation Examples:**

For Claude CLI, this translates to:
```bash
claude-code --dangerously-skip-everything --add-dir="/tmp" --add-dir="/private/var/tmp"
```

For Codex CLI, this might translate to:
```bash
codex --full-auto -C /tmp
```

For Gemini CLI, this might translate to:
```bash
gemini-cli --auto-approve --workspace="/tmp" --workspace="/private/var/tmp"
```

#### Raw Arguments Pass-Through

The `raw-args` field allows you to pass tool-specific arguments directly to the CLI without adapter translation. This is useful for:

- Experimental features not yet mapped in the adapter
- Tool-specific flags unique to one CLI
- Advanced configurations not covered by generic options

**Example with raw-args:**
```yaml
cli-agent: "claude"
cli-agent-config:
  skip-confirmations: true
  raw-args:
    - "--ide"
    - "--agents"
    - '{"reviewer":{"description":"Reviews code"}}'
```

**Translates to:**
```bash
claude --dangerously-skip-permissions --ide --agents '{"reviewer":{"description":"Reviews code"}}'
```

**Important Notes:**
- Raw args are appended after all adapter-translated arguments
- No validation is performed on raw args
- Arguments are passed exactly as specified (be careful with quoting)
- Tool compatibility is your responsibility

---

### `on-error` (string, optional, default: "fail")

Specifies how the meta-agent should handle task failures during workflow execution.

**Supported Values:**
- `fail` (default) - Stop workflow immediately on first error
- `continue` - Log error and continue with remaining tasks
- `skip` - Skip failed task and continue with next task

**Example:**
```yaml
on-error: fail  # Fail fast (default behavior)
```

**Design Rationale:**
- Default to `fail` because continuing on errors can introduce unexpected behavior and cascading failures
- Use `continue` or `skip` only when tasks are independent and failures are acceptable
- Failed tasks are always logged regardless of strategy

**Behavior Details:**
- `fail`: Stops workflow, exits with error code, prints failure details
- `continue`: Logs error, marks task as failed, continues to next task
- `skip`: Logs error, marks task as skipped, continues to next task

---

### `template-variables` (object, required)

Named variables that can be referenced throughout the configuration using Jinja2 syntax (`{{variable_name}}`).

**Features:**
- Variables can reference other variables
- Variables are evaluated in dependency order
- Evaluated before `includes`, which are evaluated before `task` prompts
- Reserved variables are automatically provided (gitroot, datetime, user, etc.)

**Naming Rules:**
- Follow Jinja2 identifier rules (alphanumeric and underscores)
- Can contain hyphens: `topic-doc` ✓
- Can contain underscores: `topic_doc` ✓
- Can contain numbers: `topic2` ✓
- Cannot start with a number: `2topic` ✗
- Case-sensitive: `Topic` and `topic` are different
- Cannot use reserved names: `gitroot`, `datetime`, `user`, `directory`

**Example:**
```yaml
template-variables:
  topic: "access-control-behaviours"
  service: "example-service"
  docs-folder: "docs"
  # Variables can reference each other
  doc-root: "{{directory}}/{{service}}/{{docs-folder}}"
  topic-doc: "{{doc-root}}/{{topic}}.md"
  topic-doc-root: "{{doc-root}}/{{topic}}"
```

**Reserved Variables** (automatically injected by meta-agent):
- `{{gitroot}}` - Git repository root directory (absolute path)
- `{{datetime}}` - Current date/time in ISO 8601 format (local timezone)
- `{{user}}` - Current system username
- `{{directory}}` - Working directory (absolute path, from config)

See [Reserved Template Variables](#reserved-template-variables) section for details.

---

### `ensure` (object, optional)

Pre-flight validation to ensure required tools and MCPs are available before workflow execution.

**Structure:**
```yaml
ensure:
  mcps: <list of MCP names>
  tools: <list of tool names>
```

**Example:**
```yaml
ensure:
  mcps:
    - notion
    - linear
  tools:
    - gh
```

**Behavior:**
- Workflow will not start if any required MCPs or tools are missing
- Provides early failure before potentially long-running tasks begin

---

### `includes` (object, optional)

Reusable prompt fragments that can be referenced by tasks. Includes are **simple string concatenations** appended to the prompt.

**How it Works:**
1. Prompt text comes first
2. Includes are appended in the order listed
3. Each include is separated by a single space
4. Template variables are expanded after concatenation

**Features:**
- Supports Jinja2 template variable interpolation
- Can be composed together in task definitions
- Promotes DRY (Don't Repeat Yourself) for common instructions

**Example:**
```yaml
includes:
  read-intro: "Read the full introduction guide on the {{topic}} in {{intro-doc}} before starting."
  exhaustive: "Perform an exhaustive search by trying various search terms."
  parallel-subagents: "This is an embarrassingly parallel task. Use sub-agents in parallel."
  style: "The style should be complete, compact, and informative."
```

**Usage in Tasks:**
```yaml
task:
  - my-task:
      prompt: "Do the main work here."
      include:
        - read-intro
        - exhaustive
        - parallel-subagents
```

**Concatenation Process:**
1. Start with: `"Do the main work here."`
2. Append space + `read-intro`: `"Do the main work here. Read the full introduction guide..."`
3. Append space + `exhaustive`: `"... Perform an exhaustive search..."`
4. Append space + `parallel-subagents`: `"... This is an embarrassingly parallel task..."`

**Final prompt:** `"Do the main work here. Read the full introduction guide on the {{topic}} in {{intro-doc}} before starting. Perform an exhaustive search by trying various search terms. This is an embarrassingly parallel task. Use sub-agents in parallel."`

---

### `task` (list, required)

The main workflow definition. Tasks are organized in a nested structure that controls execution order and parallelism.

**Structure:**
```yaml
task:
  - <task-name>:
      <subtask-name>:
        prompt: <string>
        include: <list>
        loop: <object>
  - <task-name>:
      - <subtask-1>: ...
      - <subtask-2>: ...
```

#### Task Execution Rules

1. **Top-level list items run sequentially** (one after another)
2. **Object keys at the same level run in parallel**
3. **Nested list items under an object run sequentially**
4. **Only tasks with a `prompt` field are executable** - otherwise they're just grouping containers

#### Task Structure

Each executable task contains:

##### `prompt` (string, required for execution)

The actual instructions to send to the agent.

**Features:**
- Supports Jinja2 template variable interpolation
- Combined with `include` fragments before execution

**Example:**
```yaml
prompt: "Create a folder {{topic-doc-root}} for the topic {{topic}}."
```

##### `include` (list, optional)

List of named includes to append to the prompt.

**Example:**
```yaml
include:
  - use-intro
  - exhaustive
  - parallel-subagents
```

##### `loop` (object, optional)

Repeat the task for each item. See [Task Looping](#task-looping) section for details.

**Structure:**
```yaml
loop:
  type: <loop-type>
  # Type-specific fields
```

**Supported Types:**
- `todo-list` - Markdown todo items
- `csv` - CSV/TSV file rows
- `glob` - File pattern matching

See planning.txt for future loop types (AST, grep, JSON/YAML, git, API pagination).

##### `on-error` (string, optional)

Override the workflow-level error handling strategy for this specific task.

**Values:**
- `fail` - Stop workflow if this task fails
- `continue` - Log error and continue with remaining tasks
- `skip` - Skip this task and continue

**Example:**
```yaml
task:
  - critical-task:
      prompt: "Deploy to production"
      on-error: fail  # Override workflow-level setting

  - optional-task:
      prompt: "Send notification"
      on-error: continue  # Don't fail workflow if this fails
```

**Default:** Inherits from workflow-level `on-error` setting

---

## Task Organization Patterns

### Sequential Tasks

```yaml
task:
  - step-1:
      prompt: "First task"
  - step-2:
      prompt: "Second task (runs after step-1)"
  - step-3:
      prompt: "Third task (runs after step-2)"
```

### Parallel Tasks

```yaml
task:
  - parallel-group:
      task-a:
        prompt: "Runs in parallel with task-b and task-c"
      task-b:
        prompt: "Runs in parallel with task-a and task-c"
      task-c:
        prompt: "Runs in parallel with task-a and task-b"
```

### Mixed Sequential and Parallel

```yaml
task:
  - step-1:
      prompt: "Runs first"
  - parallel-group:
      # These run in parallel after step-1
      task-a:
        prompt: "Parallel task A"
      task-b:
        prompt: "Parallel task B"
  - step-2:
      prompt: "Runs after all parallel tasks complete"
```

### Nested Sequential Tasks

```yaml
task:
  - phase-1:
      # These run sequentially within phase-1
      - substep-1:
          prompt: "First substep"
      - substep-2:
          prompt: "Second substep"
      - substep-3:
          prompt: "Third substep"
```

### Complex Nested Structure

```yaml
task:
  - harvest-initial:
      linear:
        # Sequential tasks under 'linear'
        - gather-projects:
            prompt: "Gather linear projects"
            include:
              - use-intro
              - parallel-subagents
        - gather-issues:
            prompt: "Gather linear issues"
            include:
              - use-intro
      notion-rfcs:
        # This runs in parallel with 'linear' group
        prompt: "Find RFCs in Notion"
        include:
          - use-intro
      github:
        # This also runs in parallel with 'linear' and 'notion-rfcs'
        - fetch-prs:
            prompt: "Fetch PRs"
        - analyze-prs:
            prompt: "Analyze PRs"
```

---

## Task Looping

### How Loops Work

Loops execute tasks repeatedly over collections. A single task definition becomes multiple executions.

**Architecture:**
- **Loop processing is external to the CLI agent**
- The meta-agent orchestrator handles iteration
- CLI agent receives one invocation per item with pre-expanded variables

**Basic Structure:**
```yaml
task:
  - task-name:
      prompt: "Process {{loop.item}}"
      loop:
        type: <loop-type>
        # Type-specific config
```

**Common to All Loops:**

*Execution:*
- Meta-agent loads source data
- For each item: meta-agent injects variables → expands prompt → invokes CLI agent
- Checkpoints saved only if `checkpoint-file` is specified (optional)

*Common Variables:*
- `{{loop.index}}` - Objective iteration count (0-based, same across all types)
- `{{loop.total}}` - Total items
- `{{loop.remaining}}` - Items remaining
- `{{loop.item}}` - Complete object containing all iteration-specific data
  - All specifics for this iteration are properties of `{{loop.item}}`
  - Structure varies by loop type

*Loop Control (All Optional):*
```yaml
loop:
  # Checkpointing (optional - checkpoints NOT created unless specified)
  checkpoint-file: ".loop-state.json"  # If specified, creates checkpoint file
  resume: true                          # Resume from checkpoint on restart

  # Retry & errors
  retry:
    max-attempts: 3
    on-failure: skip  # skip, retry, abort

  # Early exit
  exit-on:
    - condition: max-iterations
      value: 50
```

**Note:** Without `checkpoint-file`, failed loops must restart from the beginning.

---

### Loop Type Implementations

#### 1. Todo List

Iterate over uncompleted markdown todo items.

**Configuration:**
```yaml
loop:
  type: todo-list
  source: "tasks.md"
  mark-in-progress: true  # Optional
  mark-complete: true     # Optional
```

**Type-Specific Variables:**

`{{loop.item}}` contains:
- `{{loop.item.text}}` - The todo text
- `{{loop.item.number}}` - Todo item number (1-based)
- `{{loop.item.line}}` - Line number in file

**Example:**
```yaml
task:
  - process-todos:
      prompt: "Complete: {{loop.item.text}} (todo #{{loop.item.number}})"
      loop:
        type: todo-list
        source: "todos.md"
        mark-complete: true
```

---

#### 2. CSV Files

Iterate over rows in CSV/TSV files.

**Configuration:**
```yaml
loop:
  type: csv
  source: "data.csv"
  skip-header: true
  columns: [id, name, email]
  filter:                  # Optional
    column: status
    value: active
```

**Type-Specific Variables:**

`{{loop.item}}` contains:
- `{{loop.item.column_name}}` - Any column value (dynamic)
- `{{loop.item.row}}` - Row number (1-based)

**Example:**
```yaml
task:
  - notify-users:
      prompt: "Email {{loop.item.name}} at {{loop.item.email}} (row {{loop.item.row}})"
      loop:
        type: csv
        source: "users.csv"
        skip-header: true
        columns: [id, name, email]
```

---

#### 3. File Glob

Iterate over files matching patterns.

**Configuration:**
```yaml
loop:
  type: glob
  pattern: "agent_yaml/**/*.ts"
  exclude: ["**/*.test.ts"]  # Optional
  sort: modified             # Optional: name, modified, size, created
```

**Type-Specific Variables:**

`{{loop.item}}` contains:
- `{{loop.item.path}}` - Full file path
- `{{loop.item.filename}}` - Filename without path
- `{{loop.item.extension}}` - File extension

For convenience, `{{loop.item}}` renders as the file path when used as a string.

**Example:**
```yaml
task:
  - update-files:
      prompt: "Update imports in {{loop.item.path}}"
      loop:
        type: glob
        pattern: "agent_yaml/**/*.ts"
        exclude: ["**/*.test.ts"]
```

---

#### 4. JSON Arrays

Iterate over JSON array elements or JSON Lines files.

**Standard JSON Configuration:**
```yaml
loop:
  type: json
  source: "data.json"
  path: "users.active"      # Optional: dot notation to nested array
  filter:                    # Optional: single or multiple conditions
    # Simple filter (single condition):
    key: "status"
    value: "active"

    # OR multiple conditions with AND/OR operator:
    conditions:
      - key: "status"
        value: "active"
      - key: "role"
        value: "admin"
    operator: "AND"          # "AND" or "OR"
```

**JSON Lines Configuration:**
```yaml
loop:
  type: jsonl
  source: "data.jsonl"       # One JSON object per line
  filter:                    # Optional: same as JSON
    key: "status"
    value: "active"
```

**Type-Specific Variables:**

For objects in array:
- `{{loop.item.property}}` - Direct property access
- `{{loop.item.nested.field}}` - Nested property via dot notation

For primitives in array (strings, numbers, booleans, null):
- `{{loop.item.value}}` - The primitive value
- `{{loop.item.type}}` - Type name: "string", "number", "boolean", or "null"

**Example 1: Basic JSON Array**
```yaml
task:
  - process-users:
      loop:
        type: json
        source: "users.json"    # [{"name": "Alice", "role": "admin"}, ...]
      prompt: |
        Process user {{loop.item.name}} with role {{loop.item.role}}
        Create output/user-{{loop.index}}.txt
```

**Example 2: Nested Array Extraction**
```yaml
task:
  - process-engineers:
      loop:
        type: json
        source: "org.json"
        path: "departments.engineering.employees"
      prompt: |
        Process employee {{loop.item.name}}
        Title: {{loop.item.title}}
```

**Example 3: Multi-Condition Filtering**
```yaml
task:
  - process-urgent-tasks:
      loop:
        type: json
        source: "tasks.json"
        filter:
          conditions:
            - key: "priority"
              value: "high"
            - key: "status"
              value: "active"
          operator: "AND"      # Only items matching ALL conditions
      prompt: "Process urgent task: {{loop.item.title}}"
```

**Example 4: JSON Lines Format**
```yaml
task:
  - process-events:
      loop:
        type: jsonl
        source: "events.jsonl"  # {"event": "login", "user": "alice"}
                                # {"event": "logout", "user": "bob"}
        filter:
          key: "event"
          value: "login"
      prompt: "Process login for {{loop.item.user}}"
```

**Format Differences:**

| Feature | JSON (.json) | JSON Lines (.jsonl) |
|---------|--------------|---------------------|
| Format | Single JSON array `[...]` or object with nested array | One JSON object per line |
| Parsing | Entire file parsed at once | Streaming line-by-line |
| Path extraction | Supported via `path` field | Not supported (each line is the item) |
| Empty lines | N/A | Skipped silently |
| Memory | Loads full array into memory | Processes line-by-line |

**Notes:**
- Primitives in arrays are automatically wrapped as objects: `"hello"` becomes `{"value": "hello", "type": "string"}`
- Nested path uses dot notation: `"users.active"` navigates `data["users"]["active"]`
- Filters support nested keys: `"address.city"` matches `item["address"]["city"]`
- Empty arrays return success with 0 iterations
- Invalid JSON raises ExecutionError with line number and parse details

**CRITICAL PATTERN - File Creation Must Precede Loop:**

When using JSON loops, the source file must exist BEFORE the loop executes. You cannot create a file and loop over it in the same task.

❌ **WRONG:**
```yaml
task:
  - process-data:
      prompt: |
        Create data.json with: [{"id": 1}, {"id": 2}]
        Process each item...
      loop:
        type: json
        source: "data.json"  # ERROR: Loop executes first, file doesn't exist yet!
```

✅ **CORRECT:**
```yaml
task:
  - setup:
      prompt: "Create data.json with: [{"id": 1}, {"id": 2}]"

  - process-data:
      prompt: "Process item {{loop.item.id}}"
      loop:
        type: json
        source: "data.json"  # ✅ File created in previous task
```

**Explanation:** Loops execute BEFORE the task prompt. The loop needs to read the source file to determine iterations, so the file must already exist from a previous task.

---

## Template Variable Interpolation

Variables are interpolated by `agent_yaml/utils.py`, which picks one of two paths **per string**.

### Hybrid Interpolation

| Path | Chosen when the string contains | Behaviour |
|------|---------------------------------|-----------|
| Simple regex | none of the triggers below | `{{var}}`, `{{var.nested}}`, `{{var-with-hyphens}}`; values are stringified; unknown names render as `""` |
| Full Jinja2 | `{%`, `{#`, `{{-`, `-}}`, or a `\|` filter inside `{{ }}` | Conditionals, `for` loops, filters, comments, whitespace control |

**Supported on the Jinja2 path:**
- Variable substitution and nested access: `{{var}}`, `{{loop.item.text}}`
- Conditionals: `{% if %}` / `{% elif %}` / `{% else %}` / `{% endif %}`
- Loops: `{% for item in items %}…{% endfor %}`
- Filters: `{{var | default('x')}}`, `{{var | upper}}`, `{{var | int}}`
- Comments `{# … #}`, whitespace control `{%- -%}`, and `{% raw %}…{% endraw %}`
- Literal braces for shell/Go templating

**Not supported:** macros, `{% import %}`, template inheritance, and custom filters — the loader is
`BaseLoader` with no search path.

**Undefined variables are silent by design:** they render as an empty string and are falsy, so a typo
produces an empty prompt rather than an error. Use `| default(...)` for optional values.

**Hyphenated names:** `{{my-var}}` works only on the simple path. Once a string uses any Jinja2
feature, `my-var` parses as subtraction and renders empty; use underscored names or the `v`
namespace, `{{ v['my-var'] }}`. See `docs/TEMPLATING.md` for the verified behaviour matrix.

### Variable References and Circular Dependencies

The resolver builds a dependency graph and applies a DFS with path tracking plus a topological sort:

```yaml
template-variables:
  a: "{{b}}"
  b: "{{c}}"
  c: "{{a}}"  # Error: Circular dependency detected
```

**Error behavior:**
- Parse-time error (workflow never starts)
- Error message identifies the circular chain: `a → b → c → a`

### Evaluation Order

1. **Reserved variables injected**: `{{gitroot}}`, `{{datetime}}`, `{{user}}`, `{{directory}}`
2. **Template Variables**: Evaluated in dependency order (with circular dependency detection)
3. **Includes**: Evaluated after template variables
4. **Task Prompts**: Evaluated last, with all variables and includes resolved

### Example Flow

```yaml
template-variables:
  service: "myservice"
  doc-root: "/docs/{{service}}"  # Becomes "/docs/myservice"

includes:
  read-doc: "Read {{doc-root}}/intro.md"  # Becomes "Read /docs/myservice/intro.md"

task:
  - my-task:
      prompt: "Process {{service}} documentation"  # Becomes "Process myservice documentation"
      include:
        - read-doc  # Appends "Read /docs/myservice/intro.md"
```

**Final prompt:** `"Process myservice documentation Read /docs/myservice/intro.md"`

---

## Reserved Template Variables

The meta-agent automatically injects reserved variables into every workflow. These are available before user-defined template-variables are evaluated.

### Auto-Injected Variables

#### `{{gitroot}}`
Git repository root directory.

**Determination:**
- Walks up from `{{directory}}` to find `.git/` directory
- **Fallback:** If not in a git repository, uses `{{directory}}`
- Always uses absolute path

**Example:** `~/projects/example-repo`

#### `{{datetime}}`
Current date and time in local timezone.

**Format:** ISO 8601 with timezone offset
- `YYYY-MM-DDTHH:MM:SS.sss±HH:MM`
- Example: `2025-10-01T23:45:30.123-07:00` (Pacific Time)
- **Evaluated once at workflow start** - same value for all tasks
- **Consistency:** All tasks in a workflow see identical datetime value
- **On resumption:** When resuming from checkpoint, uses original workflow start time (not current time)

#### `{{user}}`
Current system username.

**Source:** Environment variables (checked in order)
1. `USER`
2. `USERNAME`
3. `LOGNAME`

**Fallback:** If no environment variable found, uses `"unknown"`

**Example:** `alice`

#### `{{directory}}`
Working directory from YAML config.

**Behavior:**
- Expanded to absolute path (resolves `~`)
- **Validation:** Directory must exist (checked at parse-time)
- Same value as top-level `directory` field
- Available in all contexts

**Example:** `~/projects/example-repo`

### Precedence & Usage

**Precedence Rules:**
1. Reserved variables cannot be overridden by user-defined variables
2. Injected before user template-variables are evaluated
3. Always available in all contexts (template-variables, includes, prompts, loops)

**Example:**
```yaml
directory: "~/my-project"

template-variables:
  # Can reference reserved variables
  output-dir: "{{gitroot}}/output"
  report-file: "{{output-dir}}/report-{{user}}-{{datetime}}.md"

task:
  - create-report:
      prompt: "Create report at {{report-file}}"
```

**Expanded values:**
- `{{gitroot}}` → `/home/user/my-project`
- `{{user}}` → `user`
- `{{datetime}}` → `2025-10-01T23:45:30.123-07:00`
- `{{directory}}` → `/home/user/my-project`
- `{{output-dir}}` → `/home/user/my-project/output`
- `{{report-file}}` → `/home/user/my-project/output/report-user-2025-10-01T23:45:30.123-07:00.md`

---

## Validation Rules

The meta-agent performs two types of validation:

### 1. Linting (Parse-time Validation)

Validates YAML structure and schema **before any execution begins**.

**What's Validated:**
- **YAML syntax** - Is the file parseable?
- **Schema validation** - Are all required fields present?
- **Field types** - Are values the correct type (string, list, object)?
- **Template variable references** - Are all variables defined?
- **Loop configuration** - Are loop types valid and properly configured?
- **Task structure** - Do tasks follow the correct nesting rules?

**When:** Immediately upon loading the YAML file
**Failure behavior:** Hard fail - workflow never starts

**Example Linting Errors:**
```
Error: Unknown loop type 'invalid-type' at task.process-items.loop.type
Error: Undefined variable '{{missing-var}}' in task.my-task.prompt
Error: Field 'prompt' is required for executable tasks
```

### 2. Runtime Validation

Validates requirements **when they're actually needed** during execution.

#### Start-time Validation

Checks the `ensure` block before workflow starts:

```yaml
ensure:
  mcps:
    - notion
    - linear
  tools:
    - gh
```

**Validation:**
- Each MCP must be installed and operational
- Each tool must be executable and in PATH
- Workflow fails immediately if any requirement is missing

**When:** After parse-time validation, before first task runs
**Failure behavior:** Controlled by `on-error` setting (default: fail)

#### Just-in-time Validation

Validates resources **right before the task that needs them**.

**Use Case:** Files created during workflow execution

**Example:**
```yaml
task:
  - create-todos:
      prompt: "Create a todo list at {{topic-doc-root}}/todo.md"
  - process-todos:
      prompt: "Process item: {{loop.item.text}}"
      loop:
        type: todo-list
        source: "{{topic-doc-root}}/todo.md"  # Validated just-in-time
```

**Validation:**
- File existence checked when `process-todos` begins (not at parse-time)
- Allows previous tasks to create required files
- Fails if file doesn't exist when needed

**When:** Immediately before executing the task that needs the resource
**Failure behavior:** Controlled by `on-error` setting

### Validation Lifecycle Summary

```
1. Parse-time (Linting)
   ↓ YAML syntax, schema, variable definitions

2. Start-time (Runtime - Early)
   ↓ ensure.mcps, ensure.tools

3. Task Execution
   ↓ Just-in-time validation for each task
   └─ Loop source files, file references (@syntax)
```

### Error Handling

Controlled by the `on-error` field:

- `fail` (default) - Stop workflow on first error
- `continue` - Log error and continue with remaining tasks
- `skip` - Skip failed task and continue

**Parse-time errors always fail** - `on-error` only applies to runtime validation.

---

## CLI Invocation

### Execution Model

For each task, the meta-agent follows this process:

1. **Expands template variables** in the prompt string (Jinja2 evaluation)
2. **Delegates to the adapter** for the specified `cli-agent`
3. **Adapter constructs CLI command** using tool-specific syntax
4. **Executes as shell command** in the working directory
5. **Waits for completion** (synchronous execution)
6. **Checks exit code**: 0 = success, non-zero = failure

### Adapter Responsibility

Each adapter (opencode, claude, codex, pi, vtcode, antigravity) is responsible for:

**Prompt Delivery:**
- How to pass prompts to the CLI tool (stdin, command argument, temp file, etc.)
- Tool-specific invocation patterns

**Configuration Translation:**
- Translating `cli-agent-config` fields to tool-specific CLI arguments
- Handling `raw-args` pass-through

**Escaping:**
- Proper escaping of quotes in prompts
- Shell special character handling
- Template variable expansions containing special characters

**Example Adapter Translations:**

Given this YAML:
```yaml
cli-agent: "claude"
cli-agent-config:
  skip-confirmations: true
  timeout: 3600
task:
  - analyze:
      prompt: "Analyze the codebase and write results to analysis.md"
```

**Claude Adapter might invoke:**
```bash
cd /working/directory
claude-code --dangerously-skip-everything "Analyze the codebase and write results to analysis.md"
```

**Codex Adapter might invoke:**
```bash
cd /working/directory
codex --full-auto "Analyze the codebase and write results to analysis.md"
```

**Gemini Adapter might invoke:**
```bash
cd /working/directory
gemini-cli --auto-approve --prompt="Analyze the codebase and write results to analysis.md"
```

### Working Directory

The CLI process always executes in `{{directory}}` (the working directory specified in YAML, with `~` expansion applied).

### Environment Variables

The meta-agent may set environment variables to provide context:

- `META_AGENT_TASK="task-name"` - Current task identifier (optional)
- Inherits all parent process environment variables

### Process Management

**Synchronous Execution:**
- Meta-agent waits for CLI process to complete before proceeding
- No parallel CLI invocations for sequential tasks
- Parallel tasks may spawn multiple CLI processes simultaneously

**Exit Code Handling:**
- Exit code 0 = task success
- Non-zero exit code = task failure
- Failure behavior controlled by `on-error` setting

**Timeout:**
- Timeout specified in `cli-agent-config.timeout` (in seconds)
- Applied per CLI invocation (per task execution)
- If CLI process exceeds timeout, it is terminated
- Treated as task failure (controlled by `on-error` setting)

### Special Character Handling

**Template Expansion First:**
```yaml
template-variables:
  file: "my-file.md"
task:
  - read:
      prompt: "Read {{file}} and summarize"
# Meta-agent expands to: "Read my-file.md and summarize"
# Then passes to adapter
```

**Adapter Escaping:**
The adapter receives the expanded string and handles:
- Quote escaping for shell safety
- Special characters in the command line
- Multi-line prompts

---

## Complete Example

See `example-workflow.yaml` for a fully functional example workflow that:
- Gathers research from Linear, Notion, and GitHub
- Creates comprehensive documentation with multiple sections
- Uses parallel sub-agents for research tasks
- Validates and formats output
- Uses looping to fill out incomplete sections

---

## Philosophy & Design Principles

### No Artificial Capability Limits

The meta-agent does not impose artificial limits on capabilities that may improve over time:

**No limits on:**
- **Parallel execution**: Unlimited parallel tasks allowed (hardware/OS limits apply naturally)
- **Task count**: Workflows can have any number of tasks
- **Prompt size**: Meta-agent doesn't restrict prompt length (CLI tools may have their own limits)
- **Loop iterations**: Loops can process any number of items

**Rationale:**
- AI CLI capabilities expand over time
- Hardware improves over time
- Artificial limits become outdated and frustrating
- Real limits (memory, CPU, API rate limits) will naturally constrain execution
- Let capabilities grow without artificial bottlenecks

### File-Based Communication (No Inter-Prompt Variables)

Tasks communicate exclusively through the filesystem - there are no variables passed between prompts.

**How it works:**
- Tasks write outputs to files (file paths specified in prompts)
- Subsequent tasks read from those files (file paths specified in prompts)
- File paths are embedded in prompt text, not in separate YAML `output:` or `input:` fields

**Example:**
```yaml
task:
  - analyze:
      prompt: "Analyze the codebase and write detailed results to analysis.md"
  - summarize:
      prompt: "Read analysis.md and create an executive summary in summary.md"
  - report:
      prompt: "Combine analysis.md and summary.md into final-report.md"
```

**Rationale:**
- **Loose coupling**: Tasks are independent, connected only by file contracts
- **Debuggable**: All intermediate data is on disk for inspection
- **Simple**: No need for output/input field management in YAML
- **Transparent**: File-based communication is explicit and traceable

**Future:** Validators (see planning.txt) will enable verification that expected files exist and contain valid data, without introducing explicit output fields in the YAML structure.

### Stateless Execution

The meta-agent is stateless - no persistent state files are maintained across runs.

**Current behavior:**
- Each workflow execution starts fresh
- Ordered execution provides inherent state (completed tasks in current session don't re-run)
- If workflow fails, user re-runs entire workflow
- No cross-session resumability

**Rationale:**
- **Simplicity**: No state file format or management logic needed
- **Predictability**: Same YAML always runs the same way
- **Debuggability**: No hidden state to reason about

**Future:** Workflow state management (see planning.txt) may be added for long-running workflows requiring cross-session resumability.

### CLI Output is Opaque

The meta-agent treats CLI stdout/stderr as opaque - all meaningful task output must be written to files.

**How it works:**
1. Meta-agent spawns CLI process with prompt
2. Waits for process completion
3. Checks exit code (0 = success, non-zero = failure)
4. **Ignores** stdout/stderr content

**Rationale:**
- **Consistent** with file-based communication philosophy
- **Portable** across different CLI tools with varying output formats
- **Forces good practices**: Tasks must produce persistent, structured output

**Future:** CLI output may be captured and logged for debugging purposes, but will never be used for workflow orchestration logic.

### Sub-Agents are Prompt-Based

Sub-agents are **not configured in YAML**. They are invoked by the CLI agent via natural language prompts.

**How it works:**
- YAML defines prompts that request sub-agents (e.g., "Use sub-agents in parallel")
- The CLI agent (Claude CLI, etc.) handles sub-agent spawning
- Meta-agent only orchestrates the high-level workflow

**Example:**
```yaml
includes:
  use-subagents: "Use sub-agents to accomplish this task in parallel"

task:
  - my-task:
      prompt: "Process data"
      include:
        - use-subagents  # CLI agent will spawn sub-agents
```

**Rationale:** Sub-agent behavior is CLI-specific and best controlled via natural language rather than rigid configuration.

### Template Variables vs. Runtime State

- **Template variables**: Defined once, evaluated at workflow startup, immutable
- **Runtime state**: Managed through filesystem (files created/modified by tasks)

Template variables are for static configuration, not for passing data between tasks.

### Branching

There is no hard-coded branching mechanism. Branching logic should be:
- Implemented via prompting the agent to make decisions
- Controlled through conditional includes
- Managed through loop types

**Future:** Conditional execution (see planning.txt) may be added for explicit branching support.

---

## Future Enhancements

See `planning.txt` for planned features including:
- Error handling and retry policies
- Conditional execution
- Resource management
- State persistence and checkpointing
- Approval gates
- Additional loop types
- Agent profiles
- Observability and metrics

---

## Limitations

### Current Limitations

1. **Nested list tasks are rejected**: `task: [ … ]` inside a task fails schema validation even though
   this spec documents it; use the mapping form (`docs/AUTHORING.md`).
2. **Hybrid templating**: filters, conditionals and loops are supported, but any `{%`, `{#`, `{{-` or
   `|` flips the whole string to Jinja2, where hyphenated variable names need `{{ v['name'] }}`.
3. **Silent undefined variables**: typos render as empty strings instead of failing.
4. **`run --resume` is a no-op**: resumption is per loop via `resume: true` + `checkpoint-file`.
5. **`ensure.mcps` is a warning-only stub**: only `ensure.tools` is enforced.
6. **Adapter flag drift**: codex-cli 0.153.4 rejects `--full-auto`, `-a`, and `--search`; the Claude
   adapter emits `--allowed-mcp-server-names`, which current `claude` rejects
   (`docs/ADAPTER_TROUBLESHOOTING.md`).
7. **No logging configuration**: progress and errors go to stderr; `--debug` adds argv and agent output.
8. **No nested loops** and **no fail-fast validators** (every validator runs, then retries apply).

### Design Decisions (Not Limitations)

These are intentional design choices documented in Philosophy section:
- File-based communication (no inter-prompt variables)
- No workflow-level state between runs; loops may persist progress through `checkpoint-file`, and the
  interface runner keeps run history in SQLite (`docs/INTERFACE_RUNNER.md`)
- CLI output is opaque (ignored by meta-agent)
- Sub-agents are prompt-based (not YAML-configured)

---

## Best Practices

### 1. Use Meaningful Variable Names

```yaml
# Good
template-variables:
  service-name: "example-service"
  docs-output-dir: "{{service-name}}/docs"

# Avoid
template-variables:
  sn: "example-service"
  dod: "{{sn}}/docs"
```

### 2. Group Related Tasks

```yaml
task:
  - data-gathering:
      fetch-linear: ...
      fetch-notion: ...
      fetch-github: ...
  - analysis:
      analyze-data: ...
      create-report: ...
```

### 3. Use Includes for Common Patterns

```yaml
includes:
  use-subagents: "Use sub-agents in parallel for this task."
  validate-output: "Validate the output against the schema."

task:
  - task-1:
      prompt: "Do work"
      include:
        - use-subagents
        - validate-output
```

### 4. Leverage Parallel Execution

```yaml
# Sequential (slow)
task:
  - fetch-a:
      prompt: "Fetch A"
  - fetch-b:
      prompt: "Fetch B"
  - fetch-c:
      prompt: "Fetch C"

# Parallel (fast)
task:
  - fetch-all:
      fetch-a:
        prompt: "Fetch A"
      fetch-b:
        prompt: "Fetch B"
      fetch-c:
        prompt: "Fetch C"
```

### 5. Validate Early

```yaml
ensure:
  mcps:
    - required-mcp-1
    - required-mcp-2
  tools:
    - required-tool-1
    - required-tool-2
```

### 6. Document Complex Variable Dependencies

```yaml
template-variables:
  # Base paths
  service: "myservice"
  root: "/var/app"

  # Derived paths (built from base paths)
  service-dir: "{{root}}/{{service}}"
  config-file: "{{service-dir}}/config.yaml"
  logs-dir: "{{service-dir}}/logs"
```

---

## Schema Reference

### YAML Type Definitions

```typescript
interface WorkflowConfig {
  directory: string;
  "cli-agent"?: "opencode" | "claude" | "codex" | "pi" | "vtcode" | "antigravity";
  "cli-agent-config"?: CliConfig;
  "on-error"?: "fail" | "continue" | "skip";
  "template-variables": Record<string, string>;
  ensure?: {
    mcps?: string[];
    tools?: string[];
  };
  includes?: Record<string, string>;
  task: Task[];
}

interface CliConfig {
  "skip-confirmations"?: boolean;
  "additional-dirs"?: string[];
  timeout?: number;
  permissions?: string[];
  model?: string;
  "mcp-config-file"?: string;
  "raw-args"?: string[];
  [key: string]: any; // Allow CLI-specific options
}

interface Task {
  [taskName: string]: TaskDefinition | TaskDefinition[];
}

interface TaskDefinition {
  prompt?: string;
  include?: string[];
  loop?: Loop;
  "on-error"?: "fail" | "continue" | "skip";  // Override workflow-level on-error
  [nestedTaskName: string]: any;
}

// Base loop configuration (common to all loop types)
interface LoopConfig {
  type: string;
  "checkpoint-file"?: string;
  resume?: boolean;
  retry?: {
    "max-attempts": number;
    "on-failure": "skip" | "retry" | "abort";
  };
  "exit-on"?: Array<{
    condition: string;
    action?: string;
    value?: any;
  }>;
}

// Type-specific loop configurations
interface TodoListLoop extends LoopConfig {
  type: "todo-list";
  source: string;
  "mark-in-progress"?: boolean;
  "mark-complete"?: boolean;
}

interface CsvLoop extends LoopConfig {
  type: "csv";
  source: string;
  "skip-header"?: boolean;
  columns?: string[];
  filter?: {
    column: string;
    value: any;
  };
}

interface GlobLoop extends LoopConfig {
  type: "glob";
  pattern: string;
  exclude?: string[];
  sort?: "name" | "modified" | "size" | "created";
}

type Loop = TodoListLoop | CsvLoop | GlobLoop;
```

---

## Troubleshooting

### YAML Syntax Errors

**Problem:** YAML fails to parse
**Solution:**
- Check indentation (use spaces, not tabs)
- Ensure proper quoting of strings with special characters
- Validate with `python3 -c "import yaml; yaml.safe_load(open('file.yaml'))"`

### Template Variable Not Resolving

**Problem:** `{{variable}}` appears literally in prompts
**Solution:**
- Check that variable is defined in `template-variables`
- Check spelling and capitalization
- Ensure variable is not circularly defined

### Task Not Executing

**Problem:** Task appears in config but doesn't run
**Solution:**
- Ensure task has a `prompt` field (tasks without prompts are just grouping containers)
- Check that parent tasks completed successfully
- Verify task is in the correct position in the execution order

### MCP/Tool Not Found

**Problem:** Workflow fails at startup with missing MCP/tool
**Solution:**
- Install the required MCP: `mcp install <name>`
- Install the required tool: `brew install <name>` or equivalent
- Remove from `ensure` block if not actually required

---

## Appendix: Practical JSON Loop Examples

### Real-World Pattern: Log Analysis

Process application logs in JSONL format, extracting errors and warnings:

```yaml
task:
  - extract-errors:
      prompt: "Save error to errors/{{loop.index}}.txt"
      loop:
        type: jsonl
        source: "application.jsonl"
        filter:
          key: "level"
          value: "ERROR"

  - extract-warnings:
      prompt: "Save warning to warnings/{{loop.index}}.txt"
      loop:
        type: jsonl
        source: "application.jsonl"
        filter:
          key: "level"
          value: "WARN"
```

### Real-World Pattern: Multi-Stage Filtering

Progressive filtering with intermediate files:

```yaml
task:
  - filter-active:
      prompt: "Extract active users to active.json"
      loop:
        type: json
        source: "all-users.json"
        filter:
          key: "status"
          value: "active"

  - filter-admins:
      prompt: "Process admin: {{loop.item.name}}"
      loop:
        type: json
        source: "active.json"
        filter:
          key: "role"
          value: "admin"
```

Or use multi-condition filter:

```yaml
task:
  - filter-active-admins:
      prompt: "Process {{loop.item.name}}"
      loop:
        type: json
        source: "all-users.json"
        filter:
          conditions:
            - key: "status"
              value: "active"
            - key: "role"
              value: "admin"
          operator: "AND"
```

### Real-World Pattern: Nested Data Processing

Extract and process deeply nested organizational data:

```yaml
template-variables:
  org-file: "{{gitroot}}/data/organization.json"

task:
  - process-engineers:
      prompt: "Review engineer {{loop.item.name}}: {{loop.item.title}}"
      loop:
        type: json
        source: "{{org-file}}"
        path: "departments.engineering.employees"
        filter:
          key: "status"
          value: "active"
```

### Real-World Pattern: Parallel Processing

Process large dataset with parallel workers:

```yaml
task:
  - setup:
      prompt: "Create dataset.json with 1000 items"

  - process-parallel:
      prompt: "Process item {{loop.item.id}}"
      loop:
        type: json
        source: "dataset.json"
        workers: 8
        checkpoint-file: ".progress.json"
        resume: true
      retry:
        max-attempts: 3
        on-failure: skip
```

### Real-World Pattern: Data Transformation Pipeline

Transform JSON data through multiple stages:

```yaml
task:
  - stage1-extract:
      prompt: "Extract field {{loop.item.key}} from raw data"
      loop:
        type: json
        source: "raw-data.json"

  - stage2-transform:
      prompt: "Transform {{loop.item}} and save to processed/"
      loop:
        type: json
        source: "extracted-data.json"

  - stage3-validate:
      prompt: "Validate {{loop.item}}"
      loop:
        type: json
        source: "processed-data.json"
      validate:
        - json-valid: "output/{{loop.item.id}}.json"
```

---

## See Also

- **examples/** directory - 36 example workflows including comprehensive JSON loop tests
- **README.md** - User-facing documentation with detailed examples
- **CLAUDE.md** - Developer guide for contributing to agent-yaml
