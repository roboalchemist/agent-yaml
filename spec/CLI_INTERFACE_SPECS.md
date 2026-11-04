# AI Coding CLI Tools Interface Specifications

## Overview

This document provides detailed interface specifications for four major AI coding CLI tools based on their official `--help` output and documentation. These specifications inform the adapter layer design for the meta-agent YAML configuration system.

## Tools Analyzed

1. **Claude CLI** (claude) - v2.0.2 by Anthropic
2. **Gemini CLI** (gemini) - by Google
3. **Qwen Code CLI** (qwen) - by Alibaba/Qwen team
4. **OpenAI Codex CLI** (codex) - by OpenAI

---

## Common Patterns Across All Tools

### Shared Capabilities

All four CLI tools share these common capabilities:

1. **Interactive Mode** (default behavior)
   - Launch without arguments for REPL-style interaction
   - Continue conversation across multiple turns

2. **Non-Interactive Mode**
   - Single-shot prompt execution with output
   - Suitable for scripting and automation

3. **Model Selection**
   - Ability to specify which AI model to use
   - Format: `--model <model-name>`

4. **Debug Mode**
   - Enable verbose logging and diagnostics
   - Format: `--debug` or `-d`

5. **MCP (Model Context Protocol) Support**
   - Manage and configure MCP servers
   - Subcommand: `mcp` for all tools

6. **Sandbox Execution**
   - Controlled environment for running code
   - Safety mechanisms for file system access

7. **Approval/Confirmation Modes**
   - Control when user approval is required
   - Ranges from full auto to manual approval for each action

---

## 1. Claude CLI (claude)

### Installation
```bash
npm install -g claude-code
```

### Version
2.0.2 (Claude Code)

### Basic Usage

```bash
# Interactive mode (default)
claude

# Non-interactive with prompt
claude -p "your prompt here"

# Continue previous conversation
claude -c

# Resume specific session
claude -r [sessionId]
```

### Key Options

#### Input/Output Control
- `-p, --print` - Print response and exit (non-interactive)
- `--output-format <format>` - Output format: "text" (default), "json", "stream-json"
- `--input-format <format>` - Input format: "text" or "stream-json"
- `--include-partial-messages` - Include partial chunks (streaming mode)
- `--replay-user-messages` - Re-emit user messages for acknowledgment

#### Model & Session
- `--model <model>` - Specify model (e.g., 'sonnet', 'opus', or full name)
- `--fallback-model <model>` - Automatic fallback when primary model is overloaded
- `-c, --continue` - Continue most recent conversation
- `-r, --resume [sessionId]` - Resume a conversation
- `--fork-session` - Create new session ID when resuming
- `--session-id <uuid>` - Use specific session ID (must be valid UUID)

#### Permissions & Security
- `--dangerously-skip-permissions` - Bypass all permission checks (dangerous!)
- `--permission-mode <mode>` - Permission mode: "acceptEdits", "bypassPermissions", "default", "plan"
- `--allowedTools <tools...>` - Comma/space-separated list of allowed tools
- `--disallowedTools <tools...>` - Comma/space-separated list of denied tools

#### Configuration & Extensions
- `--add-dir <directories...>` - Additional directories for tool access
- `--settings <file-or-json>` - Path to settings JSON or JSON string
- `--setting-sources <sources>` - Comma-separated list: user, project, local
- `--mcp-config <configs...>` - Load MCP servers from JSON files/strings
- `--strict-mcp-config` - Only use MCP servers from --mcp-config
- `--agents <json>` - JSON object defining custom agents

#### Advanced
- `-d, --debug [filter]` - Debug mode with optional category filtering
- `--verbose` - Override verbose mode from config
- `--ide` - Auto-connect to IDE on startup
- `--append-system-prompt <prompt>` - Append to system prompt

#### Subcommands
- `mcp` - Configure and manage MCP servers
- `migrate-installer` - Migrate from global npm to local installation
- `setup-token` - Set up long-lived auth token
- `doctor` - Check health of auto-updater
- `update` - Check for and install updates
- `install [target]` - Install native build (stable/latest/version)

### Claude CLI Unique Features

1. **Session Management**
   - Sophisticated session resume with fork capability
   - UUID-based session IDs for precise control

2. **IDE Integration**
   - Native IDE connection capability
   - `--ide` flag for automatic IDE detection

