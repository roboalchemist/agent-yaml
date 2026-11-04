# CLI Adapter Specification

## Overview

This document defines the adapter layer that translates generic meta-agent YAML configurations into tool-specific CLI invocations. The adapter enables a single YAML workflow to run on multiple AI coding CLI tools (Claude, Gemini, Qwen, Codex).

## Design Principles

1. **Generic First**: YAML config uses generic, tool-agnostic terminology
2. **Graceful Degradation**: Unsupported features are skipped with warnings
3. **Capability Detection**: Adapter detects which features each tool supports
4. **Explicit Mappings**: Clear, documented mappings for all configuration options
5. **Validation**: Pre-flight checks for tool-specific constraints

---

## Generic YAML Configuration Schema

```yaml
directory: <string>              # Working directory
cli-agent: <string>               # Which CLI to use: claude, gemini, qwen, codex
cli-agent-config:                      # Generic CLI configuration
  skip-confirmations: <boolean>  # Auto-approve actions
  additional-dirs: <list>        # Extra directories in context
  timeout: <number>              # Global timeout in seconds
  permissions: <list>            # Permission/approval settings
  model: <string>                # Model to use
  debug: <boolean>               # Enable debug mode
  sandbox: <string>              # Sandbox mode
  session-id: <string>           # Session identifier
  output-format: <string>        # Output format
  mcp-servers: <list>            # MCP server configurations
  extensions: <list>             # Extensions to enable

  # Advanced options
  checkpointing: <boolean>       # Enable checkpointing
  telemetry: <boolean>           # Enable telemetry
  web-search: <boolean>          # Enable web search
  screen-reader: <boolean>       # Accessibility mode

  # Raw argument passthrough
  raw-args: <list>               # Raw CLI arguments (no translation)

  # Tool-specific passthrough
  custom: <object>               # Tool-specific options
```

---

## Configuration Mapping Tables

### 1. Skip Confirmations / Auto-Approval

**Generic Config:**
```yaml
cli-agent-config:
  skip-confirmations: true
```

**Tool-Specific Mappings:**

| Tool | CLI Arguments | Notes |
|------|---------------|-------|
| **Claude** | `--dangerously-skip-permissions` | Full bypass, use with caution |
| **Gemini** | `--yolo` or `--approval-mode yolo` | Auto-approve all actions |
| **Qwen** | `--yolo` or `--approval-mode yolo` | Auto-approve all actions |
| **Codex** | `--full-auto` | Balanced auto-approval with sandbox |

**Advanced Approval Modes:**

For more granular control, use `permissions` array:

```yaml
cli-agent-config:
  permissions:
    - level: auto-edit  # Auto-approve edit operations only
```

| Permission Level | Claude | Gemini | Qwen | Codex |
|-----------------|--------|--------|------|-------|
| `plan-only` | `--permission-mode plan` | ❌ Not supported | `--approval-mode plan` | ❌ Not supported |
| `auto-edit` | `--permission-mode acceptEdits` | `--approval-mode auto_edit` | `--approval-mode auto_edit` | ❌ Not supported |
| `on-failure` | ❌ Not supported | ❌ Not supported | ❌ Not supported | `-a on-failure` |
| `trusted-only` | ❌ Not supported | ❌ Not supported | ❌ Not supported | `-a untrusted` |
| `on-request` | ❌ Not supported | ❌ Not supported | ❌ Not supported | `-a on-request` |
| `never` | `--dangerously-skip-permissions` | `--yolo` | `--yolo` | `-a never --dangerously-bypass-approvals-and-sandbox` |

---

### 2. Additional Directories

**Generic Config:**
```yaml
cli-agent-config:
  additional-dirs:
    - "/tmp"
    - "/private/var/tmp"
```

**Tool-Specific Mappings:**

| Tool | CLI Arguments | Format |
|------|---------------|--------|
| **Claude** | `--add-dir <dir>` | Repeat flag for each directory |
| **Gemini** | `--include-directories <dirs...>` | Space-separated list |
| **Qwen** | `--include-directories <dirs...>` | Space-separated list |
| **Codex** | `-C <dir>` | ⚠️ Only single working directory, first dir used |

**Translation Examples:**

```bash
# Claude
claude --add-dir="/tmp" --add-dir="/private/var/tmp"

# Gemini
gemini --include-directories /tmp /private/var/tmp

# Qwen
qwen --include-directories /tmp /private/var/tmp

# Codex (limitation: only first directory)
codex -C /tmp
# Warning: Additional directories beyond first are not supported by Codex
```

