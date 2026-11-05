# Meta-Agent Yaml Config

## Core Architecture
- Meta-agent yaml format for task tracking
- Template variables (both user-defined and reserved/automatic)
- Reserved template variables automatically injected by the meta-agent
- Config layering (base.yaml for common tags)

## CLI Adapter Layer
The system supports multiple AI CLI tools through a generic adapter interface:

**Supported CLI Tools:**
- Claude CLI (claude-code)
- OpenAI Codex (openai cli)
- Gemini CLI (gemini cli)
- Extensible to other AI CLI tools

**Adapter Responsibilities:**
- Translate generic `cli-agent-config` block to tool-specific command-line arguments
- Map generic concepts (sub-agents, timeouts, permissions) to tool-specific equivalents
- Handle tool-specific features while maintaining common interface
- Provide capability detection (what features are available in each CLI)

**Common Interface:**
- Working directory configuration
- Timeout settings
- Permission/safety flags
- Extension/MCP management
- Sub-agent invocation

## Agent Management
- **Sub-agents are prompt-based** (not YAML-configured)
  - Sub-agent invocation is controlled via natural language prompts
  - The CLI agent handles sub-agent spawning based on prompt instructions
  - Meta-agent YAML only defines the prompts that request sub-agents
- Quick tags for prompts (use sub-agents)
    - e.g.: use-agents: "Use sub-agents to accomplish all tasks."
    - e.g.: use-agents-parallel: "Use many sub-agents in parallel to accomplish all tasks."
- Permissions specification for AI CLI runner
- Agent verification (CLI commands + agents in place)
- CLI-specific configurations mapped via adapter layer

## Runtime Features
- Cron job style runs
- Configurable timeouts for AI CLI tools to prevent premature termination
- Which MCPs/extensions to include and which ones to leave out on a per-task basis
- Means by which to loop over things (functions/classes/files/folders, grep/glob/find filters)
- Support for CLI-specific features through adapter configuration

## Includes (Prompt Fragments)

Includes are **simple string concatenations** that get appended to task prompts.

**Mechanism:**
1. Prompt text comes first
2. Includes are appended in order, separated by single spaces
3. Template variables are expanded after concatenation
4. No special logic - just string concatenation

**Example:**
```yaml
includes:
  use-subagents: "Use sub-agents in parallel."
  validate: "Validate all work."

task:
  - my-task:
      prompt: "Do work"
      include:
        - use-subagents
        - validate
```

**Result:** `"Do work Use sub-agents in parallel. Validate all work."`

---

## Reserved Template Variables

The meta-agent automatically injects the following reserved variables into every workflow. These are available in all template-variables, includes, and prompts.

### Auto-Injected Variables

**`{{gitroot}}`**
- Git repository root directory
- Determined by walking up from `{{directory}}` to find `.git/`
- **Fallback**: If not in a git repository, falls back to `{{directory}}`
- Always uses absolute path

**`{{datetime}}`**
- Current date and time in ISO 8601 format (local timezone)
- Format: `YYYY-MM-DDTHH:MM:SS.sss±HH:MM`
- Example: `2025-10-01T23:45:30.123-07:00` (Pacific Time)
- **Evaluated once at workflow start** - same value for all tasks in workflow
- **Consistency**: All tasks in a workflow see the same datetime value
- **On resumption**: When resuming from checkpoint, uses original workflow start time (not current time)

**`{{user}}`**
- Current system username
- Determined from environment variables: USER, USERNAME, or LOGNAME (checked in order)
- **Fallback**: If no environment variable found, uses `"unknown"`
- Example: `user`

**`{{directory}}`**
- Working directory from YAML config
- Always expanded to absolute path (resolves `~`)
- **Validation**: Directory must exist (checked at parse-time)
- Example: `~/projects/example-repo`

### Precedence Rules

1. **Reserved variables cannot be overridden** - User-defined variables with reserved names are ignored
2. **Evaluation happens first** - Reserved variables are injected before user template-variables are evaluated
3. **Always available** - Reserved variables are available in all contexts (template-variables, includes, prompts, loop configs)

### Example Usage

```yaml
template-variables:
  repo-root: "{{gitroot}}"
  timestamp: "{{datetime}}"
  output-file: "{{gitroot}}/reports/{{user}}-{{datetime}}.md"

task:
  - log-start:
      prompt: "Starting workflow in {{directory}} at {{datetime}} by {{user}}"
```