3. **Custom Agents**
   - Define custom agents via JSON
   - Example: `--agents '{"reviewer": {"description": "Reviews code", "prompt": "You are a code reviewer"}}'`

4. **Granular Tool Control**
   - Allowed/disallowed tools with pattern matching
   - Example: `--allowed-tools "Bash(git:*) Edit"`

5. **Streaming Support**
   - Full streaming input/output with `stream-json` format
   - Partial message support for real-time feedback

6. **Multiple Setting Sources**
   - User, project, and local settings hierarchy
   - Selective loading via `--setting-sources`

---

## 2. Gemini CLI (gemini)

### Installation
```bash
npm install -g @google/gemini-cli
```

### Basic Usage

```bash
# Interactive mode (default)
gemini

# With positional prompt
gemini [promptWords...]

# Non-interactive prompt
gemini -p "your prompt here"

# Interactive prompt that continues
gemini -i "initial prompt"
```

### Key Options

#### Model & Execution
- `-m, --model <model>` - Specify model
- `-p, --prompt <prompt>` - Prompt (appended to stdin) [deprecated - use positional]
- `-i, --prompt-interactive <prompt>` - Execute prompt and continue interactively
- `-y, --yolo` - Auto-accept all actions (YOLO mode)
- `--approval-mode <mode>` - Set approval mode: "default", "auto_edit", "yolo"

#### Sandbox & Context
- `-s, --sandbox` - Run in sandbox
- `--sandbox-image <uri>` - Sandbox image URI
- `-a, --all-files` - Include ALL files in context [deprecated]
- `--include-directories <dirs...>` - Additional workspace directories

#### Extensions & MCP
- `-e, --extensions <list>` - Extensions to use (all if not provided)
- `-l, --list-extensions` - List all available extensions and exit
- `--allowed-mcp-server-names <names...>` - Allowed MCP server names
- `--allowed-tools <tools...>` - Tools allowed without confirmation

#### Advanced Features
- `-d, --debug` - Debug mode
- `--show-memory-usage` - Show memory usage in status bar
- `-c, --checkpointing` - Enable checkpointing of file edits
- `--experimental-acp` - Start agent in ACP mode
- `--screen-reader` - Enable screen reader mode (accessibility)
- `-o, --output-format <format>` - Output format: "text" or "json"

#### Telemetry
- `--telemetry` - Enable telemetry
- `--telemetry-target <target>` - Set target: "local" or "gcp"
- `--telemetry-otlp-endpoint <url>` - OTLP endpoint
- `--telemetry-otlp-protocol <protocol>` - OTLP protocol: "grpc" or "http"
- `--telemetry-log-prompts` - Enable logging of user prompts
- `--telemetry-outfile <file>` - Redirect telemetry to file

#### Proxy
- `--proxy <uri>` - Proxy for gemini client

#### Subcommands
- `gemini mcp` - Manage MCP servers
- `gemini extensions <command>` - Manage extensions

### Gemini CLI Unique Features

1. **Extensions System**
   - Extensible architecture with plugin support
   - `--list-extensions` to discover available extensions
   - Selective extension loading

2. **YOLO Mode**
   - Named after YouTube reference
   - Full automation with `--yolo` flag

3. **Comprehensive Telemetry**
   - Multiple telemetry targets (local/gcp)
   - OTLP protocol support
   - Granular telemetry control

4. **ACP Mode**
   - Experimental Agent Communication Protocol mode
   - `--experimental-acp` flag

5. **Checkpointing**
   - File edit checkpointing system
   - Allows rollback of changes

---

## 3. Qwen Code CLI (qwen)

### Installation
```bash
npm install -g @qwen-code/qwen-code
```

### Basic Usage

```bash
# Interactive mode (default)
qwen

# Non-interactive prompt
qwen -p "your prompt here"

# Interactive prompt that continues
qwen -i "initial prompt"
```

### Key Options

#### Model & Execution
- `-m, --model <model>` - Specify model
- `-p, --prompt <prompt>` - Prompt (appended to stdin)
- `-i, --prompt-interactive <prompt>` - Execute prompt and continue interactively
- `-y, --yolo` - Auto-accept all actions (YOLO mode)
- `--approval-mode <mode>` - Approval mode: "plan", "default", "auto-edit", "yolo"