---

### 3. Model Selection

**Generic Config:**
```yaml
cli-agent-config:
  model: "sonnet-4.5"  # Generic model identifier
```

**Adapter Responsibilities:**
1. Map generic model names to tool-specific identifiers
2. Validate model availability for each tool
3. Provide fallback options

**Model Name Mapping:**

| Generic Name | Claude | Gemini | Qwen | Codex |
|-------------|--------|--------|------|-------|
| `sonnet-4.5` | `claude-sonnet-4-5-20250929` | ❌ | ❌ | ❌ |
| `opus-4` | `claude-opus-4` | ❌ | ❌ | ❌ |
| `gemini-2.5-pro` | ❌ | `gemini-2.5-pro` | ❌ | ❌ |
| `qwen3-coder` | ❌ | ❌ | `qwen3-coder-plus` | ❌ |
| `gpt-5` | ❌ | ❌ | ❌ | `gpt-5` |
| `gpt-5-codex` | ❌ | ❌ | ❌ | `gpt-5-codex` |

**Tool-Specific Arguments:**

```bash
# Claude
claude --model "claude-sonnet-4-5-20250929"

# Gemini
gemini --model "gemini-2.5-pro"

# Qwen
qwen --model "qwen3-coder-plus"

# Codex
codex --model "gpt-5-codex"
```

---

### 4. Debug Mode

**Generic Config:**
```yaml
cli-agent-config:
  debug: true
```

**Tool-Specific Mappings:**

| Tool | CLI Arguments | Additional Options |
|------|---------------|-------------------|
| **Claude** | `--debug` or `-d` | Filter categories: `--debug api,hooks` |
| **Gemini** | `--debug` or `-d` | Boolean only |
| **Qwen** | `--debug` or `-d` | Boolean only |
| **Codex** | Debug via config | Use `-c debug=true` |

**Translation:**

```bash
# Claude (with optional filtering)
claude --debug

# Gemini
gemini --debug

# Qwen
qwen --debug

# Codex
codex -c debug=true
```

---

### 5. Sandbox Configuration

**Generic Config:**
```yaml
cli-agent-config:
  sandbox: "workspace-write"  # Options: read-only, workspace-write, full-access
```

**Tool-Specific Mappings:**

| Sandbox Level | Claude | Gemini | Qwen | Codex |
|--------------|--------|--------|------|-------|
| `read-only` | ❌ Use permissions | `--sandbox` (image needed) | `--sandbox` | `--sandbox read-only` |
| `workspace-write` | ❌ Use permissions | `--sandbox` (image needed) | `--sandbox` | `--sandbox workspace-write` |
| `full-access` | `--dangerously-skip-permissions` | `--sandbox-image <uri>` | `--sandbox-image <uri>` | `--sandbox danger-full-access` |

**Notes:**
- Claude doesn't have explicit sandbox; use permission modes instead
- Gemini/Qwen require sandbox image URI configuration
- Codex has three explicit sandbox levels

---

### 6. Session Management

**Generic Config:**
```yaml
cli-agent-config:
  session-id: "my-workflow-session"
  continue-session: true
```

**Tool-Specific Mappings:**

| Feature | Claude | Gemini | Qwen | Codex |
|---------|--------|--------|------|-------|
| Resume Session | `--resume [id]` | ❌ | ❌ | `resume [--last]` |
| Continue Last | `--continue` or `-c` | ❌ | ❌ | `resume --last` |
| Specific Session ID | `--session-id <uuid>` | ❌ | ❌ | ❌ |
| Fork Session | `--fork-session` (with resume) | ❌ | ❌ | ❌ |

**Translation:**

```bash
# Claude - most advanced
claude --continue  # Continue last
claude --resume abc-123-def  # Resume specific
claude --session-id "550e8400-e29b-41d4-a716-446655440000"  # Use specific UUID

# Gemini - not supported
# Adapter should skip session management for Gemini

# Qwen - not supported
# Adapter should skip session management for Qwen

# Codex
codex resume  # Interactive picker
codex resume --last  # Resume most recent
```

---

### 7. Output Format

**Generic Config:**
```yaml
cli-agent-config:
  output-format: "json"  # Options: text, json, stream-json
```

**Tool-Specific Mappings:**