---

## Template Variable Features

### Syntax

Template variables use **minimal Jinja2 syntax**:

**Supported:**
- Variable substitution: `{{variable-name}}`
- Variable references: Variables can reference other variables

**Not Supported (for now):**
- Filters: `{{var | upper}}`, `{{var | default('x')}}`
- Conditionals: `{% if condition %}...{% endif %}`
- Loops: `{% for item in list %}...{% endfor %}`
- Macros, blocks, or other Jinja2 advanced features

**Future**: Full Jinja2 support may be added (see planning.txt) - could enable conditional execution, string manipulation, and branching logic.

### Variable Evaluation

```yaml
template-variables:
  service: "example-service"
  docs: "{{service}}/docs"           # References {{service}}
  guide: "{{docs}}/guide.md"         # References {{docs}}, which references {{service}}
```

**Evaluation order:**
1. Reserved variables injected first (`{{gitroot}}`, `{{datetime}}`, `{{user}}`, `{{directory}}`)
2. User variables evaluated in dependency order
3. Variables expanded in prompts and includes

### Circular Dependency Detection

The meta-agent uses a **spanning tree algorithm** to detect circular dependencies:

```yaml
template-variables:
  a: "{{b}}"
  b: "{{c}}"
  c: "{{a}}"  # Error: Circular dependency detected
```

**Error behavior:**
- Parse-time error (workflow never starts)
- Error message identifies the circular chain: `a → b → c → a`
- Workflow must be fixed before execution

---

## Validation

The meta-agent performs two types of validation:

### 1. Linting (Parse-time)

Validates YAML structure and schema before any execution:

- **YAML syntax** - Is the file parseable?
- **Schema validation** - Are all required fields present?
- **Field types** - Are values the correct type (string, list, object)?
- **Template variable references** - Are all variables defined?
- **Loop configuration** - Are loop types valid and properly configured?

**When:** Immediately upon loading the YAML file
**Failure behavior:** Hard fail - workflow never starts

### 2. Runtime Validation (Start-time and Just-in-time)

Validates requirements when they're actually needed:

**Start-time validation:**
```yaml
ensure:
  mcps:
    - notion
    - linear
  tools:
    - gh
```
- Check MCPs/tools exist before workflow starts
- Only validates items in the `ensure:` block

**Just-in-time validation:**
```yaml
loop:
  type: todo-list
  source: "tasks.md"  # Created by previous task
```
- Validate file existence right before the task that needs it
- Allows workflows to create files that are used later

**Example workflow:**
```yaml
task:
  - create-todos:
      prompt: "Create a todo list at {{topic-doc-root}}/todo.md"
  - process-todos:
      prompt: "Process item: {{loop.item.text}}"
      loop:
        type: todo-list
        source: "{{topic-doc-root}}/todo.md"  # Validated just-in-time, not at parse
```

### Error Handling

Configurable via workflow-level setting:

```yaml
on-error: fail  # Default: fail fast on any error
```

**Supported values:**
- `fail` (default) - Stop workflow on first error
- `continue` - Log error and continue with remaining tasks
- `skip` - Skip failed task and continue

**Design Decision:** Default to `fail` because continuing on errors can introduce unexpected behavior and cascading failures.

## Documentation
- Good documentation for AI agent self-service, so that AI assistants can define their own agent runs using this YAML format
- CLI-specific adapter documentation for each supported tool (Claude CLI, OpenAI Codex, Gemini CLI)

## Limitations

### Current Limitations
1. **No hard-coded branching**: Conditional logic must be implemented via prompting (by design)
2. **Minimal Jinja2 support**: Only variable substitution, no filters/conditionals (see planning.txt for full Jinja2)
3. **Limited loop types**: Currently supports todo-list, CSV, and glob (see planning.txt for future types)
4. **No task validators**: Cannot verify task output quality (planned, see planning.txt)
5. **Stateless execution**: No cross-session resumability (may be added, see planning.txt)
6. **No logging configuration**: Errors go to stderr only (planned, see planning.txt)

