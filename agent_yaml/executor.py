"""
Task execution engine.

Orchestrates task execution with support for:
- Parallel execution (object keys spawn concurrent processes)
- Sequential execution (array items execute one after another)
- Error handling strategies (fail, continue, skip)
- Timeout management (per-task subprocess timeout)
- Exit code validation (0 = success, non-zero = failure)
- Per-task directory override

Execution model:
- Object keys = parallel (concurrent subprocess spawning)
- Array items = sequential (wait for each to complete)

Error handling:
- on-error: fail (default) - Stop workflow on first error
- on-error: continue - Log error, continue remaining tasks
- on-error: skip - Skip failed task without marking failure

Reference: spec/PROJECT_SPECS.md lines 271-349 for execution philosophy.
"""

import logging
import os
import subprocess
import sys

from .events import emit_event
from .includes import append_includes_to_prompt, resolve_includes
from .utils import interpolate_variables


def build_merged_environment(workflow_config, task_def, resolved_vars):
    """
    Build merged environment variables for subprocess execution.

    Merges environment variables from three sources with the following precedence
    (later overrides earlier):
    1. System environment (os.environ)
    2. Workflow-level environment variables
    3. Task-level env variables

    Template variables in env values are interpolated using resolved_vars.

    Args:
        workflow_config: Workflow configuration containing optional 'environment' dict
        task_def: Task definition containing optional 'env' dict
        resolved_vars: Resolved template variables for interpolation

    Returns:
        dict: Merged environment variables (copy of os.environ + workflow + task env)

    Note:
        - os.environ is NOT modified (we use copy())
        - All env values are converted to strings
        - Template variables like {{gitroot}} are interpolated in values
    """
    # Start with copy of system environment (CRITICAL: don't modify os.environ)
    merged_env = os.environ.copy()

    # Add workflow-level environment variables
    workflow_env = workflow_config.get("environment", {})
    for key, value in workflow_env.items():
        # Convert to string and interpolate template variables
        str_value = str(value) if value is not None else ""
        str_value = interpolate_variables(str_value, resolved_vars)
        merged_env[key] = str_value

    # Add task-level env variables (overrides workflow-level)
    task_env = task_def.get("env", {})
    for key, value in task_env.items():
        # Convert to string and interpolate template variables
        str_value = str(value) if value is not None else ""
        str_value = interpolate_variables(str_value, resolved_vars)
        merged_env[key] = str_value

    return merged_env