| Format | Claude | Gemini | Qwen | Codex |
|--------|--------|--------|------|-------|
| `text` | Default or `--output-format text` | Default or `-o text` | Default | Default |
| `json` | `--output-format json` | `-o json` | ❌ | ❌ |
| `stream-json` | `--output-format stream-json` | ❌ | ❌ | ❌ |

**Translation:**

```bash
# Claude
claude --output-format json
claude --output-format stream-json

# Gemini
gemini --output-format json

# Qwen - not supported
qwen  # Falls back to text, adapter logs warning

# Codex - not supported
codex  # Falls back to text, adapter logs warning
```

---

### 8. MCP Server Configuration

**Generic Config:**
```yaml
cli-agent-config:
  mcp-servers:
    - notion
    - linear
    - tavily
  mcp-config-file: "/path/to/mcp-config.json"
```

**Tool-Specific Mappings:**

| Feature | Claude | Gemini | Qwen | Codex |
|---------|--------|--------|------|-------|
| MCP Management | `mcp` subcommand | `mcp` subcommand | `mcp` subcommand | `mcp` subcommand (experimental) |
| Allowed Servers | `--allowed-mcp-server-names <list>` | `--allowed-mcp-server-names <list>` | `--allowed-mcp-server-names <list>` | Config file |
| Config File | `--mcp-config <files>` | ❌ | ❌ | ❌ |
| Strict Mode | `--strict-mcp-config` | ❌ | ❌ | ❌ |

**Translation:**

```bash
# Claude
claude --mcp-config /path/to/mcp-config.json --strict-mcp-config

# Gemini
gemini --allowed-mcp-server-names notion linear tavily

# Qwen
qwen --allowed-mcp-server-names notion linear tavily

# Codex
# MCP configuration via ~/.codex/config.toml
codex  # Adapter should warn that config file setup is needed
```

---

### 9. Extensions

**Generic Config:**
```yaml
cli-agent-config:
  extensions:
    - code-review
    - documentation
```

**Tool-Specific Mappings:**

| Feature | Claude | Gemini | Qwen | Codex |
|---------|--------|--------|------|-------|
| Extensions Support | ❌ | ✅ | ✅ | ❌ |
| List Extensions | N/A | `--list-extensions` or `-l` | `--list-extensions` or `-l` | N/A |
| Select Extensions | N/A | `--extensions <list>` or `-e` | `--extensions <list>` or `-e` | N/A |

**Translation:**

```bash
# Claude - not supported
claude  # Adapter skips, logs warning

# Gemini
gemini --extensions code-review documentation

# Qwen
qwen --extensions code-review documentation

# Codex - not supported
codex  # Adapter skips, logs warning
```

---

### 10. Telemetry

**Generic Config:**
```yaml
cli-agent-config:
  telemetry: true
  telemetry-endpoint: "https://metrics.example.com"
```

**Tool-Specific Mappings:**

| Feature | Claude | Gemini | Qwen | Codex |
|---------|--------|--------|------|-------|
| Enable Telemetry | ❌ | `--telemetry` | `--telemetry` | ❌ |
| Target | N/A | `--telemetry-target local\|gcp` | `--telemetry-target local\|gcp` | N/A |
| OTLP Endpoint | N/A | `--telemetry-otlp-endpoint <url>` | `--telemetry-otlp-endpoint <url>` | N/A |
| OTLP Protocol | N/A | `--telemetry-otlp-protocol grpc\|http` | `--telemetry-otlp-protocol grpc\|http` | N/A |
| Log Prompts | N/A | `--telemetry-log-prompts` | `--telemetry-log-prompts` | N/A |
| Output File | N/A | `--telemetry-outfile <file>` | `--telemetry-outfile <file>` | N/A |

---

### 11. Web Search

**Generic Config:**
```yaml
cli-agent-config:
  web-search: true
  search-api-key: "sk-..."  # For tools that need API keys
```

**Tool-Specific Mappings:**

| Feature | Claude | Gemini | Qwen | Codex |
|---------|--------|--------|------|-------|
| Web Search | ❌ | ✅ Built-in | ✅ Tavily | `--search` |
| API Key | N/A | N/A (uses Google) | `--tavily-api-key <key>` | N/A |

**Translation:**

```bash
# Claude - not supported
claude  # Adapter skips, logs warning

# Gemini - built-in, always available
gemini  # No flag needed, search tool available by default

# Qwen
qwen --tavily-api-key "sk-..."

# Codex
codex --search
```