### Design Decisions (Not Limitations)
These are intentional design choices (see Philosophy section):
- File-based communication (no inter-prompt variables)
- Stateless execution (no persistent state files)
- CLI output is opaque (ignored by meta-agent)
- Sub-agents are prompt-based (not YAML-configured)

## Philosophy

### CLI-Agnostic Design
The meta-agent YAML format should work with multiple AI CLI tools (Claude CLI, OpenAI Codex, Gemini CLI, etc.) through a generic adapter layer. We should not be overly tied to any single CLI tool.

### No Inter-Prompt Variables (File-Based Communication)
No variables are passed between prompts. All task communication happens through the filesystem:

- Tasks write outputs to files (specified in prompts)
- Subsequent tasks read from those files (specified in prompts)
- File paths are embedded in prompt text, not in separate YAML fields

**Example:**
```yaml
task:
  - analyze:
      prompt: "Analyze the codebase and write results to analysis.md"
  - summarize:
      prompt: "Read analysis.md and create a summary in summary.md"
```

**Rationale:**
- Enforces loose coupling between tasks
- Makes workflows debuggable (all intermediate data is on disk)
- Keeps YAML simple (no output/input field management)
- Allows manual inspection of task outputs

**Future:** Validators (see planning.txt) will enable checking that expected files exist and contain valid data, without introducing explicit output fields.

### Stateless Execution
The meta-agent is stateless - workflows execute from start to finish without persistent state files.