def execute_single_task(
    task_name, task_def, resolved_vars, adapter, workflow_config, dry_run=False, debug=False, _attempt=1
):
    """
    Execute a single task by building CLI command and running subprocess.

    This method:
    1. Extracts prompt from task_def
    2. Gets task-level on-error setting or uses workflow-level default
    3. Resolves includes by looking up references in workflow_config["includes"]
    4. Appends includes to prompt (no interpolation yet)
    5. Interpolates variables in final concatenated prompt (SINGLE interpolation)
    6. Builds CLI command using adapter.build_command()
    7. Executes subprocess with timeout from workflow_config (unless dry_run=True)
    8. Captures exit code (0=success, non-zero=failure)
    9. Handles errors according to on-error setting

    In dry-run mode, builds the command and prints it without executing subprocess.
    In debug mode, prints the full command before executing.

    CLI output is opaque - stdout/stderr are ignored, only exit code matters.

    Args:
        task_name: Name of the task
        task_def: Task definition dict with 'prompt', optional 'include', 'on-error', 'cli-agent-config'
        resolved_vars: Resolved variables for interpolation
        adapter: CLI adapter instance
        workflow_config: Workflow configuration with 'cli-agent-config', 'on-error', 'includes', 'directory'
        dry_run: If True, print command without executing (default: False)
        debug: If True, print full CLI command before execution (default: False)

    Returns:
        dict: Execution result with keys:
            - task_name: Name of the task
            - status: "success", "failed", or "skipped"
            - exit_code: Exit code from subprocess
            - error_message: Error message if failed (optional)

    Raises:
        ExecutionError: If task fails and on-error strategy is 'fail'

    Reference:
        - spec/PROJECT_SPECS.md lines 316-330 (opaque output philosophy)
        - spec/YAML_SPEC.md lines 330-359 (task-level on-error override)
        - Task-level cli-agent-config merges with global config (task overrides take precedence)
    """
    event_node_id = workflow_config.get("_current_node_id", task_name)
    emit_event(
        workflow_config,
        "task_started",
        node_id=event_node_id,
        task_name=task_name,
        attempt=_attempt,
        status="running",
    )

    # 1. Extract prompt from task definition
    prompt = task_def.get("prompt", "")
    if not prompt:
        emit_event(
            workflow_config,
            "task_failed",
            node_id=event_node_id,
            task_name=task_name,
            attempt=_attempt,
            status="failed",
            message=f"Task '{task_name}' has no prompt defined",
        )
        raise ExecutionError(f"Task '{task_name}' has no prompt defined")

    # 1a. Determine working directory early (needed for skip-if and execution)
    # Task-level directory overrides workflow-level directory
    if "directory" in task_def:
        task_directory = task_def["directory"]

        # Interpolate template variables in the directory path
        task_directory = interpolate_variables(task_directory, resolved_vars)

        # Expand user home directory (~)
        task_directory = os.path.expanduser(task_directory)

        # Resolve relative paths relative to workflow directory
        if not os.path.isabs(task_directory):
            workflow_dir = workflow_config.get("directory", ".")
            workflow_dir = os.path.expanduser(workflow_dir)
            task_directory = os.path.join(workflow_dir, task_directory)

        # Convert to absolute path
        working_dir = os.path.abspath(task_directory)
    else:
        # Use workflow-level directory
        workflow_dir = workflow_config.get("directory", ".")
        workflow_dir = os.path.expanduser(workflow_dir)
        working_dir = os.path.abspath(workflow_dir)

    # 1b. Check skip-if conditions BEFORE execution
    skip_config = task_def.get("skip-if")
    if skip_config:
        from .skip_conditions import check_skip_conditions, SkipConditionError

        try:
            skip_result = check_skip_conditions(skip_config, resolved_vars, working_dir)
            if skip_result.should_skip:
                emit_event(
                    workflow_config,
                    "task_skipped",
                    node_id=event_node_id,
                    task_name=task_name,
                    attempt=_attempt,
                    status="skipped",
                    payload={"skip_condition": skip_result.to_dict()},
                )
                return {
                    "task_name": task_name,
                    "status": "skipped",
                    "exit_code": 0,
                    "skip_condition": skip_result.to_dict(),
                }
        except SkipConditionError as e:
            # Skip condition configuration error or file not found for file-contains
            error_msg = f"Task '{task_name}' skip-if condition error: {e}"
            print(error_msg, file=sys.stderr)

            # Get error strategy to determine how to handle this
            error_strategy = task_def.get("on-error", workflow_config.get("on-error", "fail"))
            if error_strategy == "fail":
                raise ExecutionError(error_msg)
            elif error_strategy == "continue":
                return {
                    "task_name": task_name,
                    "status": "failed",
                    "exit_code": -1,
                    "error_message": error_msg,
                }
            else:  # skip
                return {"task_name": task_name, "status": "skipped", "exit_code": -1}

    # 1c. Check when condition BEFORE execution (after skip-if)
    when_expression = task_def.get("when")
    if when_expression is not None:
        from .when_conditions import check_when_condition, WhenConditionError

        try:
            when_result = check_when_condition(when_expression, resolved_vars)
            if not when_result.should_execute:
                emit_event(
                    workflow_config,
                    "task_skipped",
                    node_id=event_node_id,
                    task_name=task_name,
                    attempt=_attempt,
                    status="skipped",
                    payload={"when_condition": when_result.to_dict()},
                )
                return {
                    "task_name": task_name,
                    "status": "skipped",
                    "exit_code": 0,
                    "when_condition": when_result.to_dict(),
                }
        except WhenConditionError as e:
            # When condition evaluation error
            error_msg = f"Task '{task_name}' when condition error: {e}"
            print(error_msg, file=sys.stderr)

            # Get error strategy to determine how to handle this
            error_strategy = task_def.get("on-error", workflow_config.get("on-error", "fail"))
            if error_strategy == "fail":
                raise ExecutionError(error_msg)
            elif error_strategy == "continue":
                return {
                    "task_name": task_name,
                    "status": "failed",
                    "exit_code": -1,
                    "error_message": error_msg,
                }
            else:  # skip
                return {"task_name": task_name, "status": "skipped", "exit_code": -1}

    # 2. Get error handling strategy (task-level overrides workflow-level)
    error_strategy = task_def.get("on-error", workflow_config.get("on-error", "fail"))

    # Validate error strategy
    valid_strategies = ["fail", "continue", "skip"]
    if error_strategy not in valid_strategies:
        raise ExecutionError(
            f"Invalid on-error strategy '{error_strategy}' for task '{task_name}'. "
            f"Must be one of: {', '.join(valid_strategies)}"
        )

    # 2b. Get retry configuration
    retry_config = task_def.get("retry", {})
    max_attempts = retry_config.get("max-attempts", 1)
    on_validation_failure = retry_config.get("on-validation-failure", "fail")

    # Print retry attempt info if this is a retry
    if _attempt > 1:
        print(
            f"⟳ Retrying task '{task_name}' (attempt {_attempt}/{max_attempts})...",
            file=sys.stderr,
        )

    # 3-5. Resolve includes and append to prompt (no interpolation yet)
    include_refs = task_def.get("include", [])
    if include_refs:
        workflow_includes = workflow_config.get("includes", {})
        workflow_dir = workflow_config.get("_workflow_dir", ".")

        # Concatenate include strings in order
        # Support BOTH named inline includes AND file-based includes
        include_parts = []
        for ref in include_refs:
            # Check if this is a named inline include first
            if ref in workflow_includes:
                # Named inline include (backward compatibility)
                include_parts.append(workflow_includes[ref])
            else:
                # File-based include - resolve the file path and read content
                # This treats ref as a file path
                try:
                    # resolve_includes handles a list, so we pass a single-item list
                    file_content = resolve_includes([ref], workflow_dir, resolved_vars)
                    include_parts.append(file_content)
                except (FileNotFoundError, PermissionError) as e:
                    raise ExecutionError(
                        f"Task '{task_name}' failed to resolve include '{ref}': {str(e)}"
                    )

        # Join with single space separator
        include_string = " ".join(include_parts)

        # Append to prompt (variables will be interpolated AFTER concatenation)
        prompt = append_includes_to_prompt(prompt, include_string)

    # 5b. Update resolved_vars with task-level env for {{env.VAR}} interpolation
    # Task env should override workflow env in the 'env' namespace
    task_env = task_def.get("env", {})
    if task_env and "env" in resolved_vars:
        # Create a copy of resolved_vars to avoid modifying the original
        resolved_vars = dict(resolved_vars)
        # Create a copy of the env dict and merge task env
        updated_env = dict(resolved_vars["env"])
        for key, value in task_env.items():
            updated_env[key] = str(value) if value is not None else ""
        resolved_vars["env"] = updated_env

    # 6. Interpolate variables in final prompt (SINGLE interpolation after concatenation)
    prompt = interpolate_variables(prompt, resolved_vars)

    # 7. Build CLI command with merged config (task-level overrides global)
    cli_config = workflow_config.get("cli-agent-config", {}).copy()

    # Merge task-level cli-agent-config if present (allows per-task timeout overrides)
    task_cli_config = task_def.get("cli-agent-config", {})
    if task_cli_config:
        cli_config.update(task_cli_config)

    # CLI flags win over workflow- and task-level config
    if workflow_config.get("_model_override"):
        cli_config["model"] = workflow_config["_model_override"]
    if workflow_config.get("_debug", False):
        cli_config["debug"] = True
    command = adapter.build_command(cli_config, prompt)

    # 7b. Set up task workflow config with computed working directory
    # Create a copy of workflow_config for this task to avoid modifying original
    task_workflow_config = workflow_config.copy()
    task_workflow_config["directory"] = working_dir

    # Validate directory exists (unless in dry-run mode)
    if "directory" in task_def and not dry_run and not os.path.isdir(working_dir):
        error_msg = (
            f"Task '{task_name}' directory does not exist\n\n"
            f"Context: Task specifies directory override\n"
            f"Expected: Directory to exist at path\n"
            f"Found: Directory not found: {working_dir}\n"
            f"Suggestion: Create the directory before running the workflow, or check the path"
        )
        if error_strategy == "fail":
            raise ExecutionError(error_msg)
        elif error_strategy == "continue":
            return {
                "task_name": task_name,
                "status": "failed",
                "exit_code": -1,
                "error_message": error_msg,
            }
        else:  # skip
            return {"task_name": task_name, "status": "skipped", "exit_code": -1}

    # 7c. Build merged environment variables
    # Precedence: system env < workflow environment < task env
    merged_env = build_merged_environment(workflow_config, task_def, resolved_vars)

    # Agent CLIs with shell tools (opencode, claude) resolve relative paths against
    # $PWD, not the real process cwd. Keep it in sync with the launch directory so
    # task-level `directory` overrides and relative-path prompts behave as written.
    if working_dir:
        merged_env["PWD"] = str(working_dir)

    # Dry run mode: print command without executing
    if dry_run:
        print(f"[DRY RUN] Task '{task_name}' would execute:", file=sys.stderr)
        print(f"  Command: {' '.join(command)}", file=sys.stderr)
        print(f"  Working directory: {task_workflow_config.get('directory')}", file=sys.stderr)
        print(f"  Error strategy: {error_strategy}", file=sys.stderr)
        timeout = cli_config.get("timeout", None)
        print(f"  Timeout: {timeout}s", file=sys.stderr)
        # Show custom env vars if set
        workflow_env = workflow_config.get("environment", {})
        task_env = task_def.get("env", {})
        if workflow_env or task_env:
            print("  Environment variables:", file=sys.stderr)
            for key in sorted(set(workflow_env.keys()) | set(task_env.keys())):
                if key in task_env:
                    print(f"    {key}={merged_env.get(key)} (task)", file=sys.stderr)
                else:
                    print(f"    {key}={merged_env.get(key)} (workflow)", file=sys.stderr)
        emit_event(
            workflow_config,
            "task_completed",
            node_id=event_node_id,
            task_name=task_name,
            attempt=_attempt,
            status="success",
            exit_code=0,
            dry_run=True,
        )
        return {"task_name": task_name, "status": "success", "exit_code": 0}

    # Debug mode: print command before executing
    if debug:
        print(f"[DEBUG] Task '{task_name}':", file=sys.stderr)
        print(f"  Command: {' '.join(command)}", file=sys.stderr)
        print(f"  Working directory: {task_workflow_config.get('directory')}", file=sys.stderr)
        timeout = cli_config.get("timeout", None)
        print(f"  Timeout: {timeout}s", file=sys.stderr)

    # 8. Execute subprocess with timeout
    timeout = cli_config.get("timeout", None)  # Default no timeout
    working_dir = task_workflow_config.get("directory")

    # Check if we should use streaming mode
    use_streaming = debug or workflow_config.get("_debug", False)
    # When debug mode is on, adapter will set output-format to stream-json
    output_format = cli_config.get("output-format")
    if output_format is None and use_streaming:
        output_format = "stream-json"
    elif output_format is None:
        output_format = "text"
    is_stream_json = output_format == "stream-json"

    # Set up logging if in debug mode
    logger = None
    log_file = None
    if use_streaming:
        from datetime import datetime

        # Use workspace if available, otherwise use /tmp
        workspace = resolved_vars.get("workspace")
        if workspace:
            logs_dir = os.path.join(workspace, "logs")
        else:
            logs_dir = "/tmp/agent-yaml-logs"

        os.makedirs(logs_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_task_name = task_name.replace("/", "-").replace(" ", "_")
        log_file = os.path.join(logs_dir, f"{safe_task_name}-{timestamp}.log")

        # Set up logger with both file and console handlers
        logger = logging.getLogger(f"agent-yaml.{safe_task_name}.{timestamp}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        # File handler
        file_handler = logging.FileHandler(log_file, mode="w")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter("%(message)s")
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # Console handler (to stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_formatter = logging.Formatter("%(message)s")
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        logger.info(f"=== Task: {task_name} ===")
        logger.info(f"=== Command: {' '.join(command)} ===")
        logger.info("")

    try:
        if use_streaming and is_stream_json:
            # Streaming mode: Use Popen and parse stream-json in real-time
            import json
            import time

            # stderr is merged into stdout: a separate stderr pipe that is only read after
            # exit deadlocks once the agent writes more than a pipe buffer of stderr.
            process = subprocess.Popen(
                command,
                cwd=working_dir,
                env=merged_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line-buffered
            )

            start_time = time.time()

            if logger:
                logger.info("=== STREAMING OUTPUT ===")

            # Read stdout line by line in real-time
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break

                line = line.rstrip()
                if not line:
                    continue

                if logger:
                    try:
                        event = json.loads(line)
                        event_type = event.get("type")

                        # Log different event types
                        if event_type == "assistant":
                            message = event.get("message", {})
                            content = message.get("content", [])
                            for item in content:
                                if item.get("type") == "text":
                                    logger.info(item.get("text", ""))
                                elif item.get("type") == "tool_use":
                                    tool_name = item.get("name", "unknown")
                                    tool_input = item.get("input", {})
                                    logger.info(f"\n[Tool: {tool_name}]")
                                    # Show relevant tool parameters
                                    if tool_name == "Bash":
                                        cmd = tool_input.get("command", "")
                                        desc = tool_input.get("description", "")
                                        logger.info(f"  Command: {cmd}")
                                        if desc:
                                            logger.info(f"  Description: {desc}")
                                    elif tool_name in ["Edit", "Write", "Read"]:
                                        file_path = tool_input.get("file_path", "")
                                        logger.info(f"  File: {file_path}")
                                        if tool_name == "Edit":
                                            old_str = tool_input.get("old_string", "")[:100]
                                            new_str = tool_input.get("new_string", "")[:100]
                                            logger.info(f"  Replacing: {old_str}...")
                                            logger.info(f"  With: {new_str}...")
                                    else:
                                        # Generic tool - show all inputs
                                        for key, value in tool_input.items():
                                            val_str = str(value)[:100]
                                            logger.info(f"  {key}: {val_str}")

                        elif event_type == "result":
                            result_text = event.get("result", "")
                            if result_text:
                                logger.info("\n=== Final Result ===")
                                logger.info(result_text)
                    except json.JSONDecodeError:
                        # Not JSON, just log the line
                        logger.info(line)

                # Check for timeout
                if timeout and (time.time() - start_time) > timeout:
                    process.kill()
                    raise subprocess.TimeoutExpired(command, timeout)

            # Wait for process to complete
            process.wait(timeout=timeout if timeout else None)
            exit_code = process.returncode

            if logger:
                logger.info("")
                logger.info(f"=== Exit Code: {exit_code} ===")

        else:
            # Non-streaming mode: Use subprocess.run()
            # Some CLIs (pi) hang on /dev/null stdin in print mode and need a clean EOF.
            stdin_kwargs = (
                {"input": ""}
                if getattr(adapter, "needs_empty_stdin", False)
                else {"stdin": subprocess.DEVNULL}
            )
            result = subprocess.run(
                command,
                cwd=working_dir,
                env=merged_env,
                timeout=timeout,
                capture_output=True,
                text=True,
                **stdin_kwargs,
            )
            exit_code = result.returncode

            # Log output if in debug mode
            if logger:
                logger.info(f"=== Exit Code: {exit_code} ===")
                logger.info("")
                if result.stdout:
                    logger.info("=== STDOUT ===")
                    logger.info(result.stdout)
                    logger.info("")
                if result.stderr:
                    logger.info("=== STDERR ===")
                    logger.info(result.stderr)
                    logger.info("")

        # Clean up logger handlers
        if logger:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
            if log_file:
                print(f"  Output logged to: {log_file}", file=sys.stderr)

    except subprocess.TimeoutExpired:
        # Enhanced error message with helpful suggestions
        timeout_minutes = timeout / 60
        error_msg = (
            f"Task timeout exceeded\n\n"
            f"Context: Task '{task_name}' exceeded {timeout} seconds ({timeout_minutes:.1f} minutes) timeout\n"
            f"Expected: Task to complete within timeout period\n"
            f"Found: Task still running after timeout\n"
            f"Suggestion: Consider one of the following:\n"
            f"  1. Increase timeout in cli-agent-config:\n"
            f"     cli-agent-config:\n"
            f"       timeout: {timeout * 2}  # Double the current timeout\n"
            f"  2. Break the task into smaller subtasks\n"
            f"  3. Check if the CLI agent is stuck waiting for input\n"
            f"  4. Review task complexity and optimize the prompt"
        )
        print(error_msg, file=sys.stderr)

        # Handle timeout according to error strategy
        if error_strategy == "fail":
            emit_event(
                workflow_config,
                "task_failed",
                node_id=event_node_id,
                task_name=task_name,
                attempt=_attempt,
                status="failed",
                exit_code=-1,
                message=error_msg,
            )
            raise ExecutionError(error_msg)
        elif error_strategy == "continue":
            return {
                "task_name": task_name,
                "status": "failed",
                "exit_code": -1,
                "error_message": error_msg,
            }
        else:  # skip
            return {"task_name": task_name, "status": "skipped", "exit_code": -1}

    except Exception as e:
        error_msg = f"Task '{task_name}' failed with exception: {str(e)}"
        print(error_msg, file=sys.stderr)

        if error_strategy == "fail":
            emit_event(
                workflow_config,
                "task_failed",
                node_id=event_node_id,
                task_name=task_name,
                attempt=_attempt,
                status="failed",
                exit_code=-1,
                message=error_msg,
            )
            raise ExecutionError(error_msg)
        elif error_strategy == "continue":
            return {
                "task_name": task_name,
                "status": "failed",
                "exit_code": -1,
                "error_message": error_msg,
            }
        else:  # skip
            return {"task_name": task_name, "status": "skipped", "exit_code": -1}

    # 9. Handle errors according to error strategy
    if exit_code == 0:
        # Success - now check validators if present
        validators_config = task_def.get("validate", [])

        if validators_config:
            emit_event(
                workflow_config,
                "validators_started",
                node_id=event_node_id,
                task_name=task_name,
                status="running",
                total=len(validators_config),
            )
            if not dry_run:
                print(
                    f"Running {len(validators_config)} validator(s) for task '{task_name}'...",
                    file=sys.stderr,
                )

                from .task_validators import (
                    run_validators,
                    ValidationError as ValidatorError,
                )

                try:
                    validation_result = run_validators(validators_config, resolved_vars)

                    if validation_result["all_passed"]:
                        print(
                            f"✅ All validators passed for task '{task_name}'",
                            file=sys.stderr,
                        )
                        emit_event(
                            workflow_config,
                            "validators_completed",
                            node_id=event_node_id,
                            task_name=task_name,
                            status="success",
                            payload=validation_result,
                        )
                        emit_event(
                            workflow_config,
                            "task_completed",
                            node_id=event_node_id,
                            task_name=task_name,
                            attempt=_attempt,
                            status="success",
                            exit_code=0,
                        )
                        return {
                            "task_name": task_name,
                            "status": "success",
                            "exit_code": 0,
                            "validation": validation_result,
                        }
                    else:
                        # Validation failed
                        error_msg = (
                            f"Task '{task_name}' completed but validation failed: "
                            f"{validation_result['failed_count']}/{validation_result['total_count']} validators failed"
                        )
                        print(error_msg, file=sys.stderr)

                        # Check if we should retry
                        if on_validation_failure == "retry" and _attempt < max_attempts:
                            emit_event(
                                workflow_config,
                                "task_retrying",
                                node_id=event_node_id,
                                task_name=task_name,
                                attempt=_attempt,
                                status="retrying",
                                message=error_msg,
                            )
                            print(
                                f"⟳ Validation failed, retrying (attempt {_attempt}/{max_attempts})...",
                                file=sys.stderr,
                            )
                            # Recursively retry the task
                            return execute_single_task(
                                task_name,
                                task_def,
                                resolved_vars,
                                adapter,
                                workflow_config,
                                dry_run,
                                debug,
                                _attempt=_attempt + 1,
                            )

                        # No retry or max attempts exhausted
                        if _attempt > 1:
                            error_msg += f" (failed after {_attempt} attempts)"

                        # Handle validation failure per on-validation-failure strategy
                        if on_validation_failure == "fail":
                            emit_event(
                                workflow_config,
                                "task_failed",
                                node_id=event_node_id,
                                task_name=task_name,
                                attempt=_attempt,
                                status="failed",
                                exit_code=0,
                                message=error_msg,
                                payload={"validation": validation_result},
                            )
                            raise ExecutionError(error_msg)
                        elif on_validation_failure == "skip":
                            return {
                                "task_name": task_name,
                                "status": "skipped",
                                "exit_code": 0,
                                "validation": validation_result,
                                "attempts": _attempt,
                            }
                        else:  # on_validation_failure == "retry" but exhausted, fall back to error_strategy
                            if error_strategy == "fail":
                                raise ExecutionError(error_msg)
                            elif error_strategy == "continue":
                                return {
                                    "task_name": task_name,
                                    "status": "failed",
                                    "exit_code": 0,  # Task succeeded, validation failed
                                    "error_message": error_msg,
                                    "validation": validation_result,
                                    "attempts": _attempt,
                                }
                            else:  # skip
                                return {
                                    "task_name": task_name,
                                    "status": "skipped",
                                    "exit_code": 0,
                                    "validation": validation_result,
                                    "attempts": _attempt,
                                }

                except ValidatorError as e:
                    error_msg = f"Task '{task_name}' validation error: {e}"
                    print(error_msg, file=sys.stderr)

                    if error_strategy == "fail":
                        raise ExecutionError(error_msg)
                    elif error_strategy == "continue":
                        return {
                            "task_name": task_name,
                            "status": "failed",
                            "exit_code": 0,
                            "error_message": error_msg,
                        }
                    else:  # skip
                        return {
                            "task_name": task_name,
                            "status": "skipped",
                            "exit_code": 0,
                        }

        # No validators or dry run - return success
        emit_event(
            workflow_config,
            "task_completed",
            node_id=event_node_id,
            task_name=task_name,
            attempt=_attempt,
            status="success",
            exit_code=0,
        )
        return {"task_name": task_name, "status": "success", "exit_code": 0}
    else:
        # Non-zero exit code = failure
        error_msg = f"Task '{task_name}' failed with exit code {exit_code}"
        print(error_msg, file=sys.stderr)

        if error_strategy == "fail":
            emit_event(
                workflow_config,
                "task_failed",
                node_id=event_node_id,
                task_name=task_name,
                attempt=_attempt,
                status="failed",
                exit_code=exit_code,
                message=error_msg,
            )
            raise ExecutionError(error_msg)
        elif error_strategy == "continue":
            return {
                "task_name": task_name,
                "status": "failed",
                "exit_code": exit_code,
                "error_message": error_msg,
            }
        else:  # skip
            return {"task_name": task_name, "status": "skipped", "exit_code": exit_code}


class ExecutionError(Exception):
    """Raised when task execution fails."""

    pass