---

### 12. Checkpointing

**Generic Config:**
```yaml
cli-agent-config:
  checkpointing: true
```

**Tool-Specific Mappings:**

| Tool | CLI Arguments | Support |
|------|---------------|---------|
| **Claude** | ❌ | Not supported |
| **Gemini** | `--checkpointing` or `-c` | ✅ |
| **Qwen** | `--checkpointing` or `-c` | ✅ |
| **Codex** | ❌ | Not supported |

---

### 13. Accessibility (Screen Reader)

**Generic Config:**
```yaml
cli-agent-config:
  screen-reader: true
```

**Tool-Specific Mappings:**

| Tool | CLI Arguments | Support |
|------|---------------|---------|
| **Claude** | ❌ | Not supported |
| **Gemini** | `--screen-reader` | ✅ |
| **Qwen** | `--screen-reader` | ✅ |
| **Codex** | ❌ | Not supported |

---

### 14. Custom/Tool-Specific Options

**Generic Config:**
```yaml
cli-agent-config:
  custom:
    claude:
      ide: true
      agents:
        reviewer:
          description: "Reviews code"
          prompt: "You are a code reviewer"
    codex:
      profile: "production"
      image: "/path/to/screenshot.png"
    gemini:
      experimental-acp: true
    qwen:
      openai-base-url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
      openai-api-key: "sk-..."
      vlm-switch-mode: "session"
```

**Claude-Specific:**
```bash
claude --ide --agents '{"reviewer":{"description":"Reviews code","prompt":"You are a code reviewer"}}'
```

**Codex-Specific:**
```bash
codex --profile production --image /path/to/screenshot.png
```

**Gemini-Specific:**
```bash
gemini --experimental-acp
```

**Qwen-Specific:**
```bash
qwen --openai-base-url "https://dashscope-intl.aliyuncs.com/compatible-mode/v1" \
     --openai-api-key "sk-..." \
     --vlm-switch-mode session
```

---

### 15. Raw Arguments Pass-Through

**Generic Config:**
```yaml
cli-agent-config:
  raw-args:
    - "--experimental-feature"
    - "--custom-setting=value"
    - "--flag"
```

**Purpose:**

The `raw-args` field provides an escape hatch for passing tool-specific arguments directly to the CLI without any adapter translation or validation. This is useful for:

1. **Experimental Features**: Newly released CLI features not yet supported by the adapter
2. **Tool-Specific Flags**: Unique options that only exist for one CLI tool
3. **Advanced Configurations**: Edge cases not covered by generic mappings
4. **Temporary Workarounds**: Quick solutions while waiting for adapter updates

**Behavior:**

- Raw arguments are **appended** after all adapter-translated arguments
- No validation or transformation is performed
- Arguments are passed exactly as specified (preserving quotes and format)
- Order is preserved as listed in the array
- Tool compatibility checking is the user's responsibility

**Translation for All Tools:**

```bash
# Claude
claude <adapter-translated-args> --experimental-feature --custom-setting=value --flag

# Gemini
gemini <adapter-translated-args> --experimental-feature --custom-setting=value --flag

# Qwen
qwen <adapter-translated-args> --experimental-feature --custom-setting=value --flag

# Codex
codex <adapter-translated-args> --experimental-feature --custom-setting=value --flag
```

**Example Use Cases:**

**1. Claude IDE Integration:**
```yaml
cli-agent: "claude"
cli-agent-config:
  raw-args:
    - "--ide"
```

**2. Gemini Experimental ACP:**
```yaml
cli-agent: "gemini"
cli-agent-config:
  raw-args:
    - "--experimental-acp"
```

**3. Codex Image Attachment:**
```yaml
cli-agent: "codex"
cli-agent-config:
  raw-args:
    - "--image"
    - "/path/to/diagram.png"
```

**4. Qwen OpenAI Logging:**
```yaml
cli-agent: "qwen"
cli-agent-config:
  raw-args:
    - "--openai-logging"
```

**Important Warnings:**

⚠️ **No Validation**: The adapter does not validate raw arguments. Invalid flags will cause CLI errors at runtime.

⚠️ **Tool-Specific**: Raw args meant for one tool may not work with others. Always check CLI compatibility.

⚠️ **Quote Handling**: Be careful with shell quoting. Complex arguments with spaces or special characters may need proper escaping:

