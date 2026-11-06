"""
Workflow schema validator.

Validates parsed YAML workflows against the schema specification.
Checks required fields, correct types, and structural constraints.

Validation includes:
- Required field presence (workflow, task)
- Type validation (strings, lists, objects, booleans, integers)
- Loop configuration validation (type-specific required fields)
- Template variable reference validation

Reference: spec/YAML_SPEC.md for schema requirements.
"""

from agent_yaml.includes import CircularIncludeError, detect_circular_includes


class ValidationError(Exception):
    """Raised when workflow validation fails."""

    pass


class SchemaValidator:
    """
    Validates workflow schema against specification.

    Checks:
    - Required fields (directory, task)
    - Optional field types (cli-agent, cli-agent-config, on-error, etc.)
    - Field value constraints (cli-agent must be a supported adapter)
    """

    VALID_CLI_AGENTS = ["opencode", "claude", "codex", "pi", "vtcode", "antigravity"]
    VALID_ON_ERROR_VALUES = ["fail", "continue", "skip"]

    # Adapter options. Anything not listed here is rejected, so a typo or a
    # config key copied from another adapter fails at validate time instead of
    # producing a command the CLI rejects at run time.
    _agent = "claude"
    PI_THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]
    PI_OUTPUT_FORMATS = ["text", "json", "rpc"]
    PI_OPTION_SPEC = {
        "model": "string",
        "provider": "string",
        "thinking": "string",
        "title": "string",
        "session-id": "string",
        "output-format": "string",
        "tools": "string or list of strings",
        "exclude-tools": "string or list of strings",
        "skip-confirmations": "boolean",
        "no-tools": "boolean",
        "continue": "boolean",
        "session": "boolean",
        "debug": "boolean",
        "no-extensions": "boolean",
        "timeout": "positive number",
        "raw-args": "list of strings",
        "additional-dirs": "list (ignored by pi)",
        "mcp-servers": "list (ignored by pi)",
        "mcp-config-file": "string (ignored by pi)",
    }

    VTCODE_OPTION_SPEC = {
        "model": "string",
        "provider": "string",
        "session-id": "string",
        "output-format": "string",
        "security-level": "string",
        "max-tool-calls": "positive integer",
        "skip-confirmations": "boolean",
        "continue": "boolean",
        "debug": "boolean",
        "quiet": "boolean",
        "timeout": "positive number",
        "raw-args": "list of strings",
        "additional-dirs": "list (ignored by vtcode)",
        "mcp-servers": "list (ignored by vtcode)",
        "mcp-config-file": "string (ignored by vtcode)",
    }

    ANTIGRAVITY_OPTION_SPEC = {
        "model": "string",
        "effort": "string",
        "agent": "string",
        "session-id": "string",
        "output-format": "string",
        "skip-confirmations": "boolean",
        "continue": "boolean",
        "sandbox": "boolean",
        "timeout": "positive number",
        "raw-args": "list of strings",
        "additional-dirs": "list of directories",
        "mcp-servers": "list (ignored by agy)",
        "mcp-config-file": "string (ignored by agy)",
    }

    AGENT_OPTION_SPECS = {
        "pi": PI_OPTION_SPEC,
        "vtcode": VTCODE_OPTION_SPEC,
        "antigravity": ANTIGRAVITY_OPTION_SPEC,
    }
    AGENT_STRING_OPTIONS = {
        "pi": ["model", "provider", "thinking", "title", "session-id",
               "output-format", "mcp-config-file"],
        "vtcode": ["model", "provider", "session-id", "output-format",
                   "security-level", "mcp-config-file"],
        "antigravity": ["model", "effort", "agent", "session-id",
                        "output-format", "mcp-config-file"],
    }
    AGENT_BOOL_OPTIONS = {
        "pi": ["skip-confirmations", "no-tools", "continue", "session",
               "debug", "no-extensions"],
        "vtcode": ["skip-confirmations", "continue", "debug", "quiet"],
        "antigravity": ["skip-confirmations", "continue", "sandbox"],
    }
    AGENT_STRING_OR_LIST_OPTIONS = {
        "pi": ["tools", "exclude-tools"],
        "vtcode": [],
        "antigravity": [],
    }
    AGENT_ENUM_OPTIONS = {
        "pi": {"thinking": PI_THINKING_LEVELS, "output-format": PI_OUTPUT_FORMATS},
        "vtcode": {
            "output-format": ["text", "json"],
            "security-level": ["strict", "moderate", "permissive"],
        },
        "antigravity": {
            "output-format": ["text", "json", "stream-json"],
            "effort": ["low", "medium", "high", "xhigh", "max"],
        },
    }

    def _validate_agent_config(self, agent, config, where="cli-agent-config"):
        """Validate adapter options for the active agent: keys, types, enum values."""
        spec = self.AGENT_OPTION_SPECS[agent]

        def fail(message):
            raise ValidationError(
                "{}\n\nContext: {}\nAllowed options: {}".format(
                    message, where, ", ".join(sorted(spec))
                )
            )

        for key in config:
            if key not in spec:
                fail("Unknown {} option '{}'".format(agent, key))

        for key in self.AGENT_STRING_OPTIONS[agent]:
            if key in config and not isinstance(config[key], str):
                fail("{} option '{}' must be a string, got {}".format(
                    agent, key, type(config[key]).__name__))

        for key in self.AGENT_BOOL_OPTIONS[agent]:
            if key in config and not isinstance(config[key], bool):
                fail("{} option '{}' must be a boolean, got {}".format(
                    agent, key, type(config[key]).__name__))

        if "timeout" in config:
            value = config["timeout"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                fail("{} option 'timeout' must be a positive number, got {!r}".format(agent, value))

        if "max-tool-calls" in config:
            value = config["max-tool-calls"]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                fail("{} option 'max-tool-calls' must be a positive integer, got {!r}".format(
                    agent, value))

        for key in ("raw-args", "additional-dirs", "mcp-servers"):
            if key in config:
                value = config[key]
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    fail("{} option '{}' must be a list of strings, got {!r}".format(
                        agent, key, value))

        for key in self.AGENT_STRING_OR_LIST_OPTIONS[agent]:
            if key in config:
                value = config[key]
                if isinstance(value, str):
                    if not value.strip():
                        fail("{} option '{}' must not be empty".format(agent, key))
                elif isinstance(value, list):
                    if not all(isinstance(v, str) and v.strip() for v in value):
                        fail("{} option '{}' list entries must be non-empty strings".format(
                            agent, key))
                else:
                    fail("{} option '{}' must be a string or list of strings, got {}".format(
                        agent, key, type(value).__name__))

        for key, allowed in self.AGENT_ENUM_OPTIONS[agent].items():
            if key in config and config[key] not in allowed:
                fail("{} option '{}' must be one of {}, got '{}'".format(
                    agent, key, allowed, config[key]))

        if "session-id" in config and not config["session-id"].strip():
            fail("{} option 'session-id' must not be empty".format(agent))

    def _validate_pi_config(self, config, where="cli-agent-config"):
        """Backward-compatible wrapper for the pi option validator."""
        self._validate_agent_config("pi", config, where)

    def validate_schema(self, workflow_dict):
        """
        Validate a parsed workflow against the schema.

        Args:
            workflow_dict: Parsed workflow dictionary

        Returns:
            bool: True if valid

        Raises:
            ValidationError: If workflow fails schema validation with specific field name and expected type
        """
        if not isinstance(workflow_dict, dict):
            raise ValidationError("Workflow must be a dictionary")

        # Validate required field: directory
        if "directory" not in workflow_dict:
            raise ValidationError("Field 'directory' is required but missing")
        if not isinstance(workflow_dict["directory"], str):
            raise ValidationError(
                "Field 'directory' must be a string, got {}".format(
                    type(workflow_dict["directory"]).__name__
                )
            )

        # Validate required field: task
        if "task" not in workflow_dict:
            raise ValidationError("Field 'task' is required but missing")
        if not isinstance(workflow_dict["task"], list):
            raise ValidationError(
                "Field 'task' must be a list, got {}".format(type(workflow_dict["task"]).__name__)
            )

        # Validate task list is not empty
        if len(workflow_dict["task"]) == 0:
            raise ValidationError(
                "Workflow has no tasks\n\n"
                "Context: The 'task' field is an empty list\n"
                "Expected: At least one task definition\n"
                "Found: Empty task list\n"
                "Suggestion: Add at least one task to the workflow:\n"
                "  task:\n"
                "    - task-name:\n"
                '        prompt: "Your task prompt"'
            )

        # Validate optional field: cli-agent
        if "cli-agent" in workflow_dict:
            if not isinstance(workflow_dict["cli-agent"], str):
                raise ValidationError(
                    "Field 'cli-agent' must be a string, got {}".format(
                        type(workflow_dict["cli-agent"]).__name__
                    )
                )
            if workflow_dict["cli-agent"] not in self.VALID_CLI_AGENTS:
                raise ValidationError(
                    "Field 'cli-agent' must be one of {}, got '{}'".format(
                        self.VALID_CLI_AGENTS, workflow_dict["cli-agent"]
                    )
                )

        # Validate optional field: cli-agent-config
        if "cli-agent-config" in workflow_dict:
            if not isinstance(workflow_dict["cli-agent-config"], dict):
                raise ValidationError(
                    "Field 'cli-agent-config' must be a dict, got {}".format(
                        type(workflow_dict["cli-agent-config"]).__name__
                    )
                )

        # Adapter-specific option validation. pi options are enumerated, so an
        # option copied from another adapter fails here rather than at run time.
        self._agent = workflow_dict.get("cli-agent", "claude")
        if (
            self._agent in self.AGENT_OPTION_SPECS
            and isinstance(workflow_dict.get("cli-agent-config"), dict)
        ):
            self._validate_agent_config(self._agent, workflow_dict["cli-agent-config"])

        # Validate optional field: on-error
        if "on-error" in workflow_dict:
            if not isinstance(workflow_dict["on-error"], str):
                raise ValidationError(
                    "Field 'on-error' must be a string, got {}".format(
                        type(workflow_dict["on-error"]).__name__
                    )
                )
            if workflow_dict["on-error"] not in self.VALID_ON_ERROR_VALUES:
                raise ValidationError(
                    "Field 'on-error' must be one of {}, got '{}'".format(
                        self.VALID_ON_ERROR_VALUES, workflow_dict["on-error"]
                    )
                )

        # Validate optional field: template-variables
        if "template-variables" in workflow_dict:
            if not isinstance(workflow_dict["template-variables"], dict):
                raise ValidationError(
                    "Field 'template-variables' must be a dict, got {}".format(
                        type(workflow_dict["template-variables"]).__name__
                    )
                )

        # Validate optional field: ensure
        if "ensure" in workflow_dict:
            if not isinstance(workflow_dict["ensure"], dict):
                raise ValidationError(
                    "Field 'ensure' must be a dict, got {}".format(
                        type(workflow_dict["ensure"]).__name__
                    )
                )

            # Validate ensure.mcps if present
            if "mcps" in workflow_dict["ensure"]:
                if not isinstance(workflow_dict["ensure"]["mcps"], list):
                    raise ValidationError(
                        "Field 'ensure.mcps' must be a list, got {}".format(
                            type(workflow_dict["ensure"]["mcps"]).__name__
                        )
                    )

            # Validate ensure.tools if present
            if "tools" in workflow_dict["ensure"]:
                if not isinstance(workflow_dict["ensure"]["tools"], list):
                    raise ValidationError(
                        "Field 'ensure.tools' must be a list, got {}".format(
                            type(workflow_dict["ensure"]["tools"]).__name__
                        )
                    )

        # Validate optional field: environment (workflow-level env vars)
        if "environment" in workflow_dict:
            if not isinstance(workflow_dict["environment"], dict):
                raise ValidationError(
                    "Field 'environment' must be a dict, got {}".format(
                        type(workflow_dict["environment"]).__name__
                    )
                )
            # Validate all env var keys are strings
            for key, value in workflow_dict["environment"].items():
                if not isinstance(key, str):
                    raise ValidationError(
                        f"Environment variable key must be a string, got {type(key).__name__}"
                    )
                # Values can be any type (will be converted to string at execution time)
                # but if it's a string, that's ideal

        # Validate optional field: includes
        if "includes" in workflow_dict:
            if not isinstance(workflow_dict["includes"], dict):
                raise ValidationError(
                    "Field 'includes' must be a dict, got {}".format(
                        type(workflow_dict["includes"]).__name__
                    )
                )

            # Detect circular include dependencies
            try:
                detect_circular_includes(workflow_dict["includes"])
            except CircularIncludeError as e:
                raise ValidationError(str(e))

        # Validate task content (each task must have prompt or nested tasks)
        self._validate_task_list(workflow_dict["task"])

        return True

    def _validate_task_list(self, task_list, path="task"):
        """
        Recursively validate that each task has either a prompt or nested tasks.

        Args:
            task_list: List of task definitions
            path: Current path for error reporting (e.g., "task[0].subtask")

        Raises:
            ValidationError: If task has neither prompt nor nested tasks
        """
        for index, task_item in enumerate(task_list):
            if not isinstance(task_item, dict):
                raise ValidationError(
                    f"Task at {path}[{index}] must be a dict, got {type(task_item).__name__}"
                )

            # Each task item should be a dict with one key (task name) -> task definition
            for task_name, task_def in task_item.items():
                if not isinstance(task_def, dict):
                    raise ValidationError(
                        f"Task definition for '{task_name}' at {path}[{index}] must be a dict, "
                        f"got {type(task_def).__name__}"
                    )

                if (
                    self._agent in self.AGENT_OPTION_SPECS
                    and isinstance(task_def.get("cli-agent-config"), dict)
                ):
                    self._validate_agent_config(
                        self._agent,
                        task_def["cli-agent-config"],
                        "cli-agent-config for task '{}' at {}[{}]".format(task_name, path, index),
                    )

                # Check if task has prompt
                has_prompt = "prompt" in task_def and task_def["prompt"]

                # Check if task has nested tasks
                has_nested_tasks = (
                    "task" in task_def and task_def["task"] and len(task_def["task"]) > 0
                )

                # Check if task has loop (loop tasks don't need nested tasks)
                has_loop = "loop" in task_def

                # Check if task has direct child tasks (parallel grouping without 'task:' field)
                # This happens when task_def has keys that are themselves task definitions
                # Example: setup: { create-dirs: { prompt: ... }, create-files: { prompt: ... } }
                has_direct_children = False
                if not has_prompt and not has_nested_tasks and not has_loop:
                    # Check if any keys in task_def look like nested tasks
                    for key, value in task_def.items():
                        # Skip known meta fields
                        if key in ["prompt", "task", "loop", "include", "on-error", "directory",
                                   "cli-agent-config", "validate", "retry", "skip-if", "env", "when"]:
                            continue
                        # If value is a dict, it might be a nested task
                        if isinstance(value, dict):
                            has_direct_children = True
                            break
                        # If value is a list, it might be sequential nested tasks
                        if isinstance(value, list):
                            has_direct_children = True
                            break

                # Task must have prompt OR nested tasks OR loop OR direct children (parallel/sequential grouping)
                if (
                    not has_prompt
                    and not has_nested_tasks
                    and not has_loop
                    and not has_direct_children
                ):
                    raise ValidationError(
                        f"Task with neither prompt nor nested tasks\n\n"
                        f"Context: Task '{task_name}' at {path}[{index}]\n"
                        f"Expected: Task must have either 'prompt' field or nested 'task' field\n"
                        f"Found: Task definition with neither field\n"
                        f"Suggestion: Add a prompt to the task:\n"
                        f"  {task_name}:\n"
                        f'    prompt: "Your task prompt"\n'
                        f"Or add nested tasks:\n"
                        f"  {task_name}:\n"
                        f"    task:\n"
                        f"      - subtask:\n"
                        f'          prompt: "Subtask prompt"'
                    )

                # If task has nested tasks, recursively validate them
                if has_nested_tasks:
                    self._validate_task_list(
                        task_def["task"], path=f"{path}[{index}].{task_name}.task"
                    )

                # If task has direct children (parallel/sequential grouping), validate them
                if has_direct_children:
                    # Build a list of child tasks for validation
                    child_tasks = []
                    for key, value in task_def.items():
                        # Skip known meta fields
                        if key in ["prompt", "task", "loop", "include", "on-error", "directory",
                                   "cli-agent-config", "validate", "retry", "skip-if", "env", "when"]:
                            continue
                        # Add child as a task item (name: definition)
                        if isinstance(value, (dict, list)):
                            child_tasks.append({key: value})

                    # Recursively validate child tasks
                    if child_tasks:
                        self._validate_task_list(child_tasks, path=f"{path}[{index}].{task_name}")

                # If task has loop, validate loop configuration
                if has_loop:
                    self._validate_loop_config(task_def["loop"], f"{path}[{index}].{task_name}")

                # If task has validators, validate validator configuration
                if "validate" in task_def:
                    self._validate_validators_config(
                        task_def["validate"], f"{path}[{index}].{task_name}"
                    )

                # If task has retry config, validate retry configuration
                if "retry" in task_def:
                    self._validate_retry_config(
                        task_def["retry"], f"{path}[{index}].{task_name}"
                    )

                # If task has skip-if config, validate skip-if configuration
                if "skip-if" in task_def:
                    self._validate_skip_if_config(
                        task_def["skip-if"], f"{path}[{index}].{task_name}"
                    )

                # If task has when config, validate when configuration
                if "when" in task_def:
                    self._validate_when_config(
                        task_def["when"], f"{path}[{index}].{task_name}"
                    )

                # If task has directory override, validate it's a string
                if "directory" in task_def:
                    if not isinstance(task_def["directory"], str):
                        raise ValidationError(
                            f"Task '{task_name}' at {path}[{index}]: 'directory' must be a string, "
                            f"got {type(task_def['directory']).__name__}"
                        )

                # If task has env config, validate it's a dict
                if "env" in task_def:
                    if not isinstance(task_def["env"], dict):
                        raise ValidationError(
                            f"Task '{task_name}' at {path}[{index}]: 'env' must be a dict, "
                            f"got {type(task_def['env']).__name__}"
                        )
                    # Validate all env var keys are strings
                    for key, value in task_def["env"].items():
                        if not isinstance(key, str):
                            raise ValidationError(
                                f"Task '{task_name}' at {path}[{index}]: "
                                f"env variable key must be a string, got {type(key).__name__}"
                            )

    def _validate_loop_config(self, loop_config, path):
        """
        Validate loop configuration including parallel execution options.

        Args:
            loop_config: Loop configuration dict
            path: Current path for error reporting

        Raises:
            ValidationError: If loop configuration is invalid
        """
        if not isinstance(loop_config, dict):
            raise ValidationError(
                f"Loop configuration at {path} must be a dict, got {type(loop_config).__name__}"
            )

        # Validate loop type
        loop_type = loop_config.get("type")
        if not loop_type:
            raise ValidationError(f"Loop at {path} missing required field 'type'")

        valid_loop_types = ["todo-list", "csv", "glob", "json", "jsonl"]
        if loop_type not in valid_loop_types:
            raise ValidationError(
                f"Loop at {path} has invalid type '{loop_type}'. Must be one of: {valid_loop_types}"
            )

        # Validate workers if present
        if "workers" in loop_config:
            workers = loop_config["workers"]
            if not isinstance(workers, int):
                raise ValidationError(
                    f"Loop at {path}: 'workers' must be an integer, got {type(workers).__name__}"
                )
            if workers < 1:
                raise ValidationError(
                    f"Loop at {path}: 'workers' must be >= 1, got {workers}"
                )

        # Validate directory-pool if present
        if "directory-pool" in loop_config:
            directory_pool = loop_config["directory-pool"]
            if not isinstance(directory_pool, list):
                raise ValidationError(
                    f"Loop at {path}: 'directory-pool' must be a list, got {type(directory_pool).__name__}"
                )
            if not directory_pool:
                raise ValidationError(
                    f"Loop at {path}: 'directory-pool' cannot be empty"
                )
            for i, directory in enumerate(directory_pool):
                if not isinstance(directory, str):
                    raise ValidationError(
                        f"Loop at {path}: 'directory-pool[{i}]' must be a string, got {type(directory).__name__}"
                    )

        # Validate git-worktrees if present
        if "git-worktrees" in loop_config:
            git_config = loop_config["git-worktrees"]
            if not isinstance(git_config, dict):
                raise ValidationError(
                    f"Loop at {path}: 'git-worktrees' must be a dict, got {type(git_config).__name__}"
                )

            # Validate enabled flag
            if "enabled" in git_config:
                if not isinstance(git_config["enabled"], bool):
                    raise ValidationError(
                        f"Loop at {path}: 'git-worktrees.enabled' must be a boolean, got {type(git_config['enabled']).__name__}"
                    )

            # Validate base path if present
            if "base" in git_config:
                if not isinstance(git_config["base"], str):
                    raise ValidationError(
                        f"Loop at {path}: 'git-worktrees.base' must be a string, got {type(git_config['base']).__name__}"
                    )

            # Validate branch-field if present (required for CSV loops)
            if loop_type == "csv" and "branch-field" in git_config:
                if not isinstance(git_config["branch-field"], str):
                    raise ValidationError(
                        f"Loop at {path}: 'git-worktrees.branch-field' must be a string, got {type(git_config['branch-field']).__name__}"
                    )

            # Validate name-template if present
            if "name-template" in git_config:
                if not isinstance(git_config["name-template"], str):
                    raise ValidationError(
                        f"Loop at {path}: 'git-worktrees.name-template' must be a string, got {type(git_config['name-template']).__name__}"
                    )

            # Validate cleanup if present
            if "cleanup" in git_config:
                if not isinstance(git_config["cleanup"], bool):
                    raise ValidationError(
                        f"Loop at {path}: 'git-worktrees.cleanup' must be a boolean, got {type(git_config['cleanup']).__name__}"
                    )

        # Validate that directory-pool and git-worktrees are not both specified
        if "directory-pool" in loop_config and "git-worktrees" in loop_config:
            raise ValidationError(
                f"Loop at {path}: Cannot use both 'directory-pool' and 'git-worktrees'"
            )

        # Type-specific validation for JSON/JSONL loops
        if loop_type in ["json", "jsonl"]:
            self._validate_json_loop_config(loop_config, path)

    def _validate_json_loop_config(self, loop_config, path):
        """
        Validate JSON/JSONL loop configuration.

        Args:
            loop_config: Loop configuration dict
            path: Current path for error reporting

        Raises:
            ValidationError: If JSON loop configuration is invalid
        """
        loop_type = loop_config.get("type")

        # source is required
        if "source" not in loop_config:
            raise ValidationError(f"Loop at {path}: 'source' field is required")

        # Validate source is a string
        if not isinstance(loop_config["source"], str):
            raise ValidationError(
                f"Loop at {path}: 'source' must be a string, got {type(loop_config['source']).__name__}"
            )

        # path only valid for 'json', not 'jsonl'
        if loop_type == "jsonl" and "path" in loop_config:
            raise ValidationError(
                f"Loop at {path}: 'path' field not supported for jsonl type"
            )

        # Validate path if present (for json type)
        if "path" in loop_config:
            if not isinstance(loop_config["path"], str):
                raise ValidationError(
                    f"Loop at {path}: 'path' must be a string, got {type(loop_config['path']).__name__}"
                )

        # Validate filter structure
        filter_config = loop_config.get("filter", {})
        if filter_config:
            if not isinstance(filter_config, dict):
                raise ValidationError(
                    f"Loop at {path}: 'filter' must be a dict, got {type(filter_config).__name__}"
                )

            has_simple = "key" in filter_config and "value" in filter_config
            has_complex = "conditions" in filter_config

            if has_simple and has_complex:
                raise ValidationError(
                    f"Loop at {path}: Cannot mix simple filter (key/value) with multiple conditions"
                )

            # Validate simple filter
            if has_simple:
                if not isinstance(filter_config["key"], str):
                    raise ValidationError(
                        f"Loop at {path}: filter.key must be a string, got {type(filter_config['key']).__name__}"
                    )
                # value can be any type

            # Validate complex filter
            if has_complex:
                conditions = filter_config.get("conditions")
                if not isinstance(conditions, list) or not conditions:
                    raise ValidationError(
                        f"Loop at {path}: 'conditions' must be non-empty list"
                    )

                for i, cond in enumerate(conditions):
                    if not isinstance(cond, dict):
                        raise ValidationError(
                            f"Loop at {path}: conditions[{i}] must be a dict, got {type(cond).__name__}"
                        )
                    if "key" not in cond or "value" not in cond:
                        raise ValidationError(
                            f"Loop at {path}: conditions[{i}] must have 'key' and 'value' fields"
                        )
                    if not isinstance(cond["key"], str):
                        raise ValidationError(
                            f"Loop at {path}: conditions[{i}].key must be a string, got {type(cond['key']).__name__}"
                        )

                operator = filter_config.get("operator", "AND")
                if operator not in ["AND", "OR"]:
                    raise ValidationError(
                        f"Loop at {path}: operator must be 'AND' or 'OR', got '{operator}'"
                    )

    def _validate_validators_config(self, validators_config, path):
        """
        Validate validators configuration.

        Args:
            validators_config: Validators configuration (list of validator defs)
            path: Current path for error reporting

        Raises:
            ValidationError: If validators configuration is invalid
        """
        if not isinstance(validators_config, list):
            raise ValidationError(
                f"Validators at {path} must be a list, got {type(validators_config).__name__}"
            )

        if len(validators_config) == 0:
            raise ValidationError(
                f"Validators at {path} cannot be empty. Remove 'validate' field if no validators needed."
            )

        valid_validator_types = [
            "file-exists",
            "file-not-empty",
            "contains",
            "json-valid",
            "yaml-valid",
            "command",
        ]

        for idx, validator_def in enumerate(validators_config):
            if not isinstance(validator_def, dict):
                raise ValidationError(
                    f"Validator at {path}[{idx}] must be a dict, got {type(validator_def).__name__}"
                )

            # Each validator should have exactly one key (validator type)
            if len(validator_def) != 1:
                raise ValidationError(
                    f"Validator at {path}[{idx}] must have exactly one key, got {len(validator_def)}"
                )

            validator_type = list(validator_def.keys())[0]
            validator_config = validator_def[validator_type]

            # Validate validator type
            if validator_type not in valid_validator_types:
                raise ValidationError(
                    f"Validator at {path}[{idx}] has invalid type '{validator_type}'. "
                    f"Must be one of: {', '.join(valid_validator_types)}"
                )

            # Validate type-specific configuration
            if validator_type in ["file-exists", "file-not-empty", "json-valid", "yaml-valid"]:
                # Config must be a string (file path)
                if not isinstance(validator_config, str):
                    raise ValidationError(
                        f"Validator '{validator_type}' at {path}[{idx}] requires string (file path), "
                        f"got {type(validator_config).__name__}"
                    )

            elif validator_type == "contains":
                # Config must be a dict with 'file' and 'text' keys
                if not isinstance(validator_config, dict):
                    raise ValidationError(
                        f"Validator 'contains' at {path}[{idx}] requires dict with 'file' and 'text' keys, "
                        f"got {type(validator_config).__name__}"
                    )

                if "file" not in validator_config:
                    raise ValidationError(
                        f"Validator 'contains' at {path}[{idx}] missing required field 'file'"
                    )

                if "text" not in validator_config:
                    raise ValidationError(
                        f"Validator 'contains' at {path}[{idx}] missing required field 'text'"
                    )

                if not isinstance(validator_config["file"], str):
                    raise ValidationError(
                        f"Validator 'contains' at {path}[{idx}]: field 'file' must be string, "
                        f"got {type(validator_config['file']).__name__}"
                    )

                if not isinstance(validator_config["text"], str):
                    raise ValidationError(
                        f"Validator 'contains' at {path}[{idx}]: field 'text' must be string, "
                        f"got {type(validator_config['text']).__name__}"
                    )

            elif validator_type == "command":
                # Config must be a dict with 'cmd' key and optional 'file' key
                if not isinstance(validator_config, dict):
                    raise ValidationError(
                        f"Validator 'command' at {path}[{idx}] requires dict with 'cmd' and optional 'file' keys, "
                        f"got {type(validator_config).__name__}"
                    )

                if "cmd" not in validator_config:
                    raise ValidationError(
                        f"Validator 'command' at {path}[{idx}] missing required field 'cmd'"
                    )

                if not isinstance(validator_config["cmd"], str):
                    raise ValidationError(
                        f"Validator 'command' at {path}[{idx}]: field 'cmd' must be string, "
                        f"got {type(validator_config['cmd']).__name__}"
                    )

                # Optional file field validation
                if "file" in validator_config and not isinstance(validator_config["file"], str):
                    raise ValidationError(
                        f"Validator 'command' at {path}[{idx}]: field 'file' must be string, "
                        f"got {type(validator_config['file']).__name__}"
                    )

                timeout = validator_config.get("timeout")
                if timeout is not None and (
                    isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0
                ):
                    raise ValidationError(
                        f"Validator 'command' at {path}[{idx}]: field 'timeout' must be a "
                        f"positive number of seconds, got {timeout!r}"
                    )

    def _validate_retry_config(self, retry_config, path):
        """
        Validate retry configuration.

        Args:
            retry_config: Retry configuration dict
            path: Current path for error reporting

        Raises:
            ValidationError: If retry configuration is invalid
        """
        if not isinstance(retry_config, dict):
            raise ValidationError(
                f"Retry configuration at {path} must be a dict, got {type(retry_config).__name__}"
            )

        # Validate max-attempts field
        if "max-attempts" in retry_config:
            max_attempts = retry_config["max-attempts"]
            if not isinstance(max_attempts, int):
                raise ValidationError(
                    f"Retry at {path}: 'max-attempts' must be an integer, got {type(max_attempts).__name__}"
                )
            if max_attempts < 1:
                raise ValidationError(
                    f"Retry at {path}: 'max-attempts' must be >= 1, got {max_attempts}"
                )

        # Validate on-validation-failure field
        if "on-validation-failure" in retry_config:
            on_validation_failure = retry_config["on-validation-failure"]
            if not isinstance(on_validation_failure, str):
                raise ValidationError(
                    f"Retry at {path}: 'on-validation-failure' must be a string, got {type(on_validation_failure).__name__}"
                )

            valid_strategies = ["retry", "skip", "fail"]
            if on_validation_failure not in valid_strategies:
                raise ValidationError(
                    f"Retry at {path}: 'on-validation-failure' must be one of {valid_strategies}, got '{on_validation_failure}'"
                )

        # Check for unknown fields
        valid_fields = ["max-attempts", "on-validation-failure"]
        for field in retry_config:
            if field not in valid_fields:
                raise ValidationError(
                    f"Retry at {path}: unknown field '{field}'. Valid fields: {valid_fields}"
                )

    def _validate_skip_if_config(self, skip_config, path):
        """
        Validate skip-if configuration.

        Args:
            skip_config: Skip-if configuration dict
            path: Current path for error reporting

        Raises:
            ValidationError: If skip-if configuration is invalid
        """
        if not isinstance(skip_config, dict):
            raise ValidationError(
                f"skip-if at {path} must be a dict, got {type(skip_config).__name__}"
            )

        # skip-if should have exactly one key (condition type)
        if len(skip_config) != 1:
            raise ValidationError(
                f"skip-if at {path} must have exactly one condition, got {len(skip_config)}"
            )

        valid_condition_types = ["file-exists", "file-contains"]
        condition_type = list(skip_config.keys())[0]
        condition_config = skip_config[condition_type]

        # Validate condition type
        if condition_type not in valid_condition_types:
            raise ValidationError(
                f"skip-if at {path} has invalid condition type '{condition_type}'. "
                f"Must be one of: {', '.join(valid_condition_types)}"
            )

        # Validate type-specific configuration
        if condition_type == "file-exists":
            # Config must be a string (file path)
            if not isinstance(condition_config, str):
                raise ValidationError(
                    f"skip-if 'file-exists' at {path} requires string (file path), "
                    f"got {type(condition_config).__name__}"
                )

        elif condition_type == "file-contains":
            # Config must be a dict with 'path' and 'text' keys
            if not isinstance(condition_config, dict):
                raise ValidationError(
                    f"skip-if 'file-contains' at {path} requires dict with 'path' and 'text' keys, "
                    f"got {type(condition_config).__name__}"
                )

            if "path" not in condition_config:
                raise ValidationError(
                    f"skip-if 'file-contains' at {path} missing required field 'path'"
                )

            if "text" not in condition_config:
                raise ValidationError(
                    f"skip-if 'file-contains' at {path} missing required field 'text'"
                )

            if not isinstance(condition_config["path"], str):
                raise ValidationError(
                    f"skip-if 'file-contains' at {path}: field 'path' must be string, "
                    f"got {type(condition_config['path']).__name__}"
                )

            if not isinstance(condition_config["text"], str):
                raise ValidationError(
                    f"skip-if 'file-contains' at {path}: field 'text' must be string, "
                    f"got {type(condition_config['text']).__name__}"
                )

    def _validate_when_config(self, when_config, path):
        """
        Validate when condition configuration.

        Args:
            when_config: When condition configuration (string expression)
            path: Current path for error reporting

        Raises:
            ValidationError: If when configuration is invalid
        """
        if not isinstance(when_config, str):
            raise ValidationError(
                f"when at {path} must be a string expression, got {type(when_config).__name__}"
            )


def validate_workflow(workflow_dict):
    """
    Validate a parsed workflow against the schema.

    This is a convenience function that uses SchemaValidator.

    Args:
        workflow_dict: Parsed workflow structure

    Returns:
        bool: True if valid

    Raises:
        ValidationError: If workflow fails schema validation
    """
    validator = SchemaValidator()
    return validator.validate_schema(workflow_dict)
