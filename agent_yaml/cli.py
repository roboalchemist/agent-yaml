"""
CLI entry point for agent-yaml.

Provides the main command-line interface for running YAML workflows.
Handles argument parsing, workflow loading, and orchestration.

Usage:
    agent-yaml run <workflow.yaml> [--resume] [--dry-run] [--verbose] [--debug] [--var key=value ...]
                   [--env-file PATH ...] [--directory DIR] [--cli-agent NAME] [--model MODEL]
    agent-yaml validate <workflow.yaml> [--cli-agent NAME]
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from agent_yaml.adapters import CLINotFoundError, UnsupportedCLIError, get_adapter
from agent_yaml.ensure import EnsureValidationError, validate_ensure_block
from agent_yaml.events import emit_event
from agent_yaml.executor import ExecutionError, execute_single_task
from agent_yaml.loops import CSVLoop, GlobLoop, JsonLoop, TodoListLoop
from agent_yaml.parser import parse_workflow
from agent_yaml.validator import ValidationError, validate_workflow
from agent_yaml.variables import (
    CircularDependencyError,
    ReservedVariables,
    UndefinedVariableError,
    resolve_user_variables,
)


class EnvFileError(Exception):
    """Raised when there is an error loading an .env file."""

    pass


def parse_env_file(filepath):
    """
    Parse environment variables from a .env file.

    Supports standard .env file format:
    - KEY=value (basic assignment)
    - KEY="value" or KEY='value' (quoted values)
    - # comment lines (ignored)
    - Blank lines (ignored)
    - Inline comments after values are NOT stripped (treated as part of value)

    Args:
        filepath: Path to the .env file

    Returns:
        dict: Parsed environment variables as key-value pairs

    Raises:
        EnvFileError: If file not found or cannot be read
    """
    # Expand user home directory (~)
    filepath = os.path.expanduser(filepath)

    # Validate file exists
    if not os.path.exists(filepath):
        raise EnvFileError(f"Environment file not found: {filepath}")

    if not os.path.isfile(filepath):
        raise EnvFileError(f"Environment file is not a regular file: {filepath}")

    env_vars = {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                # Strip trailing whitespace and newline
                line = line.rstrip()

                # Skip empty lines
                if not line:
                    continue

                # Skip comment lines (lines starting with #, ignoring leading whitespace)
                stripped_line = line.lstrip()
                if stripped_line.startswith("#"):
                    continue

                # Parse KEY=value format
                if "=" not in line:
                    # Skip malformed lines (no '=' sign)
                    continue

                # Split on first '=' only
                key, value = line.split("=", 1)

                # Strip whitespace from key (but not value yet)
                key = key.strip()

                # Skip if key is empty
                if not key:
                    continue

                # Handle quoted values - strip matching quotes if present
                value = value.strip()
                if len(value) >= 2:
                    # Check for matching double quotes
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    # Check for matching single quotes
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]

                env_vars[key] = value

    except PermissionError:
        raise EnvFileError(f"Permission denied reading environment file: {filepath}")
    except OSError as e:
        raise EnvFileError(f"Error reading environment file {filepath}: {e}")

    return env_vars


def load_env_files(env_file_paths):
    """
    Load environment variables from multiple .env files.

    Files are processed in order, with later files overriding earlier ones.
    This allows for layered configurations like:
      .env (base) -> .env.local (local overrides)

    Args:
        env_file_paths: List of paths to .env files

    Returns:
        dict: Merged environment variables from all files

    Raises:
        EnvFileError: If any file not found or cannot be read
    """
    merged_env = {}

    for filepath in env_file_paths:
        file_env = parse_env_file(filepath)
        merged_env.update(file_env)

    return merged_env


def print_dry_run_plan(workflow, resolved_vars):
    """
    Print execution plan for dry-run mode.

    Args:
        workflow: Parsed workflow configuration
        resolved_vars: Resolved template variables (reserved + user)
    """
    print("\n=== DRY RUN MODE ===", file=sys.stderr)
    print("\nWorkflow Configuration:", file=sys.stderr)
    print(f"  Directory: {workflow.get('directory', '.')}", file=sys.stderr)
    print(f"  CLI Agent: {workflow.get('cli-agent', 'claude')}", file=sys.stderr)
    if workflow.get("_model_override"):
        print(f"  Model (CLI override): {workflow['_model_override']}", file=sys.stderr)
    print(f"  Error Strategy: {workflow.get('on-error', 'fail')}", file=sys.stderr)

    # Print CLI agent configuration
    cli_config = workflow.get("cli-agent-config", {})
    if cli_config:
        print("\nCLI Agent Configuration:", file=sys.stderr)
        for key, value in cli_config.items():
            print(f"  {key}: {value}", file=sys.stderr)

    # Print resolved variables
    print("\nResolved Template Variables:", file=sys.stderr)
    reserved_names = ReservedVariables.RESERVED_NAMES
    for key, value in sorted(resolved_vars.items()):
        var_type = "(reserved)" if key in reserved_names else "(user)"
        # Truncate long values
        value_str = str(value)
        if len(value_str) > 60:
            value_str = value_str[:57] + "..."
        print(f"  {key}: {value_str} {var_type}", file=sys.stderr)

    # Print ensure block
    ensure_config = workflow.get("ensure", {})
    if ensure_config:
        print("\nEnsure Block:", file=sys.stderr)
        if ensure_config.get("mcps"):
            print(f"  Required MCPs: {', '.join(ensure_config['mcps'])}", file=sys.stderr)
        if ensure_config.get("tools"):
            print(f"  Required Tools: {', '.join(ensure_config['tools'])}", file=sys.stderr)

    # Print includes
    includes = workflow.get("includes", {})
    if includes:
        print("\nIncludes:", file=sys.stderr)
        for name, content in includes.items():
            content_preview = content[:60] + "..." if len(content) > 60 else content
            print(f"  {name}: {content_preview}", file=sys.stderr)

    print("\nExecution Plan:", file=sys.stderr)
    print_task_tree_structure(workflow.get("task", []), indent=0)
    print("\n===================\n", file=sys.stderr)


def print_task_tree_structure(task_tree, indent=0):
    """
    Print the structure of a task tree showing sequential/parallel execution.

    Args:
        task_tree: Parsed task structure (list or dict)
        indent: Current indentation level
    """
    prefix = "  " * indent

    # Task tree is a list (sequential execution)
    if isinstance(task_tree, list):
        for i, step in enumerate(task_tree, 1):
            print(f"{prefix}[Sequential Step {i}]", file=sys.stderr)
            print_task_tree_structure(step, indent + 1)

    # Task tree is a dict
    elif isinstance(task_tree, dict):
        # Check if this has a 'loop' field (loop task)
        if "loop" in task_tree:
            loop_config = task_tree["loop"]
            loop_type = loop_config.get("type")
            print(f"{prefix}[Loop: {loop_type}]", file=sys.stderr)

            # Print loop-specific details
            if loop_type == "todo-list":
                source = loop_config.get("source", "N/A")
                print(f"{prefix}  Source: {source}", file=sys.stderr)
            elif loop_type == "glob":
                pattern = loop_config.get("pattern", "N/A")
                print(f"{prefix}  Pattern: {pattern}", file=sys.stderr)
            elif loop_type == "csv":
                source = loop_config.get("source", "N/A")
                print(f"{prefix}  Source: {source}", file=sys.stderr)

            # Show prompt (truncated)
            prompt = task_tree.get("prompt", "")
            if prompt:
                prompt_preview = prompt[:60] + "..." if len(prompt) > 60 else prompt
                print(f"{prefix}  Prompt: {prompt_preview}", file=sys.stderr)

        # Check if this is a task with a 'prompt' field (leaf node)
        elif "prompt" in task_tree:
            prompt = task_tree.get("prompt", "")
            prompt_preview = prompt[:60] + "..." if len(prompt) > 60 else prompt
            print(f"{prefix}[Task]", file=sys.stderr)
            print(f"{prefix}  Prompt: {prompt_preview}", file=sys.stderr)
            if task_tree.get("include"):
                print(f"{prefix}  Includes: {', '.join(task_tree['include'])}", file=sys.stderr)
            if task_tree.get("on-error"):
                print(f"{prefix}  Error strategy: {task_tree['on-error']}", file=sys.stderr)

        else:
            # This is a grouping dict - show parallel execution
            if len(task_tree) > 1:
                print(f"{prefix}[Parallel Group - {len(task_tree)} tasks]", file=sys.stderr)
            for task_name, task_def in task_tree.items():
                print(f"{prefix}  Task: {task_name}", file=sys.stderr)
                print_task_tree_structure(task_def, indent + 2)


def run_workflow(
    filepath,
    resume=False,
    dry_run=False,
    verbose=False,
    debug=False,
    var_overrides=None,
    directory_override=None,
    env_files=None,
    cli_agent_override=None,
    model_override=None,
    event_sink=None,
):
    """
    Execute a YAML workflow file.

    This function orchestrates the complete workflow execution by:
    1. Loading and parsing the YAML file
    2. Validating the schema
    3. Injecting reserved variables
    4. Resolving template variables (with overrides)
    5. Validating ensure block
    6. Getting the appropriate CLI adapter
    7. Executing the task tree
    8. Handling loops and checkpoints

    Args:
        filepath: Path to YAML workflow file
        resume: Resume from checkpoint if available
        dry_run: Parse and validate only, don't execute
        verbose: Enable verbose logging
        debug: Print full CLI commands before execution
        var_overrides: Dict of variable overrides from CLI
        directory_override: Override for the working directory
        env_files: List of .env file paths to load
        cli_agent_override: Replaces the workflow's `cli-agent` (validated like the YAML field)
        model_override: Model for every task; beats workflow- and task-level `model`

    Returns:
        int: Exit code (0 = success, 1 = failure)

    Logs to stderr:
        - Workflow start/end
        - Task progress
        - Errors and warnings
    """
    var_overrides = var_overrides or {}
    env_files = env_files or []

    try:
        # Step 1: Load YAML with YAMLParser
        if verbose:
            print(f"Loading workflow: {filepath}", file=sys.stderr)

        try:
            workflow = parse_workflow(filepath)
        except yaml.YAMLError as e:
            print(f"Error: Invalid YAML syntax in {filepath}: {e}", file=sys.stderr)
            return 1
        except FileNotFoundError:
            print(f"Error: Workflow file not found: {filepath}", file=sys.stderr)
            return 1

        # Track workflow directory for relative include path resolution
        workflow_dir = os.path.dirname(os.path.abspath(filepath))
        workflow["_workflow_dir"] = workflow_dir
        workflow["_event_sink"] = event_sink

        # Store debug and verbose flags in workflow config for access by loops and executor
        workflow["_debug"] = debug
        workflow["_verbose"] = verbose

        # CLI agent/model overrides (applied before validation so bad names are rejected)
        if cli_agent_override:
            workflow["cli-agent"] = cli_agent_override
        if model_override:
            workflow["_model_override"] = model_override

        # Step 2: Validate with SchemaValidator
        if verbose:
            print("Validating workflow schema...", file=sys.stderr)

        try:
            validate_workflow(workflow)
        except ValidationError as e:
            print(f"Error: Schema validation failed: {e}", file=sys.stderr)
            return 1

        # Step 2b: Load environment variables from .env files
        # Precedence: system env < .env file < workflow environment < task env < CLI --var
        if env_files:
            if verbose:
                print(f"Loading environment from {len(env_files)} .env file(s)...", file=sys.stderr)

            try:
                env_file_vars = load_env_files(env_files)

                if verbose:
                    print(f"  Loaded {len(env_file_vars)} variable(s) from .env files", file=sys.stderr)

                # Merge env file vars with workflow environment
                # Workflow environment overrides env file (to maintain precedence)
                workflow_env = workflow.get("environment", {})
                merged_env = env_file_vars.copy()  # Start with env file vars
                merged_env.update(workflow_env)  # Workflow overrides env file
                workflow["environment"] = merged_env

            except EnvFileError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        # Step 3: Inject reserved vars with ReservedVariables
        if verbose:
            print("Resolving reserved variables...", file=sys.stderr)

        # Apply directory override if provided
        directory = directory_override if directory_override else workflow.get("directory", ".")
        if directory_override:
            workflow["directory"] = directory_override
            if verbose:
                print(f"Overriding directory: {directory_override}", file=sys.stderr)
        reserved_vars = ReservedVariables()
        # Pass workflow environment to get_reserved_vars for {{env.VAR}} interpolation
        workflow_env = workflow.get("environment", {})
        resolved_vars = reserved_vars.get_reserved_vars(directory, workflow_env=workflow_env)

        # Step 4: Resolve template vars with TemplateVariableResolver (apply var_overrides)
        if verbose:
            print("Resolving template variables...", file=sys.stderr)

        # Get user-defined variables from workflow
        user_vars = workflow.get("template-variables", {})

        # Apply CLI overrides to user variables
        for key, value in var_overrides.items():
            if key in ReservedVariables.RESERVED_NAMES:
                print(
                    f"Warning: Cannot override reserved variable '{key}', ignoring", file=sys.stderr
                )
                continue

            # Warn if overriding undefined variable (allows it, but warns)
            if key not in user_vars:
                print(
                    f"Warning: Variable '{key}' not defined in workflow template-variables, adding as new variable",
                    file=sys.stderr,
                )

            user_vars[key] = value

        # Merge user variables into resolved vars with circular dependency detection
        try:
            resolved_vars = resolve_user_variables(user_vars, resolved_vars)
        except CircularDependencyError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except UndefinedVariableError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if verbose:
            print(f"Resolved variables: {list(resolved_vars.keys())}", file=sys.stderr)

        # Step 5: Validate ensure block with EnsureValidator
        ensure_config = workflow.get("ensure", {})
        if ensure_config:
            if verbose:
                print("Validating ensure block...", file=sys.stderr)

            try:
                validate_ensure_block(ensure_config)
            except EnsureValidationError as e:
                print(f"Error: Ensure validation failed: {e}", file=sys.stderr)
                return 1

        # Step 6: Get adapter from cli-agent field
        cli_agent = workflow.get("cli-agent", "claude")
        if verbose:
            print(f"Using CLI agent: {cli_agent}", file=sys.stderr)

        try:
            adapter = get_adapter(cli_agent)
        except UnsupportedCLIError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except CLINotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        # Dry run mode: print execution plan and execute in dry-run mode
        if dry_run:
            print_dry_run_plan(workflow, resolved_vars)

        # Step 7: Execute task tree with TaskExecutor
        if not dry_run:
            print(f"Starting workflow execution: {filepath}", file=sys.stderr)

        emit_event(
            workflow,
            "workflow_started",
            node_id="workflow",
            status="running",
            workflow_path=os.path.abspath(filepath),
            dry_run=dry_run,
        )

        error_strategy = workflow.get("on-error", "fail")
        task_tree = workflow.get("task", [])

        # Step 8: Handle loops with Loop classes
        # Execute task tree (sequential array of steps)
        try:
            exit_code = execute_task_tree(
                task_tree, adapter, resolved_vars, workflow, error_strategy, verbose, dry_run, debug
            )

            if exit_code == 0:
                emit_event(
                    workflow,
                    "workflow_completed",
                    node_id="workflow",
                    status="success",
                    exit_code=exit_code,
                    dry_run=dry_run,
                )
                if dry_run:
                    print("\nDry run complete. Workflow is valid.", file=sys.stderr)
                else:
                    print("Workflow completed successfully", file=sys.stderr)
            else:
                emit_event(
                    workflow,
                    "workflow_failed",
                    node_id="workflow",
                    status="failed",
                    exit_code=exit_code,
                    dry_run=dry_run,
                )
                if dry_run:
                    print(
                        f"\nDry run completed with validation errors (exit code: {exit_code})",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"Workflow completed with errors (exit code: {exit_code})", file=sys.stderr
                    )

            return exit_code

        except ExecutionError as e:
            emit_event(
                workflow,
                "workflow_failed",
                node_id="workflow",
                status="failed",
                exit_code=1,
                message=str(e),
                dry_run=dry_run,
            )
            print(f"Error: Workflow execution failed: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            emit_event(
                workflow,
                "workflow_failed",
                node_id="workflow",
                status="failed",
                exit_code=1,
                message=str(e),
                dry_run=dry_run,
            )
            print(f"Error: Unexpected error during execution: {e}", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"Error: Unexpected error: {e}", file=sys.stderr)
        return 1


def execute_task_tree(
    task_tree,
    adapter,
    resolved_vars,
    workflow_config,
    error_strategy="fail",
    verbose=False,
    dry_run=False,
    debug=False,
    node_path=(),
):
    """
    Execute a task tree with parallel/sequential logic.

    Args:
        task_tree: Parsed task structure (list of dicts or dict)
        adapter: CLI adapter instance
        resolved_vars: Resolved variables for interpolation
        workflow_config: Complete workflow configuration
        error_strategy: Error handling strategy ('fail', 'continue', 'skip')
        verbose: Enable verbose logging
        dry_run: If True, execute in dry-run mode (no subprocess calls)
        debug: If True, print full CLI commands before execution

    Returns:
        int: Exit code (0 = success, non-zero = failure)
    """
    if not node_path and workflow_config.get("_node_path"):
        node_path = tuple(workflow_config.get("_node_path", ()))

    # Task tree is a list (sequential execution)
    if isinstance(task_tree, list):
        for index, step in enumerate(task_tree):
            # Each step is either a dict (parallel) or a task definition
            if isinstance(step, dict):
                # Execute this step (may be parallel or sequential)
                child_workflow_config = workflow_config.copy()
                child_workflow_config["_node_path"] = node_path + (str(index),)
                exit_code = execute_task_tree(
                    step,
                    adapter,
                    resolved_vars,
                    child_workflow_config,
                    error_strategy,
                    verbose,
                    dry_run,
                    debug,
                )
                if exit_code != 0 and error_strategy == "fail":
                    return exit_code
            else:
                print(f"Warning: Unexpected task tree structure: {step}", file=sys.stderr)

        return 0

    # Task tree is a dict (parallel execution or named task)
    elif isinstance(task_tree, dict):
        # Check if this has a 'loop' field (loop task) - must check BEFORE prompt
        # because loop tasks also have 'prompt' field
        if "loop" in task_tree:
            loop_config = task_tree["loop"]
            loop_type = loop_config.get("type")
            node_id = ".".join(node_path) if node_path else "loop"
            task_workflow = workflow_config.copy()
            task_workflow["_current_node_id"] = node_id
            emit_event(
                task_workflow,
                "loop_started",
                node_id=node_id,
                status="running",
                loop_type=loop_type,
            )

            if verbose:
                print(f"Executing loop: {loop_type}", file=sys.stderr)

            # Execute appropriate loop type
            try:
                if loop_type == "todo-list":
                    loop = TodoListLoop({}, {})
                    result = loop.execute(
                        task_tree, loop_config, resolved_vars, adapter, task_workflow, dry_run
                    )
                elif loop_type == "csv":
                    loop = CSVLoop({}, {})
                    result = loop.execute(
                        task_tree, loop_config, resolved_vars, adapter, task_workflow, dry_run
                    )
                elif loop_type == "glob":
                    loop = GlobLoop({}, {})
                    result = loop.execute(
                        task_tree, loop_config, resolved_vars, adapter, task_workflow, dry_run
                    )
                elif loop_type == "json":
                    loop = JsonLoop({}, {})
                    result = loop.execute(
                        task_tree, loop_config, resolved_vars, adapter, task_workflow, dry_run
                    )
                elif loop_type == "jsonl":
                    loop = JsonLoop({}, {})
                    result = loop.execute(
                        task_tree, loop_config, resolved_vars, adapter, task_workflow, dry_run
                    )
                else:
                    print(f"Error: Unknown loop type: {loop_type}", file=sys.stderr)
                    return 1

                # Check loop result status
                if result["status"] == "failed":
                    emit_event(
                        task_workflow,
                        "loop_failed",
                        node_id=node_id,
                        status="failed",
                        loop_type=loop_type,
                        payload=result,
                    )
                    return 1
                elif result["status"] == "partial" and error_strategy == "fail":
                    emit_event(
                        task_workflow,
                        "loop_failed",
                        node_id=node_id,
                        status="failed",
                        loop_type=loop_type,
                        payload=result,
                    )
                    return 1
                else:
                    emit_event(
                        task_workflow,
                        "loop_completed",
                        node_id=node_id,
                        status="success",
                        loop_type=loop_type,
                        payload=result,
                    )
                    return 0

            except ExecutionError as e:
                emit_event(
                    task_workflow,
                    "loop_failed",
                    node_id=node_id,
                    status="failed",
                    loop_type=loop_type,
                    message=str(e),
                )
                print(f"Error: Loop execution failed: {e}", file=sys.stderr)
                return 1

        # Check if this is a task with a 'prompt' field (leaf node)
        elif "prompt" in task_tree:
            # This is a single task, execute it
            try:
                node_id = ".".join(node_path) if node_path else "task"
                task_name = node_path[-1] if node_path else "task"
                task_workflow = workflow_config.copy()
                task_workflow["_current_node_id"] = node_id
                result = execute_single_task(
                    task_name, task_tree, resolved_vars, adapter, task_workflow, dry_run, debug
                )
                return 0 if result["status"] in ("success", "skipped") else 1
            except ExecutionError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        else:
            # This is a grouping dict - execute all keys in parallel using ThreadPoolExecutor
            if verbose:
                print(f"Executing {len(task_tree)} tasks in parallel", file=sys.stderr)

            # Store task results for error aggregation
            task_results = {}
            errors = []

            # Use ThreadPoolExecutor for true parallel execution
            with ThreadPoolExecutor() as executor:
                # Submit all tasks to thread pool
                future_to_task = {}
                for task_name, task_def in task_tree.items():
                    if verbose:
                        print(f"Submitting task: {task_name}", file=sys.stderr)

                    child_workflow_config = workflow_config.copy()
                    child_workflow_config["_node_path"] = node_path + (task_name,)
                    future = executor.submit(
                        execute_task_tree,
                        task_def,
                        adapter,
                        resolved_vars,
                        child_workflow_config,
                        error_strategy,
                        verbose,
                        dry_run,
                        debug,
                    )
                    future_to_task[future] = task_name

                # Collect results as tasks complete
                for future in as_completed(future_to_task):
                    task_name = future_to_task[future]
                    try:
                        exit_code = future.result()
                        task_results[task_name] = {
                            "status": "success" if exit_code == 0 else "failed",
                            "exit_code": exit_code,
                        }

                        if exit_code != 0:
                            error_msg = f"Task '{task_name}' failed with exit code {exit_code}"
                            errors.append(error_msg)

                            if verbose:
                                print(
                                    f"Task '{task_name}' failed with exit code {exit_code}",
                                    file=sys.stderr,
                                )

                            # If on-error: fail, cancel remaining tasks and return immediately
                            if error_strategy == "fail":
                                if verbose:
                                    print(
                                        "Error strategy is 'fail', cancelling remaining tasks",
                                        file=sys.stderr,
                                    )
                                # Shutdown executor and cancel pending tasks
                                executor.shutdown(wait=False, cancel_futures=True)
                                return exit_code
                        else:
                            if verbose:
                                print(f"Task '{task_name}' completed successfully", file=sys.stderr)

                    except Exception as e:
                        error_msg = f"Task '{task_name}' raised exception: {e}"
                        errors.append(error_msg)
                        task_results[task_name] = {
                            "status": "failed",
                            "exit_code": 1,
                            "error": str(e),
                        }

                        if verbose:
                            print(f"Task '{task_name}' raised exception: {e}", file=sys.stderr)

                        # If on-error: fail, cancel remaining tasks and return immediately
                        if error_strategy == "fail":
                            if verbose:
                                print(
                                    "Error strategy is 'fail', cancelling remaining tasks",
                                    file=sys.stderr,
                                )
                            executor.shutdown(wait=False, cancel_futures=True)
                            return 1

            # All tasks completed - check for any errors
            if errors:
                if error_strategy == "fail":
                    # This should not be reached due to early return, but for safety
                    return 1
                elif error_strategy == "continue":
                    # Log errors but continue
                    if verbose:
                        print(
                            f"Completed with {len(errors)} error(s), continuing due to error strategy",
                            file=sys.stderr,
                        )
                    # Return success if error_strategy is continue
                    return 0

            return 0

    else:
        print(f"Error: Unexpected task tree type: {type(task_tree)}", file=sys.stderr)
        return 1


def validate_workflow_cmd(filepath, cli_agent_override=None):
    """
    Validate a YAML workflow file without executing.

    Args:
        filepath: Path to YAML workflow file
        cli_agent_override: Validate against this CLI agent instead of the workflow's

    Returns:
        int: Exit code (0 = valid, 1 = invalid)
    """
    # Use dry_run mode to validate
    return run_workflow(
        filepath, dry_run=True, verbose=True, cli_agent_override=cli_agent_override
    )


def parse_var_overrides(var_args):
    """
    Parse variable override arguments from CLI.

    Args:
        var_args: List of "key=value" strings

    Returns:
        dict: Parsed variable overrides

    Raises:
        ValueError: If argument format is invalid
    """
    overrides = {}
    for arg in var_args:
        if "=" not in arg:
            raise ValueError(f"Invalid variable format: '{arg}'. Expected 'key=value'")

        key, value = arg.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            raise ValueError(f"Invalid variable format: '{arg}'. Key cannot be empty")

        overrides[key] = value

    return overrides


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agent-yaml", description="Execute YAML workflows with AI CLI agents"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a YAML workflow")
    run_parser.add_argument("workflow", help="Path to YAML workflow file")
    run_parser.add_argument(
        "--resume", action="store_true", help="Resume from checkpoint if available"
    )
    run_parser.add_argument(
        "--dry-run", action="store_true", help="Validate workflow without executing"
    )
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    run_parser.add_argument(
        "--debug", action="store_true", help="Print full CLI commands before execution"
    )
    run_parser.add_argument(
        "--var", action="append", default=[], help="Override template variable (key=value)"
    )
    run_parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        help="Load environment variables from .env file (can be specified multiple times)",
    )
    run_parser.add_argument(
        "--directory", "-d", help="Override the working directory for the CLI agent"
    )
    run_parser.add_argument(
        "--cli-agent", help="Override the workflow's cli-agent (opencode, claude, gemini, qwen, codex)"
    )
    run_parser.add_argument(
        "--model", help="Model for every task, overriding workflow and task cli-agent-config"
    )

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a YAML workflow")
    validate_parser.add_argument("workflow", help="Path to YAML workflow file")
    validate_parser.add_argument(
        "--cli-agent", help="Validate against this cli-agent instead of the workflow's"
    )

    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Run the local visual workflow UI")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    serve_parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    serve_parser.add_argument("--db", default=None, help="Override SQLite database path")
    serve_parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")

    args = parser.parse_args()

    if args.command == "run":
        try:
            var_overrides = parse_var_overrides(args.var)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        exit_code = run_workflow(
            args.workflow,
            resume=args.resume,
            dry_run=args.dry_run,
            verbose=args.verbose,
            debug=args.debug,
            var_overrides=var_overrides,
            directory_override=args.directory,
            env_files=args.env_file,
            cli_agent_override=args.cli_agent,
            model_override=args.model,
        )
        sys.exit(exit_code)

    elif args.command == "validate":
        exit_code = validate_workflow_cmd(args.workflow, cli_agent_override=args.cli_agent)
        sys.exit(exit_code)

    elif args.command == "serve":
        try:
            import uvicorn
            from agent_yaml.web.app import create_app
        except Exception as e:
            print(
                "Error: web UI dependencies are missing. Install with: "
                "pip install fastapi uvicorn pydantic",
                file=sys.stderr,
            )
            print(f"Details: {e}", file=sys.stderr)
            sys.exit(1)

        app = create_app(db_path=args.db)
        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