```yaml
# Correct - JSON needs quotes preserved
raw-args:
  - "--agents"
  - '{"reviewer":{"description":"Code reviewer"}}'

# Incorrect - will be parsed incorrectly
raw-args:
  - '--agents {"reviewer":{"description":"Code reviewer"}}'
```

⚠️ **Conflicts**: Raw args may conflict with adapter-translated arguments. The CLI tool will use the last occurrence of conflicting flags.

**Recommendation:**

Use `raw-args` sparingly and prefer generic options when available. Raw args make your workflow less portable across different CLI tools.

---

## Adapter Implementation

### Capability Detection

The adapter must detect which features each tool supports:

```typescript
interface ToolCapabilities {
  name: string;
  features: {
    sandbox: boolean;
    sessionManagement: boolean;
    jsonOutput: boolean;
    streaming: boolean;
    extensions: boolean;
    telemetry: boolean;
    webSearch: boolean;
    checkpointing: boolean;
    multipleDirectories: boolean;
    imageInput: boolean;
    customAgents: boolean;
    profileSystem: boolean;
  };
}

const capabilities: Record<string, ToolCapabilities> = {
  claude: {
    name: "Claude CLI",
    features: {
      sandbox: false,
      sessionManagement: true,
      jsonOutput: true,
      streaming: true,
      extensions: false,
      telemetry: false,
      webSearch: false,
      checkpointing: false,
      multipleDirectories: true,
      imageInput: false,
      customAgents: true,
      profileSystem: false,
    }
  },
  gemini: {
    name: "Gemini CLI",
    features: {
      sandbox: true,
      sessionManagement: false,
      jsonOutput: true,
      streaming: false,
      extensions: true,
      telemetry: true,
      webSearch: true,
      checkpointing: true,
      multipleDirectories: true,
      imageInput: false,
      customAgents: false,
      profileSystem: false,
    }
  },
  qwen: {
    name: "Qwen Code CLI",
    features: {
      sandbox: true,
      sessionManagement: false,
      jsonOutput: false,
      streaming: false,
      extensions: true,
      telemetry: true,
      webSearch: true,
      checkpointing: true,
      multipleDirectories: true,
      imageInput: true,
      customAgents: false,
      profileSystem: false,
    }
  },
  codex: {
    name: "OpenAI Codex CLI",
    features: {
      sandbox: true,
      sessionManagement: true,
      jsonOutput: false,
      streaming: false,
      extensions: false,
      telemetry: false,
      webSearch: true,
      checkpointing: false,
      multipleDirectories: false,
      imageInput: true,
      customAgents: false,
      profileSystem: true,
    }
  }
};
```

### Translation Logic

```typescript
interface GenericConfig {
  directory: string;
  "cli-agent": "claude" | "gemini" | "qwen" | "codex";
  "cli-agent-config": {
    "skip-confirmations"?: boolean;
    "additional-dirs"?: string[];
    model?: string;
    debug?: boolean;
    "raw-args"?: string[];
    // ... other options
  };
}

function translateConfig(config: GenericConfig): string[] {
  const tool = config["cli-agent"];
  const cliConfig = config["cli-agent-config"];
  const args: string[] = [];

  // Handle each configuration option
  if (cliConfig["skip-confirmations"]) {
    switch (tool) {
      case "claude":
        args.push("--dangerously-skip-permissions");
        break;
      case "gemini":
      case "qwen":
        args.push("--yolo");
        break;
      case "codex":
        args.push("--full-auto");
        break;
    }
  }

  if (cliConfig["additional-dirs"]) {
    switch (tool) {
      case "claude":
        cliConfig["additional-dirs"].forEach(dir => {
          args.push(`--add-dir="${dir}"`);
        });
        break;
      case "gemini":
      case "qwen":
        args.push("--include-directories", ...cliConfig["additional-dirs"]);
        break;
      case "codex":
        // Only supports single directory via -C
        if (cliConfig["additional-dirs"].length > 0) {
          args.push("-C", cliConfig["additional-dirs"][0]);
          if (cliConfig["additional-dirs"].length > 1) {
            console.warn("Codex only supports one directory. Using first directory only.");
          }
        }
        break;
    }
  }

  // ... continue for other options

  // Append raw arguments last (no translation)
  if (cliConfig["raw-args"]) {
    args.push(...cliConfig["raw-args"]);
  }

  return args;
}
```

### Validation

