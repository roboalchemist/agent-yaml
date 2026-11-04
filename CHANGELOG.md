# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-10-02

### Added

#### Core Orchestration Engine
- **YAML Workflow Parser**: Parse and execute declarative YAML workflows that orchestrate AI CLI agents
- **Schema Validation**: Comprehensive parse-time validation of workflow structure, required fields, and types
- **Multi-Agent Support**: Execute workflows across Claude, Gemini, Qwen, and Codex CLI agents with a single YAML file
- **Structure-Based Parallelism**: Control task execution flow through YAML structure (object keys = parallel, array items = sequential)
- **Error Handling Strategies**: Configure global and task-level error handling with `on-error` (fail/continue/skip)
- **Exit Code Validation**: Reliable task success/failure detection based on CLI exit codes (output is opaque by design)

#### Template Variable System
- **Reserved Variables**: Four auto-injected variables available in all workflows:
  - `{{gitroot}}` - Git repository root (walks up directory tree to find .git/)
  - `{{datetime}}` - ISO 8601 timestamp (evaluated once at workflow start, preserved on resume)
  - `{{user}}` - System username (from USER/USERNAME/LOGNAME environment variables)
  - `{{directory}}` - Working directory (absolute path with tilde expansion)
- **User-Defined Variables**: Define custom variables with full dependency resolution
- **Circular Dependency Detection**: Automatic detection and reporting of variable reference cycles with complete dependency chain
- **Variable Interpolation**: Minimal Jinja2 template syntax (`{{var}}`) for variable substitution in prompts, includes, and configurations
- **CLI Overrides**: Override any user-defined variable at runtime using `--var key=value` flags
- **Undefined Variable Warnings**: Warnings for variables referenced in `--var` that don't exist in the workflow

#### Include System
- **Reusable Prompt Fragments**: Define prompt snippets once and include them in multiple tasks
- **Variable Interpolation**: Full template variable support within included content
- **String Concatenation**: Includes are concatenated as strings with configurable separators
- **Composability**: Build complex prompts from modular, maintainable components

#### Loop Types
- **Todo-List Loop**: Iterate over markdown checkbox lists with state management
  - Parse `[ ]` (pending), `[-]` (in-progress), `[x]` (complete) checkboxes
  - Auto-mark items as in-progress during execution and complete on success
  - Access `{{loop.index}}`, `{{loop.total}}`, `{{loop.item.text}}`, `{{loop.item.number}}`, `{{loop.item.line}}`
  - Retry failed items with configurable max-attempts
- **CSV Loop**: Iterate over CSV rows with filtering and header handling
  - Skip header rows and filter by column values
  - Access `{{loop.index}}`, `{{loop.item.column_name}}`, `{{loop.item.row}}`
  - Retry failed rows with configurable max-attempts
- **Glob Loop**: Iterate over files matching glob patterns
  - Exclude patterns and custom sort order support
  - Access `{{loop.index}}`, `{{loop.item.path}}`, `{{loop.item.filename}}`, `{{loop.item.extension}}`
  - Retry failed files with configurable max-attempts
- **Checkpoint/Resume System**: All loop types support optional checkpointing for workflow resumability
  - JSON checkpoint files track current index, completed items, and failed items
  - Resume interrupted workflows from the last successful checkpoint
  - Preserve original `{{datetime}}` variable on resume

#### CLI Adapter Layer
- **Generic Configuration**: Write agent-agnostic YAML that works across all supported CLI agents
- **Claude Adapter**: Full support for Claude CLI with MCP configuration, permission management, and directory access
- **Gemini Adapter**: Support for Gemini CLI with workspace management and approval modes
- **Qwen Adapter**: Support for Qwen CLI with YOLO mode and workspace configuration
- **Codex Adapter**: Support for Codex CLI with full-auto mode and directory switching
- **Capability Translation**: Automatic mapping of generic configurations to tool-specific CLI arguments:
  - `skip-confirmations` → `--dangerously-skip-permissions` (Claude), `--yolo` (Gemini/Qwen), `--full-auto` (Codex)
  - `additional-dirs` → `--add-dir` (Claude), `--workspace` (Gemini/Qwen), `-C` (Codex)
  - `timeout` → Subprocess timeout enforcement (per-task)
  - `model` → Model selection flags (tool-specific)
  - `mcp-config-file` → MCP configuration path (Claude)
- **Graceful Degradation**: Ignore unsupported features without failing the workflow

#### Validation System
- **Parse-Time Validation**:
  - YAML syntax correctness
  - Schema validation (required fields, correct types)
  - Template variable reference checking (all variables must be defined)
  - Circular dependency detection with full error reporting
  - Loop configuration validation (type-specific required fields)
  - Task structure validation (prompt XOR task structure)
- **Start-Time Validation**:
  - `ensure` block validation (verify MCPs and tools exist before workflow starts)
  - CLI executable availability checking