**Current behavior:**
- Each workflow run starts fresh
- Ordered execution provides inherent state (completed tasks don't re-run)
- If workflow fails, user re-runs the entire workflow
- No cross-session resumability

**Rationale:**
- Simplicity - no state file management
- Predictability - same workflow always runs the same way
- Easier debugging - no hidden state

**Future:** Workflow state management (see planning.txt) may be added for long-running workflows that need resumability across sessions.

### CLI Output is Opaque
The meta-agent ignores CLI stdout/stderr. All meaningful output must be written to files.

**How it works:**
- Meta-agent spawns CLI process
- Waits for completion
- Checks exit code (0 = success, non-zero = failure)
- Ignores stdout/stderr

**Rationale:**
- Consistent with file-based communication philosophy
- CLI output is unpredictable and tool-specific
- Forces tasks to produce structured, persistent output

**Future:** CLI output may be logged for debugging, but will never be used for workflow logic.

### Generic Adapter Layer
Since most AI CLI tools have roughly similar inputs/outputs, we maintain a thin adapter layer to translate between the generic YAML config and tool-specific invocations.

### No Artificial Capability Limits
The meta-agent does not impose artificial limits on capabilities that may improve over time:

- **No parallel execution cap**: Unlimited parallel tasks allowed (hardware/OS limits apply)
- **No task count limits**: Workflows can have any number of tasks
- **No prompt size limits**: Meta-agent doesn't restrict prompt length (CLI tools may have limits)
- **No loop iteration limits**: Loops can process any number of items

**Rationale:**
- AI CLI capabilities expand over time
- Hardware improves over time
- Artificial limits become outdated and frustrating
- Real limits (memory, CPU, API rate limits) will naturally constrain execution

---

## CLI Invocation

### Execution Model

For each task, the meta-agent:

1. **Expands template variables** in the prompt string
2. **Delegates to the adapter** for the specified `cli-agent`
3. **Adapter constructs CLI command** according to tool-specific syntax
4. **Executes as shell command** in the working directory
5. **Waits for completion** (synchronous execution)
6. **Checks exit code**: 0 = success, non-zero = failure

### Adapter Responsibility

Each adapter (claude, openai, gemini) is responsible for:
- How to pass prompts to its CLI tool (stdin, argument, file, etc.)
- How to translate generic config to tool-specific command-line arguments
- How to handle special characters and escaping in prompts
- Tool-specific invocation patterns

**Example Adapter Translations:**

```yaml
cli-agent: "claude"
cli-agent-config:
  skip-confirmations: true
prompt: "Analyze the codebase"
```

**Claude Adapter might invoke:**
```bash
claude-code --dangerously-skip-everything "Analyze the codebase"
```

**OpenAI Adapter might invoke:**
```bash
echo "Analyze the codebase" | openai-cli --yes
```

**Gemini Adapter might invoke:**
```bash
gemini-cli --auto-approve --prompt="Analyze the codebase"
```

### Working Directory

The CLI process always executes in `{{directory}}` (the working directory specified in YAML config, with `~` expanded).

### Environment Variables

The meta-agent may set environment variables to provide context to the CLI:
- `META_AGENT_TASK="task-name"` - Current task identifier (optional)
- Inherits all parent process environment variables

### Special Character Handling

The adapter is responsible for proper escaping of:
- Quotes in prompts
- Shell special characters
- Template variable expansions containing special characters

The meta-agent expands template variables before passing to the adapter, so the adapter receives the final prompt string.

---

Workflow for documentation - see `example-workflow.yaml` for the full workflow example.

---

## Task Execution Order

Task execution order is **determined by YAML structure**, not by explicit flags.

### Execution Rules

1. **Array/List items run sequentially** - Tasks in a YAML list execute one after another
2. **Object/Dict keys run in parallel** - Tasks at the same nesting level within an object execute concurrently
3. **Nested lists run sequentially** - Lists nested within object values execute in order
4. **Only tasks with `prompt` are executable** - Objects without `prompt` are grouping containers

### Sequential Execution

```yaml
task:
  - step-1:
      prompt: "First task"
  - step-2:
      prompt: "Second task (runs after step-1)"
  - step-3:
      prompt: "Third task (runs after step-2)"
```

**Execution:** step-1 → step-2 → step-3 (in order)

### Parallel Execution

```yaml
task:
  - parallel-group:
      task-a:
        prompt: "Runs in parallel"
      task-b:
        prompt: "Runs in parallel"
      task-c:
        prompt: "Runs in parallel"
```

**Execution:** task-a, task-b, task-c all run simultaneously

### Mixed Sequential and Parallel

```yaml
task:
  - phase-1:
      prep-a:
        prompt: "Parallel prep task A"
      prep-b:
        prompt: "Parallel prep task B"
  - phase-2:
      - substep-1:
          prompt: "Sequential substep 1"
      - substep-2:
          prompt: "Sequential substep 2"
```

**Execution:**
1. prep-a and prep-b run in parallel
2. Wait for both to complete
3. substep-1 runs
4. substep-2 runs after substep-1

**Design Decision:** Structure-based execution eliminates the need for explicit `parallel: true` flags while keeping the YAML readable and intuitive.

---

## Looping Mechanisms

### How Loops Work

Loops execute tasks repeatedly over collections. All loops share common infrastructure while exposing type-specific data.

**Core Concept:**
- Single task definition becomes multiple executions
- One execution per item in the collection
- Code-parseable, deterministic iteration
- State persistence for resume capability
- **Loop processing is external to the CLI agent** - the meta-agent orchestrator handles iteration and invokes the CLI agent once per item with expanded variables

**Execution Flow:**
1. Meta-agent loads source data (todo file, CSV, glob results)
2. For each item:
   - Meta-agent injects loop variables into context
   - Meta-agent expands template variables in prompt
   - Meta-agent invokes CLI agent with fully expanded prompt
   - Meta-agent saves checkpoint (if enabled)
3. Complete or resume from checkpoint

**Common Loop Variables:**

Available in all loop types:
- `{{loop.index}}` - Objective iteration count (0-based, same across all types)
- `{{loop.total}}` - Total items in loop
- `{{loop.remaining}}` - Items remaining
- `{{loop.item}}` - Complete object containing all iteration-specific data (structure varies by type)
  - All specifics for this iteration are properties of `{{loop.item}}`
  - Includes content, metadata, position info, etc.

**Variable Injection Order:**
1. Global template variables
2. Loop variables (`{{loop.index}}`, `{{loop.total}}`, etc.)
3. Type-specific variables (`{{loop.file}}`, `{{loop.item.column}}`, etc.)

**Loop Control Options:**

*Checkpointing (Optional):*
```yaml
loop:
  checkpoint-file: ".loop-state.json"  # If specified, creates checkpoint file
  resume: true                          # Resume from checkpoint on restart
```

**Note:** Checkpoints are **not** created unless `checkpoint-file` is explicitly specified. Without checkpointing, failed loops must restart from the beginning.

*Retry & Error Handling:*
```yaml
loop:
  retry:
    max-attempts: 3
    on-failure: skip  # skip, retry, abort
  exit-on:
    - condition: max-iterations
      value: 50
```

*State Format:*
```json
{
  "type": "todo-list",
  "current_index": 3,
  "completed_items": ["item-1", "item-2", "item-3"],
  "failed_items": []
}
```

---

### Loop Type Implementations

#### 1. Markdown Todo List

Iterate over uncompleted todo items in markdown files.

**Configuration:**
```yaml
loop:
  type: todo-list
  source: "tasks.md"
  mark-in-progress: true  # Optional: Mark as [-] when processing
  mark-complete: true     # Optional: Mark as [x] when done
```

**Type-Specific Variables:**

`{{loop.item}}` is an object containing:
- `{{loop.item.text}}` - The todo text
- `{{loop.item.number}}` - Todo item number (1-based, actual todo count)
- `{{loop.item.line}}` - Line number in file

**Implementation:**
- Parses markdown for `- [ ]` items
- Skips `- [-]` (in-progress) and `- [x]` (completed)
- Optionally marks items as in-progress/complete
- Atomic file updates (temp file + rename)

**Example:**
```yaml
task:
  - process-todos:
      prompt: "Complete: {{loop.item.text}} (todo #{{loop.item.number}}, iteration {{loop.index}}/{{loop.total}})"
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
  filter:                    # Optional
    column: status
    value: active
```

**Type-Specific Variables:**

`{{loop.item}}` is an object containing:
- `{{loop.item.column_name}}` - Any column value (dynamic based on columns config)
- `{{loop.item.row}}` - Row number (1-based, actual row in CSV)

**Implementation:**
- Standard CSV parser with quote/escape handling
- Optionally skips header row
- Filters applied during iteration
- Column values accessible as object properties

**Example:**
```yaml
task:
  - notify-users:
      prompt: "Email {{loop.item.name}} at {{loop.item.email}} (row {{loop.item.row}}, iteration {{loop.index}})"
      loop:
        type: csv
        source: "users.csv"
        skip-header: true
        columns: [id, name, email]
        filter:
          column: status
          value: active
```

---

#### 3. File Glob Patterns

Iterate over files matching glob patterns.

**Configuration:**
```yaml
loop:
  type: glob
  pattern: "agent_yaml/**/*.ts"
  exclude: ["**/*.test.ts"]  # Optional
  sort: modified             # Optional: name, modified, size, created
```

**Type-Specific Variables:**

`{{loop.item}}` is an object containing:
- `{{loop.item.path}}` - Full file path
- `{{loop.item.filename}}` - Filename without path
- `{{loop.item.extension}}` - File extension

For convenience, `{{loop.item}}` renders as the file path when used as a string.

**Implementation:**
- Supports `**` (recursive), `*` (wildcard), `{a,b}` (alternatives)
- Excludes via negative patterns
- Sorts by name/modified/size/created
- Results cached for loop duration

**Example:**
```yaml
task:
  - update-files:
      prompt: "Update imports in {{loop.item.path}} ({{loop.item.filename}}, iteration {{loop.index}})"
      loop:
        type: glob
        pattern: "agent_yaml/**/*.ts"
        exclude: ["**/*.test.ts"]
        sort: modified
```

---

## Advanced Loop Features

### Loop Composition

Loops can be chained via sequential tasks (not nested within a single task):

```yaml
task:
  - loop-files:
      prompt: "Process {{loop.item.path}} and generate todos"
      loop:
        type: glob
        pattern: "*.csv"

  - loop-todos:
      prompt: "Complete {{loop.item.text}}"
      loop:
        type: todo-list
        source: "generated-todos.md"
```

### Variable Expansion Example

```yaml
template-variables:
  project: "myapp"

task:
  - process:
      prompt: "{{project}}: Process {{loop.item.path}} (iteration {{loop.index}}/{{loop.total}})"
      loop:
        type: glob
        pattern: "agent_yaml/**/*.ts"
```

**Expands to:** `"myapp: Process agent_yaml/index.ts (iteration 0/15)"`

### Performance Considerations

- **Lazy Loading**: Items loaded one at a time
- **Streaming**: Large CSVs processed in streaming mode
- **Parallel Sub-Agents**: Loop iterations can spawn parallel sub-agents
- **Caching**: File lists cached for loop duration