```typescript
function validateConfig(config: GenericConfig): ValidationResult {
  const tool = config["cli-agent"];
  const caps = capabilities[tool];
  const warnings: string[] = [];
  const errors: string[] = [];

  // Check for unsupported features
  if (config["cli-agent-config"].extensions && !caps.features.extensions) {
    warnings.push(`${caps.name} does not support extensions. This option will be ignored.`);
  }

  if (config["cli-agent-config"]["output-format"] === "json" && !caps.features.jsonOutput) {
    warnings.push(`${caps.name} does not support JSON output. Falling back to text.`);
  }

  if (config["cli-agent-config"]["session-id"] && !caps.features.sessionManagement) {
    warnings.push(`${caps.name} does not support session management. This option will be ignored.`);
  }

  // Check for required features
  if (config.ensure?.mcps && config.ensure.mcps.length > 0) {
    // Verify MCP support exists
    // This would check actual MCP installation
  }

  return { valid: errors.length === 0, errors, warnings };
}
```

---

## Complete Translation Example

**Generic YAML:**

```yaml
directory: "~/my-project"
cli-agent: "claude"

cli-agent-config:
  skip-confirmations: true
  additional-dirs:
    - "/tmp"
    - "/private/var/tmp"
  timeout: 3600
  model: "sonnet-4.5"
  debug: true
  output-format: "json"
  session-id: "my-workflow-123"
  mcp-servers:
    - notion
    - linear
  raw-args:
    - "--verbose"
    - "--ide"

template-variables:
  project: "myapp"

ensure:
  mcps:
    - notion
    - linear

task:
  - research:
      prompt: "Research the codebase"
```

**Translated CLI Invocation:**

```bash
cd ~/my-project

claude \
  --dangerously-skip-permissions \
  --add-dir="/tmp" \
  --add-dir="/private/var/tmp" \
  --model="claude-sonnet-4-5-20250929" \
  --debug \
  --output-format="json" \
  --session-id="my-workflow-123" \
  --allowed-mcp-server-names notion linear \
  --verbose \
  --ide \
  --print \
  "Research the codebase"
```

**Same Config for Gemini:**

```yaml
cli-agent: "gemini"
# ... rest same
```

**Translated:**

```bash
cd ~/my-project

gemini \
  --yolo \
  --include-directories /tmp /private/var/tmp \
  --model="gemini-2.5-pro" \
  --debug \
  --output-format="json" \
  --allowed-mcp-server-names notion linear \
  -p "Research the codebase"

# Warnings logged:
# - Gemini does not support session management. session-id ignored.
# - Gemini does not support timeout configuration.
```

---

## Error Handling

### Unsupported Features

When a feature is not supported by the selected tool:

1. **Log Warning**: Inform user that feature is being skipped
2. **Continue Execution**: Don't fail the entire workflow
3. **Document Limitation**: Reference documentation for alternatives

### Missing Requirements

When required tools/MCPs are missing:

1. **Pre-flight Check**: Validate before starting workflow
2. **Clear Error Messages**: Explain what's missing and how to install
3. **Fail Fast**: Don't start execution if critical requirements are missing

### Invalid Configurations

When configuration is invalid:

1. **Validation Errors**: List all configuration errors
2. **Helpful Messages**: Explain how to fix each error
3. **Fail Before Execution**: Don't attempt to run invalid config

---

## Adapter CLI Interface

The adapter itself should be invocable:

```bash
# Validate configuration
meta-agent validate workflow.yaml

# Translate configuration (dry-run)
meta-agent translate workflow.yaml --tool=claude

# Execute workflow
meta-agent run workflow.yaml

# Execute with specific tool override
meta-agent run workflow.yaml --tool=gemini

# Check capabilities
meta-agent capabilities --tool=codex
```

---

## Future Enhancements

1. **Auto-detection**: Detect which CLI tools are installed
2. **Fallback Chain**: Try multiple tools if one fails
3. **Parallel Execution**: Run same workflow on multiple tools concurrently
4. **Result Comparison**: Compare outputs from different tools
5. **Smart Model Mapping**: Auto-select best model per tool
6. **Configuration Profiles**: Pre-defined configs for common scenarios
7. **Incremental Updates**: Update only changed configurations
8. **Dry-run Mode**: Preview what would be executed
9. **Interactive Selection**: Let user choose tool at runtime
10. **Cost Estimation**: Estimate API costs before execution