#### Sandbox & Context
- `-s, --sandbox` - Run in sandbox
- `--sandbox-image <uri>` - Sandbox image URI
- `-a, --all-files` - Include ALL files in context
- `--include-directories <dirs...>` - Additional workspace directories

#### Extensions & MCP
- `-e, --extensions <list>` - Extensions to use
- `-l, --list-extensions` - List all available extensions and exit
- `--allowed-mcp-server-names <names...>` - Allowed MCP server names
- `--allowed-tools <tools...>` - Tools allowed without confirmation

#### OpenAI API Configuration
- `--openai-api-key <key>` - OpenAI API key for authentication
- `--openai-base-url <url>` - OpenAI base URL (custom endpoints)
- `--openai-logging` - Enable logging of OpenAI API calls

#### Search & VLM
- `--tavily-api-key <key>` - Tavily API key for web search
- `--vlm-switch-mode <mode>` - Behavior when images detected: "once", "session", "persist"

#### Advanced
- `-d, --debug` - Debug mode
- `--show-memory-usage` - Show memory usage in status bar
- `-c, --checkpointing` - Enable checkpointing of file edits
- `--experimental-acp` - Start agent in ACP mode
- `--screen-reader` - Enable screen reader mode
- `--proxy <uri>` - Proxy for qwen client

#### Telemetry
- `--telemetry` - Enable telemetry
- `--telemetry-target <target>` - Target: "local" or "gcp"
- `--telemetry-otlp-endpoint <url>` - OTLP endpoint
- `--telemetry-otlp-protocol <protocol>` - Protocol: "grpc" or "http"
- `--telemetry-log-prompts` - Log user prompts for telemetry
- `--telemetry-outfile <file>` - Redirect telemetry output

#### Subcommands
- `qwen mcp` - Manage MCP servers

### Qwen CLI Unique Features

1. **Plan-Only Approval Mode**
   - Unique "plan" mode in `--approval-mode`
   - Agent creates plan without execution

2. **OpenAI API Compatibility**
   - Direct OpenAI API integration
   - Custom base URL support for OpenAI-compatible endpoints
   - API call logging for debugging

3. **Vision Language Model (VLM) Support**
   - `--vlm-switch-mode` for handling images
   - Three modes: once, session, persist
   - Intelligent model switching based on input type

4. **Tavily Search Integration**
   - Built-in web search capability
   - Dedicated API key configuration

5. **Based on Gemini CLI**
   - Fork/adaptation of Gemini CLI
   - Optimized for Qwen3-Coder models
   - Maintains similar architecture

---

## 4. OpenAI Codex CLI (codex)

### Installation
```bash
npm install -g @openai/codex
```

### Basic Usage

```bash
# Interactive mode (default)
codex

# With initial prompt
codex "your prompt here"

# Non-interactive execution
codex exec "your prompt"

# Resume previous session
codex resume
codex resume --last
```

### Key Options

#### Configuration
- `-c, --config <key=value>` - Override config value from `~/.codex/config.toml`
  - Use dotted path for nested values: `foo.bar.baz`
  - Value parsed as JSON, falls back to literal string
  - Examples:
    - `-c model="o3"`
    - `-c 'sandbox_permissions=["disk-full-read-access"]'`
    - `-c shell_environment_policy.inherit=all`

#### Model & Profile
- `-m, --model <MODEL>` - Specify model to use
- `--oss` - Use local open source model (requires Ollama)
- `-p, --profile <CONFIG_PROFILE>` - Config profile from config.toml

#### Input
- `[PROMPT]` - Optional user prompt to start session
- `-i, --image <FILE>...` - Attach image(s) to initial prompt

#### Sandbox & Permissions
- `-s, --sandbox <SANDBOX_MODE>` - Sandbox policy for shell commands
  - Values: "read-only", "workspace-write", "danger-full-access"
- `-a, --ask-for-approval <APPROVAL_POLICY>` - When to require approval
  - `untrusted` - Only run trusted commands without approval
  - `on-failure` - Ask only if command fails
  - `on-request` - Model decides when to ask
  - `never` - Never ask for approval
- `--full-auto` - Convenience alias for low-friction execution
  - Equivalent to: `-a on-failure --sandbox workspace-write`
- `--dangerously-bypass-approvals-and-sandbox` - Skip all confirmations (DANGEROUS)