- **Just-In-Time Validation**:
  - Loop source file validation (checked right before loop execution, allows previous tasks to create files)

#### CLI Interface
- **Commands**:
  - `agent-yaml run <workflow.yaml>` - Execute a workflow
  - `agent-yaml validate <workflow.yaml>` - Validate workflow without execution
- **Flags**:
  - `--resume` - Resume from checkpoint file (preserves original datetime)
  - `--dry-run` - Show execution plan without running tasks
  - `--verbose` - Enable verbose logging (DEBUG level)
  - `--var key=value` - Override user-defined variables at runtime
- **Logging System**: Structured logging to stderr with configurable levels (DEBUG/INFO/WARN/ERROR)
- **Exit Codes**: Proper exit code handling (0 = success, non-zero = failure)

#### Documentation
- **Comprehensive Specifications**:
  - `spec/PROJECT_SPECS.md` - Architecture, philosophy, design decisions, reserved variables
  - `spec/YAML_SPEC.md` - Complete YAML format reference, field definitions, loop specs
  - `spec/ADAPTER_SPEC.md` - CLI adapter mappings, capability detection, translation logic
  - `spec/planning.txt` - Future enhancements and feature roadmap
- **Example Workflows**: Real-world example workflow (`spec/example-workflow.yaml`) demonstrating all features
- **README**: Quick start guide with installation, usage, and basic examples
- **CONTRIBUTING.md**: Development guidelines, testing requirements, and contribution workflow
- **Validation Checklists**: Comprehensive checklists for specification completeness and consistency

#### Design Philosophy
- **CLI-Agnostic**: Write once, run on any supported AI CLI agent
- **File-Based Communication**: Tasks communicate via filesystem, not inter-prompt variables
- **Structure-Based Parallelism**: YAML structure defines execution flow (no explicit parallel/sequential keywords)
- **Opaque CLI Output**: Meta-agent ignores stdout/stderr, only checks exit codes
- **Stateless Execution**: No persistent state files (except optional loop checkpoints)
- **No Artificial Limits**: No caps on parallel tasks, loop iterations, or prompt sizes
- **Fail-Fast by Default**: Workflows stop on first error unless explicitly configured otherwise

### Known Limitations

#### Template System
- **Limited Jinja2 Support**: Only `{{var}}` variable substitution is supported
  - No filters (e.g., `{{var|upper}}`, `{{var|default('fallback')}}`)
  - No conditionals (e.g., `{% if condition %}...{% endif %}`)
  - No Jinja2 loops (use YAML loop structures instead)
  - No string manipulation functions
- **Reserved Variable Immutability**: Reserved variables (`{{gitroot}}`, `{{datetime}}`, `{{user}}`, `{{directory}}`) cannot be overridden

#### Validation & Testing
- **No Task Validators**: Cannot validate task outputs (e.g., file-exists, file-not-empty, content-matches-pattern)
- **No Content Validation**: No built-in way to verify task output correctness beyond exit codes

#### Error Handling
- **No Task-Level Retry**: Retry mechanisms only available for loops, not individual tasks
- **Limited Error Context**: Error messages based on exit codes only (no stdout/stderr parsing)

#### Loop Types
- **Limited Loop Sources**: Only todo-list (markdown), CSV, and glob patterns supported
  - No JSON array iteration
  - No database query iteration
  - No API pagination loops
  - No git history iteration

#### State Management
- **Stateless Execution**: No workflow-level state management (only loop checkpoints)
- **No Cross-Session Resume**: Cannot resume arbitrary workflows without explicit checkpoints
- **Checkpoint Scope**: Checkpoints only track loop progress, not entire workflow state

#### Logging
- **Fixed Log Format**: Cannot customize log output format or destination
- **Stderr Only**: All logs go to stderr (no file output option)
- **No Structured Logs**: No JSON or other machine-readable log formats

#### Performance
- **No Concurrency Limits**: No built-in way to limit number of parallel tasks (relies on OS process limits)
- **No Rate Limiting**: No throttling for API-based CLI agents

### Roadmap

See `spec/planning.txt` for detailed future enhancements:

#### Planned for 0.2.0
- Full Jinja2 template support (filters, conditionals, string manipulation)
- Task validators (file-exists, file-not-empty, content validation)
- Task-level retry mechanisms (max-attempts, on-validation-failure)
- Configurable logging (log levels, file output, structured logs)

#### Planned for 0.3.0
- Additional loop types (JSON arrays, database queries, API pagination, git history)
- Workflow state management (cross-session resumability)
- Concurrency limits and rate limiting
- Performance optimizations

#### Under Consideration
- Web UI for workflow visualization and monitoring
- Workflow templates and library
- Plugin system for custom validators and loop types
- Integration with CI/CD pipelines

---

[0.1.0]: https://github.com/yourusername/agent-yaml/releases/tag/v0.1.0