#### Workspace
- `-C, --cd <DIR>` - Use specified directory as working root

#### Search
- `--search` - Enable web search (off by default)

#### Subcommands
- `exec` (alias: `e`) - Run non-interactively
- `login` - Manage login
- `logout` - Remove stored credentials
- `mcp` - [experimental] Run as MCP server and manage MCP servers
- `proto` (alias: `p`) - Run Protocol stream via stdin/stdout
- `completion` - Generate shell completion scripts
- `debug` - Internal debugging commands
- `apply` (alias: `a`) - Apply latest diff as `git apply`
- `resume` - Resume previous session (picker or --last)
- `help` - Print help

### Codex CLI Unique Features

1. **TOML Configuration**
   - Uses `~/.codex/config.toml` for settings
   - Dotted path override syntax
   - JSON-parsed values with literal fallback

2. **Profile System**
   - Named configuration profiles
   - Switch contexts easily with `-p`

3. **Multi-Modal Input**
   - Native image attachment support
   - Multiple images via repeated `-i` flag

4. **Git Integration**
   - `apply` subcommand for applying diffs
   - Native git workflow support

5. **Approval Policy System**
   - Four distinct approval policies
   - Granular control over automation level
   - "Trusted commands" concept

6. **OSS/Ollama Support**
   - `--oss` flag for local models
   - Verifies local Ollama server
   - Supports open source model providers

7. **Protocol Mode**
   - `proto` subcommand for stdin/stdout protocol
   - Enables integration with other tools

8. **Full-Auto Mode**
   - Convenience flag combining multiple settings
   - Balanced automation vs safety

9. **Built in Rust**
   - High performance
   - Fast startup times

---

## Feature Comparison Matrix

| Feature | Claude CLI | Gemini CLI | Qwen CLI | Codex CLI |
|---------|-----------|-----------|----------|-----------|
| **Interactive Mode** | ✅ | ✅ | ✅ | ✅ |
| **Non-Interactive** | ✅ (-p) | ✅ (-p) | ✅ (-p) | ✅ (exec) |
| **Model Selection** | ✅ | ✅ | ✅ | ✅ |
| **MCP Support** | ✅ | ✅ | ✅ | ✅ (experimental) |
| **Sandbox** | ❌ | ✅ | ✅ | ✅ |
| **YOLO Mode** | ❌ | ✅ | ✅ | ✅ (--full-auto) |
| **Session Resume** | ✅ (advanced) | ❌ | ❌ | ✅ |
| **Extensions** | ❌ | ✅ | ✅ | ❌ |
| **Telemetry** | ❌ | ✅ | ✅ | ❌ |
| **JSON Output** | ✅ | ✅ | ❌ | ❌ |
| **Streaming** | ✅ (full) | ❌ | ❌ | ❌ |
| **Image Input** | ❌ | ❌ | ✅ (VLM) | ✅ |
| **Config File** | JSON/settings | settings.json | settings.json | TOML |
| **Profiles** | ❌ | ❌ | ❌ | ✅ |
| **Web Search** | ❌ | ❌ | ✅ (Tavily) | ✅ (--search) |
| **IDE Integration** | ✅ | ❌ | ❌ | ❌ |
| **Custom Agents** | ✅ | ❌ | ❌ | ❌ |
| **Checkpointing** | ❌ | ✅ | ✅ | ❌ |
| **Git Integration** | ❌ | ❌ | ❌ | ✅ (apply) |
| **OSS Models** | ❌ | ❌ | ❌ | ✅ (Ollama) |

---

## Approval/Automation Modes Comparison

### Claude CLI
- `--permission-mode`:
  - `default` - Standard prompting
  - `acceptEdits` - Auto-approve edits
  - `bypassPermissions` - Skip all permissions
  - `plan` - Plan mode only
- `--dangerously-skip-permissions` - Bypass all (dangerous)

### Gemini CLI
- `--approval-mode`:
  - `default` - Prompt for approval
  - `auto_edit` - Auto-approve edit tools
  - `yolo` - Auto-approve all tools
- `--yolo` flag (equivalent to `--approval-mode yolo`)

### Qwen CLI
- `--approval-mode`:
  - `plan` - Plan only (unique to Qwen)
  - `default` - Prompt for approval
  - `auto_edit` - Auto-approve edit tools
  - `yolo` - Auto-approve all tools
- `--yolo` flag

### Codex CLI
- `-a, --ask-for-approval`:
  - `untrusted` - Only trusted commands auto-run
  - `on-failure` - Ask only if command fails
  - `on-request` - Model decides
  - `never` - Never ask
- `--full-auto` - Convenience for `-a on-failure --sandbox workspace-write`
- `--dangerously-bypass-approvals-and-sandbox` - Ultimate bypass

---

## Directory/Context Management

### Claude CLI
```bash
claude --add-dir /path/to/dir1 --add-dir /path/to/dir2
```

### Gemini CLI
```bash
gemini --include-directories /path/to/dir1 /path/to/dir2
```

### Qwen CLI
```bash
qwen --include-directories /path/to/dir1 /path/to/dir2
```

### Codex CLI
```bash
codex -C /working/directory
# Note: Changes working root, doesn't add additional context
```

---

## Configuration Management

### Claude CLI
- Settings via JSON file or inline JSON string
- `--settings <file-or-json>`
- `--setting-sources user,project,local`
- Multiple configuration layers

### Gemini CLI
- Uses `settings.json`
- Many flags marked deprecated in favor of settings file
- Telemetry configuration in settings

### Qwen CLI
- Similar to Gemini (based on same codebase)
- Settings.json based
- Additional OpenAI API configuration

### Codex CLI
- TOML configuration: `~/.codex/config.toml`
- Override with `-c key=value`
- Profile system with `-p <profile-name>`
- Dotted path for nested values

---

## Authentication Methods

### Claude CLI
- `setup-token` subcommand
- Long-lived auth tokens
- Requires Claude subscription

### Gemini CLI
- Google account login
- Free tier: 60 requests/min, 1000 requests/day
- Gemini Code Assist license (free during preview)

### Qwen CLI
- API key configuration
- `--openai-api-key` for Alibaba Cloud
- Dashboard: https://modelstudio.console.alibabacloud.com/

### Codex CLI
- `login` subcommand
- ChatGPT account or API key
- Plus, Pro, Team, Edu, or Enterprise plans recommended

---

## Output Formats

### Claude CLI
```bash
--output-format text|json|stream-json
--input-format text|stream-json
```
- Full streaming support
- Partial message chunks
- Replay user messages

### Gemini CLI
```bash
--output-format text|json
```
- Basic JSON output
- No streaming

### Qwen CLI
- No explicit output format options
- Text output only

### Codex CLI
- No explicit output format options
- Text output by default
- Protocol mode available via `proto` subcommand

---

## Recommendations for Adapter Layer

Based on this analysis, the adapter layer should:

1. **Normalize Approval Modes**
   - Map generic approval levels to tool-specific flags
   - Support: `none`, `edits-only`, `on-failure`, `trusted-only`, `plan-only`, `full-auto`

2. **Standardize Directory Management**
   - Translate to `--add-dir` (Claude), `--include-directories` (Gemini/Qwen), or `-C` (Codex)
   - Handle multiple directories appropriately

3. **Unified Model Selection**
   - All tools support `--model` or `-m`
   - Map model aliases to tool-specific names

4. **Configuration Approaches**
   - Claude: JSON-based settings
   - Gemini/Qwen: settings.json with CLI overrides
   - Codex: TOML with dotted path overrides
   - Adapter should support all formats

5. **Session Management**
   - Claude and Codex support session resume
   - Gemini and Qwen do not (yet)
   - Adapter should gracefully degrade

6. **MCP Configuration**
   - All tools support MCP
   - Different configuration methods
   - Standardize MCP server specification

7. **Output Format Handling**
   - Only Claude and Gemini support JSON output
   - Adapter should handle text-only tools

8. **Debug Mode**
   - All support `--debug` or `-d`
   - Standardize debug verbosity levels

9. **Sandbox Configuration**
   - Gemini, Qwen, and Codex support sandboxing
   - Claude uses permission modes instead
   - Map to appropriate security levels

10. **Feature Detection**
    - Adapter should detect which features are available
    - Gracefully handle unsupported features
    - Provide warnings when features aren't available

---

## Next Steps

1. Design adapter interface based on these specifications
2. Create mapping tables for each configuration option
3. Implement capability detection logic
4. Build translation layer for CLI invocations
5. Add validation for tool-specific constraints
