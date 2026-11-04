"""
Loop iteration and checkpoint management.

Implements three loop types:
1. TodoListLoop - Iterates over markdown checkboxes
2. CSVLoop - Iterates over CSV rows with filtering
3. GlobLoop - Iterates over files matching glob pattern

Loop variables:
- {{loop.index}} - Current iteration index (0-based)
- {{loop.total}} - Total number of items
- {{loop.item.*}} - Loop type-specific item properties

Parallel execution:
- workers: Number of items to execute in parallel
- directory-pool: List of directories to round-robin assign to workers
- git-worktrees: Auto-create git worktrees for each worker

Worker variables (when workers > 1):
- {{loop.worker.id}} - Worker ID (0 to N-1)
- {{loop.worker.directory}} - Assigned directory or worktree path

Checkpoint system:
- Optional checkpoint-file for resumability
- JSON format: {"type": "...", "current_index": N, "completed_items": [...]}
- Allows workflow restart from last successful iteration

Reference: spec/YAML_SPEC.md lines 513-543 (todo-list), 545-575 (csv), 577-604 (glob).
"""

from .events import emit_event


def _emit_item_event(workflow_config, event, *, loop_type, status, index, total, item_id):
    """Emit a per-item loop callback for the web trace (no-op without an event sink)."""
    config = workflow_config or {}
    emit_event(
        config,
        event,
        node_id=config.get("_current_node_id", "loop"),
        status=status,
        loop_type=loop_type,
        index=index,
        total=total,
        item_id=item_id,
    )


class BaseLoop:
    """Base class for all loop types."""

    def __init__(self, loop_config, variables):
        """
        Initialize loop with configuration.

        Args:
            loop_config: Loop configuration dict
            variables: Resolved variables for interpolation
        """
        pass

    def iterate(self):
        """
        Generate loop items.

        Yields:
            tuple: (index, item_dict) for each iteration
        """
        pass


class TodoListLoop(BaseLoop):
    """
    Iterate over markdown checkbox items.

    Variables:
    - {{loop.item.text}} - Checkbox text content
    - {{loop.item.number}} - Item number (1-based)
    - {{loop.item.line}} - Line number in file
    """

    def execute(
        self, task_def, loop_config, resolved_vars, adapter, workflow_config, dry_run=False
    ):
        """
        Execute task for each pending todo item.

        Args:
            task_def: Task definition dict with 'prompt', optional 'include', 'on-error'
            loop_config: Loop configuration with 'source', optional 'mark-in-progress',
                        'mark-complete', 'checkpoint-file', 'resume'
            resolved_vars: Resolved variables for interpolation
            adapter: CLI adapter instance
            workflow_config: Workflow configuration
            dry_run: If True, parse and display loop info without executing (default: False)

        Returns:
            dict: Execution results for all iterations

        Raises:
            ExecutionError: If source file not found or permission error
        """
        import os
        import sys

        from .executor import ExecutionError, execute_single_task
        from .utils import interpolate_variables

        # Interpolate source path (may contain template variables)
        source_path = loop_config.get("source", "")
        if not source_path:
            raise ExecutionError("TodoListLoop requires 'source' field")

        source_path = interpolate_variables(source_path, resolved_vars)
        source_path = os.path.abspath(os.path.expanduser(source_path))

        # Check if file exists
        if not os.path.exists(source_path):
            if dry_run:
                print(
                    f"[DRY RUN] Warning: Todo list file not found: {source_path}", file=sys.stderr
                )
                print(
                    "[DRY RUN] Loop would fail at runtime if file is not created by previous task",
                    file=sys.stderr,
                )
                return {"status": "success", "iterations": 0, "completed": [], "failed": []}
            raise ExecutionError(f"Todo list file not found: {source_path}")

        # Parse markdown file and extract pending todos
        try:
            pending_todos = self._parse_todo_file(source_path)
        except FileNotFoundError:
            if dry_run:
                print(
                    f"[DRY RUN] Warning: Todo list file not found: {source_path}", file=sys.stderr
                )
                print("[DRY RUN] Loop would fail at runtime", file=sys.stderr)
                return {"status": "success", "iterations": 0, "completed": [], "failed": []}
            raise

        # Handle empty todo list
        if not pending_todos:
            print(f"No pending todo items in {source_path}", file=sys.stderr)
            return {"status": "success", "iterations": 0, "completed": [], "failed": []}

        # Dry run mode: print loop info and return
        if dry_run:
            print("[DRY RUN] Todo-list loop:", file=sys.stderr)
            print(f"  Source: {source_path}", file=sys.stderr)
            print(f"  Pending items: {len(pending_todos)}", file=sys.stderr)
            print(
                f"  Mark in progress: {loop_config.get('mark-in-progress', False)}", file=sys.stderr
            )
            print(f"  Mark complete: {loop_config.get('mark-complete', False)}", file=sys.stderr)
            if loop_config.get("checkpoint-file"):
                print(f"  Checkpoint file: {loop_config.get('checkpoint-file')}", file=sys.stderr)
            print("  Items to process:", file=sys.stderr)
            for idx, item in enumerate(pending_todos, 1):
                print(f"    {idx}. {item['text']}", file=sys.stderr)
            return {
                "status": "success",
                "iterations": len(pending_todos),
                "completed": [],
                "failed": [],
            }

        # Load checkpoint if resume is enabled
        checkpoint_file = loop_config.get("checkpoint-file")
        if checkpoint_file:
            # Checkpoint paths may contain template variables (e.g. {{output-dir}}/ckpt.json)
            checkpoint_file = interpolate_variables(str(checkpoint_file), resolved_vars)
            checkpoint_file = os.path.abspath(os.path.expanduser(checkpoint_file))
        resume = loop_config.get("resume", False)
        checkpoint_manager = CheckpointManager()
        checkpoint = None

        if resume and checkpoint_file:
            checkpoint = checkpoint_manager.load_checkpoint(checkpoint_file)
            if checkpoint:
                print(f"Resuming from checkpoint: {checkpoint_file}", file=sys.stderr)

        # Initialize tracking
        # Note: start_index is always 0 because pending_todos is already filtered
        # to exclude completed items. The checkpoint tracks what's been done,
        # but we iterate from start of remaining pending items.
        start_index = 0
        completed_items = []
        failed_items = []

        if checkpoint:
            # Load previous state, but start_index stays 0 (iterate remaining pending items)
            completed_items = checkpoint.get("completed_items", [])
            failed_items = checkpoint.get("failed_items", [])

        # Get configuration options
        mark_in_progress = loop_config.get("mark-in-progress", False)
        mark_complete = loop_config.get("mark-complete", False)

        # Execute task for each pending todo
        total = len(pending_todos)
        results = {
            "status": "success",
            "iterations": 0,
            "completed": completed_items.copy(),
            "failed": failed_items.copy(),
        }

        # Get verbose flag from workflow_config
        verbose = workflow_config.get("_verbose", False)

        for index in range(start_index, total):
            todo_item = pending_todos[index]
            _emit_item_event(
                workflow_config,
                "loop_item_started",
                loop_type="todo-list",
                status="running",
                index=index,
                total=total,
                item_id=todo_item["text"],
            )
            remaining = total - index

            # Mark as in-progress if requested (skip in dry-run)
            if mark_in_progress and not dry_run:
                self._update_checkbox_status(source_path, todo_item["line"], "[-]")

            # Build loop variables
            loop_vars = {
                "loop": {
                    "index": index,
                    "total": total,
                    "remaining": remaining,
                    "item": {
                        "text": todo_item["text"],
                        "number": todo_item["number"],
                        "line": todo_item["line"],
                    },
                }
            }

            # Merge with resolved vars
            iteration_vars = {**resolved_vars, **loop_vars}

            # Print loop item details in verbose mode
            if verbose:
                print(f"\n=== Todo-list Loop Iteration {index + 1}/{total} ===", file=sys.stderr)
                print(f"  Item number: {todo_item['number']}", file=sys.stderr)
                print(f"  Line: {todo_item['line']}", file=sys.stderr)
                print(f"  Text: {todo_item['text']}", file=sys.stderr)
                print(f"  Remaining: {remaining}", file=sys.stderr)
                print("", file=sys.stderr)

            # Get retry configuration
            retry_config = loop_config.get("retry", {})
            max_attempts = retry_config.get("max-attempts", 1)
            on_failure = retry_config.get("on-failure", None)

            # Validate retry configuration
            if max_attempts < 1:
                raise ExecutionError("retry.max-attempts must be >= 1")
            if on_failure and on_failure not in ["skip", "retry", "abort"]:
                raise ExecutionError(
                    f"retry.on-failure must be 'skip', 'retry', or 'abort', got: {on_failure}"
                )

            # Execute task with retry logic
            task_succeeded = False
            task_failed = False
            last_error = None

            for attempt in range(1, max_attempts + 1):
                # Handle on-failure: skip (only try once)
                if on_failure == "skip" and attempt > 1:
                    break

                try:
                    if attempt > 1:
                        print(
                            f"Retrying todo item '{todo_item['text']}' (attempt {attempt}/{max_attempts})",
                            file=sys.stderr,
                        )

                    # Get debug flag from workflow_config
                    debug = workflow_config.get("_debug", False)

                    result = execute_single_task(
                        f"todo-{todo_item['number']}",
                        task_def,
                        iteration_vars,
                        adapter,
                        workflow_config,
                        dry_run=dry_run,
                        debug=debug,
                    )

                    results["iterations"] += 1

                    if result["status"] == "success":
                        task_succeeded = True
                        break
                    elif result["status"] == "failed":
                        # Task returned failed status (on-error: continue/skip)
                        last_error = "Task returned failed status"
                        # Retry for 'retry' or 'abort' modes
                        if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                            continue  # Retry
                        else:
                            task_failed = True
                            break
                    elif result["status"] == "skipped":
                        # Task was skipped (counts as success for retry purposes)
                        task_succeeded = True
                        break

                except ExecutionError as e:
                    # Task failed with on-error: fail strategy or execution error
                    last_error = e
                    # Retry for 'retry' or 'abort' modes
                    if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                        print(f"Task failed: {e}. Retrying...", file=sys.stderr)
                        continue  # Retry
                    else:
                        task_failed = True
                        break

            # Handle final outcome after all retry attempts
            if task_succeeded:
                # Mark as complete if requested (skip in dry-run)
                if mark_complete and not dry_run:
                    self._update_checkbox_status(source_path, todo_item["line"], "[x]")

                _emit_item_event(
                    workflow_config,
                    "loop_item_completed",
                    loop_type="todo-list",
                    status="success",
                    index=index,
                    total=total,
                    item_id=todo_item["text"],
                )
                completed_items.append(todo_item["text"])
                results["completed"].append(todo_item["text"])

            elif task_failed:
                _emit_item_event(
                    workflow_config,
                    "loop_item_failed",
                    loop_type="todo-list",
                    status="failed",
                    index=index,
                    total=total,
                    item_id=todo_item["text"],
                )
                failed_items.append(todo_item["text"])
                results["failed"].append(todo_item["text"])
                results["status"] = "partial"

                # Handle on-failure: abort
                if on_failure == "abort":
                    print(
                        f"Task failed after {max_attempts} attempt(s). Aborting loop (on-failure: abort)",
                        file=sys.stderr,
                    )
                    results["status"] = "failed"

                    # Save checkpoint before raising (skip in dry-run)
                    if checkpoint_file and not dry_run:
                        checkpoint_data = {
                            "type": "todo-list",
                            "current_index": index + 1,
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                        }
                        checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

                    # Re-raise if it was an ExecutionError, otherwise raise new one
                    if isinstance(last_error, ExecutionError):
                        raise last_error
                    else:
                        raise ExecutionError(
                            f"Task failed after {max_attempts} attempt(s): {last_error}"
                        )

                # on-failure: skip or retry (retries exhausted) or None (default: raise)
                if on_failure == "skip":
                    print("Task failed. Skipping to next item (on-failure: skip)", file=sys.stderr)
                elif on_failure == "retry":
                    print(
                        f"Task failed after {max_attempts} attempt(s). Continuing to next item",
                        file=sys.stderr,
                    )
                else:
                    # on_failure is None (default behavior: raise ExecutionError)
                    results["status"] = "failed"

                    # Save checkpoint before raising (skip in dry-run)
                    if checkpoint_file and not dry_run:
                        checkpoint_data = {
                            "type": "todo-list",
                            "current_index": index + 1,
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                        }
                        checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

                    # Re-raise if it was an ExecutionError, otherwise raise new one
                    if isinstance(last_error, ExecutionError):
                        raise last_error
                    else:
                        raise ExecutionError(f"Task failed: {last_error}")

            # Save checkpoint after each iteration (skip in dry-run)
            if checkpoint_file and not dry_run:
                checkpoint_data = {
                    "type": "todo-list",
                    "current_index": index + 1,
                    "completed_items": completed_items,
                    "failed_items": failed_items,
                }
                checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

        return results

    def _parse_todo_file(self, file_path):
        """
        Parse markdown file and extract pending todo items.

        Args:
            file_path: Path to markdown file

        Returns:
            list: List of dicts with keys 'text', 'number', 'line', 'status'
                 Only returns pending items (status=' ')

        Format:
            - [ ] Pending item
            - [-] In-progress item
            - [x] Complete item
        """
        import re

        # Regex to match markdown checkboxes
        checkbox_pattern = r"^\s*-\s*\[([ x-])\]\s*(.+)$"

        pending_todos = []
        item_number = 0

        with open(file_path, "r") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.rstrip("\n\r")
                match = re.match(checkbox_pattern, line)

                if match:
                    status = match.group(1)
                    text = match.group(2).strip()
                    item_number += 1

                    # Only include pending items
                    if status == " ":
                        pending_todos.append(
                            {
                                "text": text,
                                "number": item_number,
                                "line": line_num,
                                "status": status,
                            }
                        )

        return pending_todos

    def _update_checkbox_status(self, file_path, line_number, new_status):
        """
        Update checkbox status at specific line atomically.

        Args:
            file_path: Path to markdown file
            line_number: Line number to update (1-based)
            new_status: New status string ('[x]', '[-]', or '[ ]')

        Uses temp file + os.replace() for atomic updates.
        """
        import os
        import re
        import tempfile

        # Read all lines
        with open(file_path, "r") as f:
            lines = f.readlines()

        # Update the target line
        if 1 <= line_number <= len(lines):
            line = lines[line_number - 1]
            # Replace checkbox status (first occurrence of [ ], [-], or [x])
            updated_line = re.sub(r"\[([ x-])\]", new_status, line, count=1)
            lines[line_number - 1] = updated_line

        # Write to temp file
        file_dir = os.path.dirname(file_path)
        fd, temp_path = tempfile.mkstemp(dir=file_dir, prefix=".todo-", suffix=".tmp")

        try:
            with os.fdopen(fd, "w") as f:
                f.writelines(lines)

            # Atomic replace
            os.replace(temp_path, file_path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise


class CSVLoop(BaseLoop):
    """
    Iterate over CSV rows.

    Variables:
    - {{loop.item.column_name}} - Value from named column
    - {{loop.item.row}} - Row number (1-based)
    """

    def execute(
        self, task_def, loop_config, resolved_vars, adapter, workflow_config, dry_run=False
    ):
        """
        Execute task for each CSV row.

        Args:
            task_def: Task definition dict with 'prompt', optional 'include', 'on-error'
            loop_config: Loop configuration with 'source', optional 'skip-header',
                        'columns', 'filter', 'checkpoint-file', 'resume'
            resolved_vars: Resolved variables for interpolation
            adapter: CLI adapter instance
            workflow_config: Workflow configuration
            dry_run: If True, parse and display loop info without executing (default: False)

        Returns:
            dict: Execution results for all iterations

        Raises:
            ExecutionError: If source file not found or CSV parsing error
        """
        import os
        import sys

        from .executor import ExecutionError, execute_single_task
        from .utils import interpolate_variables

        # Interpolate source path (may contain template variables)
        source_path = loop_config.get("source", "")
        if not source_path:
            raise ExecutionError("CSVLoop requires 'source' field")

        source_path = interpolate_variables(source_path, resolved_vars)
        source_path = os.path.abspath(os.path.expanduser(source_path))

        # Check if file exists
        if not os.path.exists(source_path):
            if dry_run:
                print(f"[DRY RUN] Warning: CSV file not found: {source_path}", file=sys.stderr)
                print(
                    "[DRY RUN] Loop would fail at runtime if file is not created by previous task",
                    file=sys.stderr,
                )
                return {"status": "success", "iterations": 0, "completed": [], "failed": []}
            raise ExecutionError(f"CSV file not found: {source_path}")

        # Parse CSV file
        try:
            csv_rows = self._parse_csv_file(source_path, loop_config)
        except FileNotFoundError:
            if dry_run:
                print(f"[DRY RUN] Warning: CSV file not found: {source_path}", file=sys.stderr)
                print("[DRY RUN] Loop would fail at runtime", file=sys.stderr)
                return {"status": "success", "iterations": 0, "completed": [], "failed": []}
            raise
        except Exception as e:
            raise ExecutionError(f"Error parsing CSV file: {e}")

        # Handle empty CSV
        if not csv_rows:
            print(f"No rows to process in {source_path}", file=sys.stderr)
            return {"status": "success", "iterations": 0, "completed": [], "failed": []}

        # Check for parallel execution
        workers = loop_config.get("workers", 1)
        if workers > 1:
            # Use parallel execution
            if dry_run:
                print("[DRY RUN] CSV loop (parallel):", file=sys.stderr)
                print(f"  Source: {source_path}", file=sys.stderr)
                print(f"  Workers: {workers}", file=sys.stderr)
                print(f"  Rows to process: {len(csv_rows)}", file=sys.stderr)
                if loop_config.get("directory-pool"):
                    print(f"  Directory pool: {loop_config.get('directory-pool')}", file=sys.stderr)
                if loop_config.get("git-worktrees"):
                    git_config = loop_config.get("git-worktrees")
                    print(f"  Git worktrees enabled: {git_config.get('enabled')}", file=sys.stderr)
                    print(f"  Base path: {git_config.get('base')}", file=sys.stderr)
                    print(f"  Branch field: {git_config.get('branch-field')}", file=sys.stderr)
                return {"status": "success", "iterations": len(csv_rows), "completed": [], "failed": []}

            return self._execute_parallel(
                task_def, loop_config, csv_rows, resolved_vars, adapter, workflow_config, dry_run=dry_run
            )

        # Sequential execution (original behavior)
        # Dry run mode: print loop info and return
        if dry_run:
            print("[DRY RUN] CSV loop:", file=sys.stderr)
            print(f"  Source: {source_path}", file=sys.stderr)
            print(f"  Rows to process: {len(csv_rows)}", file=sys.stderr)
            if loop_config.get("skip-header"):
                print("  Skip header: True", file=sys.stderr)
            if loop_config.get("columns"):
                print(f"  Column mapping: {loop_config.get('columns')}", file=sys.stderr)
            if loop_config.get("filter"):
                filter_config = loop_config.get("filter")
                print(
                    f"  Filter: {filter_config.get('column')} = {filter_config.get('value')}",
                    file=sys.stderr,
                )
            if loop_config.get("checkpoint-file"):
                print(f"  Checkpoint file: {loop_config.get('checkpoint-file')}", file=sys.stderr)
            print("  Rows to process:", file=sys.stderr)
            for idx, row in enumerate(csv_rows[:10], 1):  # Show first 10
                # Show first few columns
                preview = ", ".join([f"{k}={v}" for k, v in list(row.items())[:3]])
                print(f"    {idx}. Row {row['_row_number']}: {preview}", file=sys.stderr)
            if len(csv_rows) > 10:
                print(f"    ... and {len(csv_rows) - 10} more rows", file=sys.stderr)
            return {"status": "success", "iterations": len(csv_rows), "completed": [], "failed": []}

        # Load checkpoint if resume is enabled
        checkpoint_file = loop_config.get("checkpoint-file")
        if checkpoint_file:
            # Checkpoint paths may contain template variables (e.g. {{output-dir}}/ckpt.json)
            checkpoint_file = interpolate_variables(str(checkpoint_file), resolved_vars)
            checkpoint_file = os.path.abspath(os.path.expanduser(checkpoint_file))
        resume = loop_config.get("resume", False)
        checkpoint_manager = CheckpointManager()
        checkpoint = None

        if resume and checkpoint_file:
            checkpoint = checkpoint_manager.load_checkpoint(checkpoint_file)
            if checkpoint:
                print(f"Resuming from checkpoint: {checkpoint_file}", file=sys.stderr)

        # Initialize tracking
        start_index = 0
        completed_items = []
        failed_items = []

        if checkpoint:
            # Resume from checkpoint
            start_index = checkpoint.get("current_index", 0)
            completed_items = checkpoint.get("completed_items", [])
            failed_items = checkpoint.get("failed_items", [])

        # Execute task for each CSV row
        total = len(csv_rows)
        results = {
            "status": "success",
            "iterations": 0,
            "completed": completed_items.copy(),
            "failed": failed_items.copy(),
        }

        # Get verbose flag from workflow_config
        verbose = workflow_config.get("_verbose", False)

        for index in range(start_index, total):
            csv_row = csv_rows[index]
            _emit_item_event(
                workflow_config,
                "loop_item_started",
                loop_type="csv",
                status="running",
                index=index,
                total=total,
                item_id=f"row-{csv_row.get('_row_number')}",
            )
            remaining = total - index

            # Build loop variables with dynamic column access
            row_number = csv_row.pop("_row_number")  # Remove internal field
            loop_item = {**csv_row, "row": row_number}

            loop_vars = {
                "loop": {"index": index, "total": total, "remaining": remaining, "item": loop_item}
            }

            # Merge with resolved vars
            iteration_vars = {**resolved_vars, **loop_vars}

            # Print loop item details in verbose mode
            if verbose:
                print(f"\n=== CSV Loop Iteration {index + 1}/{total} ===", file=sys.stderr)
                print(f"  Row number: {row_number}", file=sys.stderr)
                for key, value in csv_row.items():
                    print(f"  {key}: {value}", file=sys.stderr)
                print(f"  Remaining: {remaining}", file=sys.stderr)
                print("", file=sys.stderr)

            # Get retry configuration
            retry_config = loop_config.get("retry", {})
            max_attempts = retry_config.get("max-attempts", 1)
            on_failure = retry_config.get("on-failure", None)

            # Validate retry configuration
            if max_attempts < 1:
                raise ExecutionError("retry.max-attempts must be >= 1")
            if on_failure and on_failure not in ["skip", "retry", "abort"]:
                raise ExecutionError(
                    f"retry.on-failure must be 'skip', 'retry', or 'abort', got: {on_failure}"
                )

            # Create row identifier for tracking
            row_id = f"row-{row_number}"

            # Execute task with retry logic
            task_succeeded = False
            task_failed = False
            last_error = None

            for attempt in range(1, max_attempts + 1):
                # Handle on-failure: skip (only try once)
                if on_failure == "skip" and attempt > 1:
                    break

                try:
                    if attempt > 1:
                        print(
                            f"Retrying row {row_number} (attempt {attempt}/{max_attempts})",
                            file=sys.stderr,
                        )

                    # Get debug flag from workflow_config
                    debug = workflow_config.get("_debug", False)

                    result = execute_single_task(
                        f"csv-row-{row_number}",
                        task_def,
                        iteration_vars,
                        adapter,
                        workflow_config,
                        dry_run=dry_run,
                        debug=debug,
                    )

                    results["iterations"] += 1

                    if result["status"] == "success":
                        task_succeeded = True
                        break
                    elif result["status"] == "failed":
                        # Task returned failed status (on-error: continue/skip)
                        last_error = "Task returned failed status"
                        # Retry for 'retry' or 'abort' modes
                        if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                            continue  # Retry
                        else:
                            task_failed = True
                            break
                    elif result["status"] == "skipped":
                        # Task was skipped (counts as success for retry purposes)
                        task_succeeded = True
                        break

                except ExecutionError as e:
                    # Task failed with on-error: fail strategy or execution error
                    last_error = e
                    # Retry for 'retry' or 'abort' modes
                    if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                        print(f"Task failed: {e}. Retrying...", file=sys.stderr)
                        continue  # Retry
                    else:
                        task_failed = True
                        break

            # Handle final outcome after all retry attempts
            if task_succeeded:
                _emit_item_event(
                    workflow_config,
                    "loop_item_completed",
                    loop_type="csv",
                    status="success",
                    index=index,
                    total=total,
                    item_id=row_id,
                )
                completed_items.append(row_id)
                results["completed"].append(row_id)

            elif task_failed:
                _emit_item_event(
                    workflow_config,
                    "loop_item_failed",
                    loop_type="csv",
                    status="failed",
                    index=index,
                    total=total,
                    item_id=row_id,
                )
                failed_items.append(row_id)
                results["failed"].append(row_id)
                results["status"] = "partial"

                # Handle on-failure: abort
                if on_failure == "abort":
                    print(
                        f"Task failed after {max_attempts} attempt(s). Aborting loop (on-failure: abort)",
                        file=sys.stderr,
                    )
                    results["status"] = "failed"

                    # Save checkpoint before raising (skip in dry-run)
                    if checkpoint_file and not dry_run:
                        checkpoint_data = {
                            "type": "csv",
                            "current_index": index + 1,
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                        }
                        checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

                    # Re-raise if it was an ExecutionError, otherwise raise new one
                    if isinstance(last_error, ExecutionError):
                        raise last_error
                    else:
                        raise ExecutionError(
                            f"Task failed after {max_attempts} attempt(s): {last_error}"
                        )

                # on-failure: skip or retry (retries exhausted) or None (default: raise)
                if on_failure == "skip":
                    print("Task failed. Skipping to next item (on-failure: skip)", file=sys.stderr)
                elif on_failure == "retry":
                    print(
                        f"Task failed after {max_attempts} attempt(s). Continuing to next item",
                        file=sys.stderr,
                    )
                else:
                    # on_failure is None (default behavior: raise ExecutionError)
                    results["status"] = "failed"

                    # Save checkpoint before raising (skip in dry-run)
                    if checkpoint_file and not dry_run:
                        checkpoint_data = {
                            "type": "csv",
                            "current_index": index + 1,
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                        }
                        checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

                    # Re-raise if it was an ExecutionError, otherwise raise new one
                    if isinstance(last_error, ExecutionError):
                        raise last_error
                    else:
                        raise ExecutionError(f"Task failed: {last_error}")

            # Save checkpoint after each iteration (skip in dry-run)
            if checkpoint_file and not dry_run:
                checkpoint_data = {
                    "type": "csv",
                    "current_index": index + 1,
                    "completed_items": completed_items,
                    "failed_items": failed_items,
                }
                checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

        return results

    def _execute_parallel(
        self,
        task_def,
        loop_config,
        csv_rows,
        resolved_vars,
        adapter,
        workflow_config,
        dry_run=False,
    ):
        """
        Execute CSV rows in parallel using ThreadPoolExecutor.

        Args:
            task_def: Task definition with prompt
            loop_config: Loop configuration with workers, optional directory-pool or git-worktrees
            csv_rows: Parsed CSV rows to process
            resolved_vars: Resolved variables
            adapter: CLI adapter instance
            workflow_config: Workflow configuration
            dry_run: If True, don't execute tasks

        Returns:
            dict: Execution results with status, iterations, completed, failed

        Raises:
            ExecutionError: If invalid configuration or git worktree operations fail
        """

        from .executor import ExecutionError

        directory_pool = loop_config.get("directory-pool")
        git_worktrees_config = loop_config.get("git-worktrees")

        # Validate configuration
        if directory_pool and git_worktrees_config:
            raise ExecutionError("Cannot use both directory-pool and git-worktrees")

        # Validate directory pool if specified (check for empty list)
        if directory_pool is not None and len(directory_pool) == 0:
            raise ExecutionError("directory-pool cannot be empty when specified")

        # Determine which parallel execution mode to use
        if git_worktrees_config:
            return self._execute_with_worktrees(
                task_def,
                loop_config,
                csv_rows,
                resolved_vars,
                adapter,
                workflow_config,
                dry_run=dry_run,
            )
        elif directory_pool:
            return self._execute_with_directory_pool(
                task_def,
                loop_config,
                csv_rows,
                resolved_vars,
                adapter,
                workflow_config,
                dry_run=dry_run,
            )
        else:
            # Simple parallel execution without worker directories
            return self._execute_with_simple_parallel(
                task_def,
                loop_config,
                csv_rows,
                resolved_vars,
                adapter,
                workflow_config,
                dry_run=dry_run,
            )

    def _execute_with_simple_parallel(
        self,
        task_def,
        loop_config,
        csv_rows,
        resolved_vars,
        adapter,
        workflow_config,
        dry_run=False,
    ):
        """Execute CSV rows in parallel without worker directories."""
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .executor import ExecutionError, execute_single_task

        workers = loop_config.get("workers", 1)
        total = len(csv_rows)
        results = {"status": "success", "iterations": 0, "completed": [], "failed": []}

        # Get verbose flag
        verbose = workflow_config.get("_verbose", False)
        debug = workflow_config.get("_debug", False)

        # Get retry configuration
        retry_config = loop_config.get("retry", {})
        max_attempts = retry_config.get("max-attempts", 1)
        on_failure = retry_config.get("on-failure", None)

        # Validate retry configuration
        if max_attempts < 1:
            raise ExecutionError("retry.max-attempts must be >= 1")
        if on_failure and on_failure not in ["skip", "retry", "abort"]:
            raise ExecutionError(
                f"retry.on-failure must be 'skip', 'retry', or 'abort', got: {on_failure}"
            )

        def process_row(index, csv_row):
            """Process a single CSV row (executed in worker thread)."""
            _emit_item_event(
                workflow_config,
                "loop_item_started",
                loop_type="csv",
                status="running",
                index=index,
                total=total,
                item_id=f"row-{csv_row.get('_row_number')}",
            )
            remaining = total - index
            row_number = csv_row.pop("_row_number")
            loop_item = {**csv_row, "row": row_number}

            # Build loop variables
            loop_vars = {
                "loop": {"index": index, "total": total, "remaining": remaining, "item": loop_item}
            }

            # Merge with resolved vars
            iteration_vars = {**resolved_vars, **loop_vars}

            # Print loop item details in verbose mode
            if verbose:
                print(f"\n=== CSV Loop Iteration {index + 1}/{total} (Parallel) ===", file=sys.stderr)
                print(f"  Row number: {row_number}", file=sys.stderr)
                for key, value in csv_row.items():
                    print(f"  {key}: {value}", file=sys.stderr)
                print(f"  Remaining: {remaining}", file=sys.stderr)
                print("", file=sys.stderr)

            # Execute task with retry logic
            task_succeeded = False
            task_failed = False
            last_error = None
            row_id = f"row-{row_number}"

            for attempt in range(1, max_attempts + 1):
                if on_failure == "skip" and attempt > 1:
                    break

                try:
                    if attempt > 1:
                        print(
                            f"Retrying row {row_number} (attempt {attempt}/{max_attempts})",
                            file=sys.stderr,
                        )

                    result = execute_single_task(
                        f"csv-row-{row_number}",
                        task_def,
                        iteration_vars,
                        adapter,
                        workflow_config,
                        dry_run=dry_run,
                        debug=debug,
                    )

                    if result["status"] == "success":
                        task_succeeded = True
                        break
                    elif result["status"] == "failed":
                        last_error = "Task returned failed status"
                        if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                            continue
                        else:
                            task_failed = True
                            break
                    elif result["status"] == "skipped":
                        task_succeeded = True
                        break

                except ExecutionError as e:
                    last_error = e
                    if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                        print(f"Task failed: {e}. Retrying...", file=sys.stderr)
                        continue
                    else:
                        task_failed = True
                        break

            _emit_item_event(
                workflow_config,
                "loop_item_failed",
                loop_type="csv",
                status="failed",
                index=index,
                total=total,
                item_id=row_id,
            )
            _emit_item_event(
                workflow_config,
                "loop_item_completed",
                loop_type="csv",
                status="success",
                index=index,
                total=total,
                item_id=row_id,
            )
            return {
                "index": index,
                "row_id": row_id,
                "succeeded": task_succeeded,
                "failed": task_failed,
                "error": last_error,
            }

        # Execute rows in parallel
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(process_row, index, csv_rows[index].copy()): index
                for index in range(total)
            }

            # Collect results as they complete
            for future in as_completed(futures):
                result = future.result()
                results["iterations"] += 1

                if result["succeeded"]:
                    results["completed"].append(result["row_id"])
                elif result["failed"]:
                    results["failed"].append(result["row_id"])
                    results["status"] = "partial"

                    # Handle on-failure: abort
                    if on_failure == "abort":
                        print(
                            "Task failed. Aborting loop (on-failure: abort)", file=sys.stderr
                        )
                        results["status"] = "failed"
                        # Cancel pending futures
                        for f in futures:
                            f.cancel()
                        raise ExecutionError(f"Task failed: {result['error']}")

                    # on-failure: skip or retry or None (default)
                    if on_failure == "skip":
                        print("Task failed. Skipping (on-failure: skip)", file=sys.stderr)
                    elif on_failure == "retry":
                        print("Task failed. Continuing to next item", file=sys.stderr)
                    elif on_failure is None:
                        # Default behavior: raise error
                        results["status"] = "failed"
                        # Cancel pending futures
                        for f in futures:
                            f.cancel()
                        raise ExecutionError(f"Task failed: {result['error']}")

        return results

    def _execute_with_directory_pool(
        self,
        task_def,
        loop_config,
        csv_rows,
        resolved_vars,
        adapter,
        workflow_config,
        dry_run=False,
    ):
        """Execute CSV rows in parallel with round-robin directory assignment."""
        import os
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .executor import ExecutionError, execute_single_task

        workers = loop_config.get("workers", 1)
        directory_pool = loop_config.get("directory-pool", [])
        total = len(csv_rows)
        results = {"status": "success", "iterations": 0, "completed": [], "failed": []}

        # Validate directory pool
        if not directory_pool:
            raise ExecutionError("directory-pool cannot be empty when specified")
        if len(directory_pool) < workers:
            print(
                f"Warning: directory-pool has {len(directory_pool)} entries but workers={workers}. "
                f"Some workers will share directories.",
                file=sys.stderr,
            )

        # Validate all directories exist
        for directory in directory_pool:
            expanded_dir = os.path.abspath(os.path.expanduser(directory))
            if not os.path.exists(expanded_dir):
                raise ExecutionError(f"Directory in pool does not exist: {expanded_dir}")
            if not os.path.isdir(expanded_dir):
                raise ExecutionError(f"Path in directory-pool is not a directory: {expanded_dir}")

        # Get verbose and debug flags
        verbose = workflow_config.get("_verbose", False)
        debug = workflow_config.get("_debug", False)

        # Get retry configuration
        retry_config = loop_config.get("retry", {})
        max_attempts = retry_config.get("max-attempts", 1)
        on_failure = retry_config.get("on-failure", None)

        # Validate retry configuration
        if max_attempts < 1:
            raise ExecutionError("retry.max-attempts must be >= 1")
        if on_failure and on_failure not in ["skip", "retry", "abort"]:
            raise ExecutionError(
                f"retry.on-failure must be 'skip', 'retry', or 'abort', got: {on_failure}"
            )

        def process_row(index, csv_row, worker_id):
            """Process a single CSV row with assigned worker directory."""
            _emit_item_event(
                workflow_config,
                "loop_item_started",
                loop_type="csv",
                status="running",
                index=index,
                total=total,
                item_id=f"row-{csv_row.get('_row_number')}",
            )
            remaining = total - index
            row_number = csv_row.pop("_row_number")
            loop_item = {**csv_row, "row": row_number}

            # Assign directory from pool (round-robin)
            assigned_directory = directory_pool[worker_id % len(directory_pool)]
            expanded_dir = os.path.abspath(os.path.expanduser(assigned_directory))

            # Build loop variables with worker info
            loop_vars = {
                "loop": {
                    "index": index,
                    "total": total,
                    "remaining": remaining,
                    "item": loop_item,
                    "worker": {"id": worker_id, "directory": expanded_dir},
                }
            }

            # Merge with resolved vars
            iteration_vars = {**resolved_vars, **loop_vars}

            # Override working directory for this task
            task_workflow_config = workflow_config.copy()
            task_workflow_config["directory"] = expanded_dir

            # Print loop item details in verbose mode
            if verbose:
                print(f"\n=== CSV Loop Iteration {index + 1}/{total} (Worker {worker_id}) ===", file=sys.stderr)
                print(f"  Row number: {row_number}", file=sys.stderr)
                print(f"  Worker directory: {expanded_dir}", file=sys.stderr)
                for key, value in csv_row.items():
                    print(f"  {key}: {value}", file=sys.stderr)
                print(f"  Remaining: {remaining}", file=sys.stderr)
                print("", file=sys.stderr)

            # Execute task with retry logic
            task_succeeded = False
            task_failed = False
            last_error = None
            row_id = f"row-{row_number}"

            for attempt in range(1, max_attempts + 1):
                if on_failure == "skip" and attempt > 1:
                    break

                try:
                    if attempt > 1:
                        print(
                            f"Retrying row {row_number} (attempt {attempt}/{max_attempts})",
                            file=sys.stderr,
                        )

                    result = execute_single_task(
                        f"csv-row-{row_number}",
                        task_def,
                        iteration_vars,
                        adapter,
                        task_workflow_config,
                        dry_run=dry_run,
                        debug=debug,
                    )

                    if result["status"] == "success":
                        task_succeeded = True
                        break
                    elif result["status"] == "failed":
                        last_error = "Task returned failed status"
                        if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                            continue
                        else:
                            task_failed = True
                            break
                    elif result["status"] == "skipped":
                        task_succeeded = True
                        break

                except ExecutionError as e:
                    last_error = e
                    if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                        print(f"Task failed: {e}. Retrying...", file=sys.stderr)
                        continue
                    else:
                        task_failed = True
                        break

            _emit_item_event(
                workflow_config,
                "loop_item_failed",
                loop_type="csv",
                status="failed",
                index=index,
                total=total,
                item_id=row_id,
            )
            _emit_item_event(
                workflow_config,
                "loop_item_completed",
                loop_type="csv",
                status="success",
                index=index,
                total=total,
                item_id=row_id,
            )
            return {
                "index": index,
                "row_id": row_id,
                "succeeded": task_succeeded,
                "failed": task_failed,
                "error": last_error,
            }

        # Execute rows in parallel with worker IDs
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all tasks with worker IDs
            futures = {
                executor.submit(process_row, index, csv_rows[index].copy(), index % workers): index
                for index in range(total)
            }

            # Collect results as they complete
            for future in as_completed(futures):
                result = future.result()
                results["iterations"] += 1

                if result["succeeded"]:
                    results["completed"].append(result["row_id"])
                elif result["failed"]:
                    results["failed"].append(result["row_id"])
                    results["status"] = "partial"

                    # Handle on-failure: abort
                    if on_failure == "abort":
                        print(
                            "Task failed. Aborting loop (on-failure: abort)", file=sys.stderr
                        )
                        results["status"] = "failed"
                        # Cancel pending futures
                        for f in futures:
                            f.cancel()
                        raise ExecutionError(f"Task failed: {result['error']}")

                    # on-failure: skip or retry or None (default)
                    if on_failure == "skip":
                        print("Task failed. Skipping (on-failure: skip)", file=sys.stderr)
                    elif on_failure == "retry":
                        print("Task failed. Continuing to next item", file=sys.stderr)
                    elif on_failure is None:
                        # Default behavior: raise error
                        results["status"] = "failed"
                        # Cancel pending futures
                        for f in futures:
                            f.cancel()
                        raise ExecutionError(f"Task failed: {result['error']}")

        return results

    def _execute_with_worktrees(
        self,
        task_def,
        loop_config,
        csv_rows,
        resolved_vars,
        adapter,
        workflow_config,
        dry_run=False,
    ):
        """Execute CSV rows in parallel with git worktrees."""
        import os
        import subprocess
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .executor import ExecutionError, execute_single_task
        from .utils import interpolate_variables

        workers = loop_config.get("workers", 1)
        git_config = loop_config.get("git-worktrees", {})
        total = len(csv_rows)
        results = {"status": "success", "iterations": 0, "completed": [], "failed": []}

        # Validate git worktree configuration
        if not git_config.get("enabled"):
            raise ExecutionError("git-worktrees.enabled must be true when using git-worktrees")

        base_path = git_config.get("base", "{{gitroot}}/.worktrees")
        branch_field = git_config.get("branch-field")
        name_template = git_config.get("name-template", "worker-{{loop.worker.id}}")
        cleanup = git_config.get("cleanup", True)

        if not branch_field:
            raise ExecutionError("git-worktrees.branch-field is required")

        # Interpolate base path
        base_path = interpolate_variables(base_path, resolved_vars)
        base_path = os.path.abspath(os.path.expanduser(base_path))

        # Verify we're in a git repository
        gitroot = resolved_vars.get("gitroot")
        if not gitroot:
            raise ExecutionError("git-worktrees requires a git repository (gitroot not found)")

        # Create base directory if needed
        if not dry_run:
            os.makedirs(base_path, exist_ok=True)

        # Get verbose and debug flags
        verbose = workflow_config.get("_verbose", False)
        debug = workflow_config.get("_debug", False)

        # Get retry configuration
        retry_config = loop_config.get("retry", {})
        max_attempts = retry_config.get("max-attempts", 1)
        on_failure = retry_config.get("on-failure", None)

        # Validate retry configuration
        if max_attempts < 1:
            raise ExecutionError("retry.max-attempts must be >= 1")
        if on_failure and on_failure not in ["skip", "retry", "abort"]:
            raise ExecutionError(
                f"retry.on-failure must be 'skip', 'retry', or 'abort', got: {on_failure}"
            )

        # Track created worktrees for cleanup
        created_worktrees = []

        def process_row(index, csv_row, worker_id):
            """Process a single CSV row with git worktree."""
            _emit_item_event(
                workflow_config,
                "loop_item_started",
                loop_type="csv",
                status="running",
                index=index,
                total=total,
                item_id=f"row-{csv_row.get('_row_number')}",
            )
            nonlocal created_worktrees

            remaining = total - index
            row_number = csv_row.pop("_row_number")
            loop_item = {**csv_row, "row": row_number}

            # Get branch name from CSV
            branch = csv_row.get(branch_field)
            if not branch:
                raise ExecutionError(
                    f"Row {row_number}: branch field '{branch_field}' is missing or empty"
                )

            # Build worktree name from template
            name_vars = {**resolved_vars, "loop": {"worker": {"id": worker_id}, "item": loop_item}}
            worktree_name = interpolate_variables(name_template, name_vars)
            worktree_path = os.path.join(base_path, worktree_name)

            # Create git worktree
            if not dry_run:
                try:
                    # Check if worktree already exists
                    if os.path.exists(worktree_path):
                        # Remove existing worktree
                        subprocess.run(
                            ["git", "worktree", "remove", worktree_path, "--force"],
                            check=True,
                            capture_output=True,
                            text=True,
                            cwd=gitroot,
                        )

                    # Create new worktree
                    subprocess.run(
                        ["git", "worktree", "add", worktree_path, branch],
                        check=True,
                        capture_output=True,
                        text=True,
                        cwd=gitroot,
                    )
                    created_worktrees.append(worktree_path)

                    if verbose:
                        print(f"Created worktree: {worktree_path} (branch: {branch})", file=sys.stderr)

                except subprocess.CalledProcessError as e:
                    raise ExecutionError(
                        f"Failed to create git worktree for branch '{branch}': {e.stderr}"
                    )

            # Build loop variables with worker info
            loop_vars = {
                "loop": {
                    "index": index,
                    "total": total,
                    "remaining": remaining,
                    "item": loop_item,
                    "worker": {"id": worker_id, "directory": worktree_path},
                }
            }

            # Merge with resolved vars
            iteration_vars = {**resolved_vars, **loop_vars}

            # Override working directory for this task
            task_workflow_config = workflow_config.copy()
            task_workflow_config["directory"] = worktree_path

            # Print loop item details in verbose mode
            if verbose:
                print(f"\n=== CSV Loop Iteration {index + 1}/{total} (Worker {worker_id}) ===", file=sys.stderr)
                print(f"  Row number: {row_number}", file=sys.stderr)
                print(f"  Branch: {branch}", file=sys.stderr)
                print(f"  Worktree: {worktree_path}", file=sys.stderr)
                for key, value in csv_row.items():
                    print(f"  {key}: {value}", file=sys.stderr)
                print(f"  Remaining: {remaining}", file=sys.stderr)
                print("", file=sys.stderr)

            # Execute task with retry logic
            task_succeeded = False
            task_failed = False
            last_error = None
            row_id = f"row-{row_number}"

            for attempt in range(1, max_attempts + 1):
                if on_failure == "skip" and attempt > 1:
                    break

                try:
                    if attempt > 1:
                        print(
                            f"Retrying row {row_number} (attempt {attempt}/{max_attempts})",
                            file=sys.stderr,
                        )

                    result = execute_single_task(
                        f"csv-row-{row_number}",
                        task_def,
                        iteration_vars,
                        adapter,
                        task_workflow_config,
                        dry_run=dry_run,
                        debug=debug,
                    )

                    if result["status"] == "success":
                        task_succeeded = True
                        break
                    elif result["status"] == "failed":
                        last_error = "Task returned failed status"
                        if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                            continue
                        else:
                            task_failed = True
                            break
                    elif result["status"] == "skipped":
                        task_succeeded = True
                        break

                except ExecutionError as e:
                    last_error = e
                    if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                        print(f"Task failed: {e}. Retrying...", file=sys.stderr)
                        continue
                    else:
                        task_failed = True
                        break

            _emit_item_event(
                workflow_config,
                "loop_item_failed",
                loop_type="csv",
                status="failed",
                index=index,
                total=total,
                item_id=row_id,
            )
            _emit_item_event(
                workflow_config,
                "loop_item_completed",
                loop_type="csv",
                status="success",
                index=index,
                total=total,
                item_id=row_id,
            )
            return {
                "index": index,
                "row_id": row_id,
                "succeeded": task_succeeded,
                "failed": task_failed,
                "error": last_error,
                "worktree_path": worktree_path,
            }

        try:
            # Execute rows in parallel with worker IDs
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Submit all tasks with worker IDs
                futures = {
                    executor.submit(process_row, index, csv_rows[index].copy(), index % workers): index
                    for index in range(total)
                }

                # Collect results as they complete
                for future in as_completed(futures):
                    result = future.result()
                    results["iterations"] += 1

                    if result["succeeded"]:
                        results["completed"].append(result["row_id"])
                    elif result["failed"]:
                        results["failed"].append(result["row_id"])
                        results["status"] = "partial"

                        # Handle on-failure: abort
                        if on_failure == "abort":
                            print(
                                "Task failed. Aborting loop (on-failure: abort)", file=sys.stderr
                            )
                            results["status"] = "failed"
                            # Cancel pending futures
                            for f in futures:
                                f.cancel()
                            raise ExecutionError(f"Task failed: {result['error']}")

                        # on-failure: skip or retry or None (default)
                        if on_failure == "skip":
                            print("Task failed. Skipping (on-failure: skip)", file=sys.stderr)
                        elif on_failure == "retry":
                            print("Task failed. Continuing to next item", file=sys.stderr)
                        elif on_failure is None:
                            # Default behavior: raise error
                            results["status"] = "failed"
                            # Cancel pending futures
                            for f in futures:
                                f.cancel()
                            raise ExecutionError(f"Task failed: {result['error']}")

        finally:
            # Cleanup worktrees if requested
            if cleanup and not dry_run:
                for worktree_path in created_worktrees:
                    try:
                        subprocess.run(
                            ["git", "worktree", "remove", worktree_path, "--force"],
                            check=True,
                            capture_output=True,
                            text=True,
                            cwd=gitroot,
                        )
                        if verbose:
                            print(f"Removed worktree: {worktree_path}", file=sys.stderr)
                    except subprocess.CalledProcessError as e:
                        print(
                            f"Warning: Failed to remove worktree {worktree_path}: {e.stderr}",
                            file=sys.stderr,
                        )

        return results

    def _parse_csv_file(self, file_path, loop_config):
        """
        Parse CSV file and return list of row dicts.

        Args:
            file_path: Path to CSV file
            loop_config: Loop configuration with optional 'skip-header', 'columns', 'filter'

        Returns:
            list: List of dicts with CSV data and '_row_number' (1-based)

        Raises:
            ExecutionError: If CSV parsing fails or filter config is invalid
        """
        import csv

        from .executor import ExecutionError

        skip_header = loop_config.get("skip-header", False)
        custom_columns = loop_config.get("columns", [])
        filter_config = loop_config.get("filter", {})

        rows = []

        try:
            with open(file_path, "r", newline="", encoding="utf-8") as f:
                # Skip first row if requested
                if skip_header:
                    next(f, None)

                # Use custom column names if provided, otherwise read from file
                if custom_columns:
                    reader = csv.DictReader(f, fieldnames=custom_columns)
                else:
                    reader = csv.DictReader(f)

                # Check if we have valid headers
                if reader.fieldnames is None:
                    return []  # Empty file

                # Parse all rows
                for row_num, row in enumerate(reader, start=1):
                    # Adjust row number if we skipped header
                    actual_row_num = row_num + 1 if skip_header else row_num

                    # Apply filter if specified
                    if filter_config:
                        filter_column = filter_config.get("column")
                        filter_value = filter_config.get("value")

                        if not filter_column:
                            raise ExecutionError("filter.column is required when using filter")
                        if filter_value is None:
                            raise ExecutionError("filter.value is required when using filter")

                        # Check if column exists
                        if filter_column not in row:
                            raise ExecutionError(
                                f"Filter column '{filter_column}' not found in CSV. Available columns: {', '.join(row.keys())}"
                            )

                        # Skip rows that don't match filter
                        if row[filter_column] != str(filter_value):
                            continue

                    # Add internal row number field
                    row["_row_number"] = actual_row_num
                    rows.append(row)

        except csv.Error as e:
            raise ExecutionError(f"CSV parsing error: {e}")
        except UnicodeDecodeError as e:
            raise ExecutionError(f"CSV file encoding error: {e}. File must be UTF-8 encoded.")
        except Exception as e:
            raise ExecutionError(f"Error reading CSV file: {e}")

        return rows


class FileItem(dict):
    """
    Dict that renders as file path when converted to string.

    This allows {{loop.item}} to work as both:
    - A string (renders as path): "{{loop.item}}" -> "src/index.ts"
    - A dict (access properties): "{{loop.item.filename}}" -> "index.ts"
    """

    def __str__(self):
        return self.get("path", "")

    def __repr__(self):
        return self.get("path", "")


class GlobLoop(BaseLoop):
    """
    Iterate over files matching glob pattern.

    Variables:
    - {{loop.item.path}} - Full file path
    - {{loop.item.filename}} - Filename without path
    - {{loop.item.extension}} - File extension
    - {{loop.item}} - Renders as file path when used as string
    """

    def execute(
        self, task_def, loop_config, resolved_vars, adapter, workflow_config, dry_run=False
    ):
        """
        Execute task for each file matching glob pattern.

        Args:
            task_def: Task definition dict with 'prompt', optional 'include', 'on-error'
            loop_config: Loop configuration with 'pattern', optional 'exclude',
                        'sort', 'checkpoint-file', 'resume'
            resolved_vars: Resolved variables for interpolation
            adapter: CLI adapter instance
            workflow_config: Workflow configuration
            dry_run: If True, parse and display loop info without executing (default: False)

        Returns:
            dict: Execution results for all iterations

        Raises:
            ExecutionError: If pattern field missing or file permission error
        """
        import os
        import sys

        from .executor import ExecutionError, execute_single_task
        from .utils import interpolate_variables

        # Get pattern (required)
        pattern = loop_config.get("pattern", "")
        if not pattern:
            raise ExecutionError("GlobLoop requires 'pattern' field")

        # Interpolate pattern (may contain template variables)
        pattern = interpolate_variables(pattern, resolved_vars)

        # Get exclude patterns (optional)
        exclude_patterns = loop_config.get("exclude", [])
        if isinstance(exclude_patterns, str):
            exclude_patterns = [exclude_patterns]

        # Interpolate exclude patterns
        exclude_patterns = [interpolate_variables(p, resolved_vars) for p in exclude_patterns]

        # Get sort option (optional)
        sort_by = loop_config.get("sort")

        # Get matching files
        matching_files = self._get_matching_files(pattern, exclude_patterns)

        # Sort files if requested
        if sort_by:
            matching_files = self._sort_files(matching_files, sort_by)

        # Handle empty file list
        if not matching_files:
            print(f"No files match pattern: {pattern}", file=sys.stderr)
            return {"status": "success", "iterations": 0, "completed": [], "failed": []}

        # Dry run mode: print loop info and return
        if dry_run:
            print("[DRY RUN] Glob loop:", file=sys.stderr)
            print(f"  Pattern: {pattern}", file=sys.stderr)
            if exclude_patterns:
                print(f"  Exclude: {', '.join(exclude_patterns)}", file=sys.stderr)
            if sort_by:
                print(f"  Sort by: {sort_by}", file=sys.stderr)
            print(f"  Matching files: {len(matching_files)}", file=sys.stderr)
            if loop_config.get("checkpoint-file"):
                print(f"  Checkpoint file: {loop_config.get('checkpoint-file')}", file=sys.stderr)
            print("  Files to process:", file=sys.stderr)
            for idx, file_path in enumerate(matching_files, 1):
                print(f"    {idx}. {file_path}", file=sys.stderr)
            return {
                "status": "success",
                "iterations": len(matching_files),
                "completed": [],
                "failed": [],
            }

        # Load checkpoint if resume is enabled
        checkpoint_file = loop_config.get("checkpoint-file")
        if checkpoint_file:
            # Checkpoint paths may contain template variables (e.g. {{output-dir}}/ckpt.json)
            checkpoint_file = interpolate_variables(str(checkpoint_file), resolved_vars)
            checkpoint_file = os.path.abspath(os.path.expanduser(checkpoint_file))
        resume = loop_config.get("resume", False)
        checkpoint_manager = CheckpointManager()
        checkpoint = None

        if resume and checkpoint_file:
            checkpoint = checkpoint_manager.load_checkpoint(checkpoint_file)
            if checkpoint:
                print(f"Resuming from checkpoint: {checkpoint_file}", file=sys.stderr)

        # Initialize tracking
        start_index = 0
        completed_items = []
        failed_items = []

        if checkpoint:
            # Resume from checkpoint
            start_index = checkpoint.get("current_index", 0)
            completed_items = checkpoint.get("completed_items", [])
            failed_items = checkpoint.get("failed_items", [])

        # Execute task for each matching file
        total = len(matching_files)
        results = {
            "status": "success",
            "iterations": 0,
            "completed": completed_items.copy(),
            "failed": failed_items.copy(),
        }

        # Get verbose flag from workflow_config
        verbose = workflow_config.get("_verbose", False)

        for index in range(start_index, total):
            file_path = matching_files[index]
            _emit_item_event(
                workflow_config,
                "loop_item_started",
                loop_type="glob",
                status="running",
                index=index,
                total=total,
                item_id=os.path.basename(file_path),
            )
            remaining = total - index

            # Build file item
            file_item = self._build_file_item(file_path)

            # Build loop variables
            loop_vars = {
                "loop": {"index": index, "total": total, "remaining": remaining, "item": file_item}
            }

            # Merge with resolved vars
            iteration_vars = {**resolved_vars, **loop_vars}

            # Print loop item details in verbose mode
            if verbose:
                print(f"\n=== Glob Loop Iteration {index + 1}/{total} ===", file=sys.stderr)
                print(f"  Path: {file_item['path']}", file=sys.stderr)
                print(f"  Filename: {file_item['filename']}", file=sys.stderr)
                print(f"  Extension: {file_item['extension']}", file=sys.stderr)
                print(f"  Remaining: {remaining}", file=sys.stderr)
                print("", file=sys.stderr)

            # Get retry configuration
            retry_config = loop_config.get("retry", {})
            max_attempts = retry_config.get("max-attempts", 1)
            on_failure = retry_config.get("on-failure", None)

            # Validate retry configuration
            if max_attempts < 1:
                raise ExecutionError("retry.max-attempts must be >= 1")
            if on_failure and on_failure not in ["skip", "retry", "abort"]:
                raise ExecutionError(
                    f"retry.on-failure must be 'skip', 'retry', or 'abort', got: {on_failure}"
                )

            # Execute task with retry logic
            task_succeeded = False
            task_failed = False
            last_error = None

            for attempt in range(1, max_attempts + 1):
                # Handle on-failure: skip (only try once)
                if on_failure == "skip" and attempt > 1:
                    break

                try:
                    if attempt > 1:
                        print(
                            f"Retrying file '{file_path}' (attempt {attempt}/{max_attempts})",
                            file=sys.stderr,
                        )

                    # Get debug flag from workflow_config
                    debug = workflow_config.get("_debug", False)

                    result = execute_single_task(
                        f"file-{index}",
                        task_def,
                        iteration_vars,
                        adapter,
                        workflow_config,
                        dry_run=dry_run,
                        debug=debug,
                    )

                    results["iterations"] += 1

                    if result["status"] == "success":
                        task_succeeded = True
                        break
                    elif result["status"] == "failed":
                        # Task returned failed status (on-error: continue/skip)
                        last_error = "Task returned failed status"
                        # Retry for 'retry' or 'abort' modes
                        if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                            continue  # Retry
                        else:
                            task_failed = True
                            break
                    elif result["status"] == "skipped":
                        # Task was skipped (counts as success for retry purposes)
                        task_succeeded = True
                        break

                except ExecutionError as e:
                    # Task failed with on-error: fail strategy or execution error
                    last_error = e
                    # Retry for 'retry' or 'abort' modes
                    if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                        print(f"Task failed: {e}. Retrying...", file=sys.stderr)
                        continue  # Retry
                    else:
                        task_failed = True
                        break

            # Handle final outcome after all retry attempts
            if task_succeeded:
                _emit_item_event(
                    workflow_config,
                    "loop_item_completed",
                    loop_type="glob",
                    status="success",
                    index=index,
                    total=total,
                    item_id=file_path,
                )
                completed_items.append(file_path)
                results["completed"].append(file_path)

            elif task_failed:
                _emit_item_event(
                    workflow_config,
                    "loop_item_failed",
                    loop_type="glob",
                    status="failed",
                    index=index,
                    total=total,
                    item_id=file_path,
                )
                failed_items.append(file_path)
                results["failed"].append(file_path)
                results["status"] = "partial"

                # Handle on-failure: abort
                if on_failure == "abort":
                    print(
                        f"Task failed after {max_attempts} attempt(s). Aborting loop (on-failure: abort)",
                        file=sys.stderr,
                    )
                    results["status"] = "failed"

                    # Save checkpoint before raising (skip in dry-run)
                    if checkpoint_file and not dry_run:
                        checkpoint_data = {
                            "type": "glob",
                            "current_index": index + 1,
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                        }
                        checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

                    # Re-raise if it was an ExecutionError, otherwise raise new one
                    if isinstance(last_error, ExecutionError):
                        raise last_error
                    else:
                        raise ExecutionError(
                            f"Task failed after {max_attempts} attempt(s): {last_error}"
                        )

                # on-failure: skip or retry (retries exhausted) or None (default: raise)
                if on_failure == "skip":
                    print("Task failed. Skipping to next item (on-failure: skip)", file=sys.stderr)
                elif on_failure == "retry":
                    print(
                        f"Task failed after {max_attempts} attempt(s). Continuing to next item",
                        file=sys.stderr,
                    )
                else:
                    # on_failure is None (default behavior: raise ExecutionError)
                    results["status"] = "failed"

                    # Save checkpoint before raising (skip in dry-run)
                    if checkpoint_file and not dry_run:
                        checkpoint_data = {
                            "type": "glob",
                            "current_index": index + 1,
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                        }
                        checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

                    # Re-raise if it was an ExecutionError, otherwise raise new one
                    if isinstance(last_error, ExecutionError):
                        raise last_error
                    else:
                        raise ExecutionError(f"Task failed: {last_error}")

            # Save checkpoint after each iteration (skip in dry-run)
            if checkpoint_file and not dry_run:
                checkpoint_data = {
                    "type": "glob",
                    "current_index": index + 1,
                    "completed_items": completed_items,
                    "failed_items": failed_items,
                }
                checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

        return results

    def _get_matching_files(self, pattern, exclude_patterns=None):
        """
        Get files matching glob pattern with optional exclusions.

        Args:
            pattern: Glob pattern (e.g., "src/**/*.py")
            exclude_patterns: List of patterns to exclude (optional)

        Returns:
            list: Sorted list of absolute file paths

        Raises:
            ExecutionError: If permission error occurs
        """
        import glob
        import os
        from fnmatch import fnmatch

        from .executor import ExecutionError

        try:
            # Get all matching files (recursive)
            matches = glob.glob(pattern, recursive=True)

            # Filter to only files (not directories)
            file_matches = [m for m in matches if os.path.isfile(m)]

            # Apply exclusions
            if exclude_patterns:
                filtered = []
                for file_path in file_matches:
                    # Check if file matches any exclude pattern
                    excluded = False
                    for exclude_pattern in exclude_patterns:
                        if fnmatch(file_path, exclude_pattern):
                            excluded = True
                            break

                    if not excluded:
                        filtered.append(file_path)

                file_matches = filtered

            # Convert to absolute paths
            file_matches = [os.path.abspath(f) for f in file_matches]

            return file_matches

        except PermissionError as e:
            raise ExecutionError(f"Permission denied accessing files: {e}")
        except Exception as e:
            raise ExecutionError(f"Error matching files: {e}")

    def _sort_files(self, file_paths, sort_by):
        """
        Sort files by specified criteria.

        Args:
            file_paths: List of file paths
            sort_by: Sort criteria ('name', 'modified', 'size', 'created')

        Returns:
            list: Sorted file paths

        Raises:
            ExecutionError: If sort_by is invalid or file stat fails
        """
        import os
        import sys

        from .executor import ExecutionError

        if sort_by == "name":
            # Sort alphabetically by path
            return sorted(file_paths)

        elif sort_by == "modified":
            # Sort by modification time (newest first)
            try:
                return sorted(file_paths, key=lambda f: os.path.getmtime(f), reverse=True)
            except OSError as e:
                raise ExecutionError(f"Error getting modification time: {e}")

        elif sort_by == "size":
            # Sort by file size (largest first)
            try:
                return sorted(file_paths, key=lambda f: os.path.getsize(f), reverse=True)
            except OSError as e:
                raise ExecutionError(f"Error getting file size: {e}")

        elif sort_by == "created":
            # Sort by creation time (newest first)
            # Use st_birthtime on macOS, st_ctime on other platforms
            try:

                def get_creation_time(file_path):
                    stat = os.stat(file_path)
                    # macOS has st_birthtime, others use st_ctime
                    if sys.platform == "darwin":
                        return stat.st_birthtime
                    else:
                        return stat.st_ctime

                return sorted(file_paths, key=get_creation_time, reverse=True)
            except OSError as e:
                raise ExecutionError(f"Error getting creation time: {e}")

        else:
            raise ExecutionError(
                f"Invalid sort value: {sort_by}. Must be 'name', 'modified', 'size', or 'created'"
            )

    def _build_file_item(self, file_path):
        """
        Build FileItem dict with path, filename, and extension.

        Args:
            file_path: Absolute file path

        Returns:
            FileItem: Dict with 'path', 'filename', 'extension' keys
        """
        import os

        filename = os.path.basename(file_path)
        _, extension = os.path.splitext(filename)

        return FileItem({"path": file_path, "filename": filename, "extension": extension})


class CheckpointManager:
    """Manages loop checkpoint creation and restoration."""

    def save_checkpoint(self, checkpoint_file, checkpoint_data):
        """
        Save checkpoint to JSON file atomically.

        Uses temp file + os.replace() for atomic writes to prevent
        corruption if process is interrupted during write.

        Args:
            checkpoint_file: Path to checkpoint file
            checkpoint_data: Dict with checkpoint state

        Checkpoint format:
            {
                "type": "todo-list|csv|glob|json|jsonl",
                "current_index": 3,
                "completed_items": ["item1", "item2", "item3"],
                "failed_items": ["item4"]
            }
        """
        import json
        import os
        import tempfile

        # Create parent directory if it doesn't exist
        checkpoint_path = os.path.abspath(os.path.expanduser(checkpoint_file))
        checkpoint_dir = os.path.dirname(checkpoint_path)
        if checkpoint_dir:
            os.makedirs(checkpoint_dir, exist_ok=True)

        # Write to temp file first
        fd, temp_path = tempfile.mkstemp(dir=checkpoint_dir, prefix=".checkpoint-", suffix=".tmp")

        try:
            with os.fdopen(fd, "w") as f:
                json.dump(checkpoint_data, f, indent=2)

            # Atomic replace
            os.replace(temp_path, checkpoint_path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def load_checkpoint(self, checkpoint_file):
        """
        Load checkpoint from JSON file with validation.

        Args:
            checkpoint_file: Path to checkpoint file

        Returns:
            dict: Checkpoint data or None if file doesn't exist

        Raises:
            CheckpointValidationError: If checkpoint file format is invalid
            json.JSONDecodeError: If checkpoint file is invalid JSON
            IOError: If file exists but cannot be read
        """
        import json
        import os

        checkpoint_path = os.path.abspath(os.path.expanduser(checkpoint_file))

        if not os.path.exists(checkpoint_path):
            return None

        try:
            with open(checkpoint_path, "r") as f:
                checkpoint_data = json.load(f)
        except json.JSONDecodeError as e:
            raise CheckpointValidationError(
                f"Invalid checkpoint file format\n\n"
                f"Context: Checkpoint file contains invalid JSON\n"
                f"File: {checkpoint_path}\n"
                f"Expected: Valid JSON checkpoint data\n"
                f"Found: {str(e)}\n"
                f"Suggestion: Delete the corrupted checkpoint file and restart the workflow:\n"
                f"  rm {checkpoint_path}"
            )
        except Exception as e:
            raise CheckpointValidationError(
                f"Failed to read checkpoint file\n\n"
                f"Context: Error reading checkpoint file\n"
                f"File: {checkpoint_path}\n"
                f"Error: {str(e)}\n"
                f"Suggestion: Ensure the file has read permissions or delete it to start fresh"
            )

        # Validate checkpoint structure
        self._validate_checkpoint_structure(checkpoint_data, checkpoint_path)

        return checkpoint_data

    def _validate_checkpoint_structure(self, checkpoint_data, checkpoint_path):
        """
        Validate checkpoint data structure.

        Args:
            checkpoint_data: Parsed checkpoint dict
            checkpoint_path: Path to checkpoint file (for error messages)

        Raises:
            CheckpointValidationError: If checkpoint structure is invalid
        """
        if not isinstance(checkpoint_data, dict):
            raise CheckpointValidationError(
                f"Invalid checkpoint file format\n\n"
                f"Context: Checkpoint data must be a JSON object\n"
                f"File: {checkpoint_path}\n"
                f"Expected: JSON object with 'type', 'current_index', etc.\n"
                f"Found: {type(checkpoint_data).__name__}\n"
                f"Suggestion: Delete the corrupted checkpoint file:\n"
                f"  rm {checkpoint_path}"
            )

        # Required fields
        required_fields = ["type", "current_index", "completed_items", "failed_items"]
        missing_fields = [field for field in required_fields if field not in checkpoint_data]

        if missing_fields:
            raise CheckpointValidationError(
                f"Invalid checkpoint file format\n\n"
                f"Context: Checkpoint missing required fields\n"
                f"File: {checkpoint_path}\n"
                f"Expected: Fields {required_fields}\n"
                f"Found: Missing {missing_fields}\n"
                f"Suggestion: Delete the corrupted checkpoint file:\n"
                f"  rm {checkpoint_path}"
            )

        # Validate field types
        valid_types = ["todo-list", "csv", "glob", "json", "jsonl"]
        if checkpoint_data["type"] not in valid_types:
            raise CheckpointValidationError(
                f"Invalid checkpoint file format\n\n"
                f"Context: Invalid checkpoint type\n"
                f"File: {checkpoint_path}\n"
                f"Expected: One of {valid_types}\n"
                f"Found: '{checkpoint_data['type']}'\n"
                f"Suggestion: Delete the corrupted checkpoint file:\n"
                f"  rm {checkpoint_path}"
            )

        if not isinstance(checkpoint_data["current_index"], int):
            raise CheckpointValidationError(
                f"Invalid checkpoint file format\n\n"
                f"Context: Field 'current_index' must be an integer\n"
                f"File: {checkpoint_path}\n"
                f"Expected: Integer value\n"
                f"Found: {type(checkpoint_data['current_index']).__name__}\n"
                f"Suggestion: Delete the corrupted checkpoint file:\n"
                f"  rm {checkpoint_path}"
            )

        if not isinstance(checkpoint_data["completed_items"], list):
            raise CheckpointValidationError(
                f"Invalid checkpoint file format\n\n"
                f"Context: Field 'completed_items' must be a list\n"
                f"File: {checkpoint_path}\n"
                f"Expected: List of completed items\n"
                f"Found: {type(checkpoint_data['completed_items']).__name__}\n"
                f"Suggestion: Delete the corrupted checkpoint file:\n"
                f"  rm {checkpoint_path}"
            )

        if not isinstance(checkpoint_data["failed_items"], list):
            raise CheckpointValidationError(
                f"Invalid checkpoint file format\n\n"
                f"Context: Field 'failed_items' must be a list\n"
                f"File: {checkpoint_path}\n"
                f"Expected: List of failed items\n"
                f"Found: {type(checkpoint_data['failed_items']).__name__}\n"
                f"Suggestion: Delete the corrupted checkpoint file:\n"
                f"  rm {checkpoint_path}"
            )


class JsonLoop(BaseLoop):
    """
    Loop type that iterates over JSON arrays or JSON Lines files.

    Supports:
    - Standard JSON arrays with optional nested path extraction
    - JSON Lines format (one JSON object per line)
    - Filtering with single or multiple conditions (AND/OR)
    - Primitive wrapping for consistent API
    - Checkpoint/resume functionality
    - Parallel execution with workers
    """

    def execute(
        self, task_def, loop_config, resolved_vars, adapter, workflow_config, dry_run=False
    ):
        """
        Execute task for each JSON array item or JSONL line.

        Args:
            task_def: Task definition dict with 'prompt', optional 'include', 'on-error'
            loop_config: Loop configuration with 'source', optional 'path', 'filter',
                        'checkpoint-file', 'resume', 'workers'
            resolved_vars: Resolved variables for interpolation
            adapter: CLI adapter instance
            workflow_config: Workflow configuration
            dry_run: If True, parse and display loop info without executing (default: False)

        Returns:
            dict: Execution results for all iterations

        Raises:
            ExecutionError: If source file not found or JSON parsing error
        """
        import os
        import sys

        from .executor import ExecutionError
        from .utils import interpolate_variables

        # Interpolate source path (may contain template variables)
        source_path = loop_config.get("source", "")
        if not source_path:
            raise ExecutionError("JsonLoop requires 'source' field")

        source_path = interpolate_variables(source_path, resolved_vars)
        source_path = os.path.abspath(os.path.expanduser(source_path))

        # Check if file exists
        if not os.path.exists(source_path):
            if dry_run:
                print(f"[DRY RUN] Warning: JSON file not found: {source_path}", file=sys.stderr)
                print(
                    "[DRY RUN] Loop would fail at runtime if file is not created by previous task",
                    file=sys.stderr,
                )
                return {"status": "success", "iterations": 0, "completed": [], "failed": []}
            raise ExecutionError(f"JSON file not found: {source_path}")

        # Determine loop type (json vs jsonl)
        loop_type = loop_config.get("type", "json")

        # Parse JSON or JSONL file
        try:
            if loop_type == "jsonl":
                json_items = self._parse_jsonl_file(source_path)
            else:
                json_items = self._parse_json_file(source_path, loop_config)
        except FileNotFoundError:
            if dry_run:
                print(f"[DRY RUN] Warning: JSON file not found: {source_path}", file=sys.stderr)
                print("[DRY RUN] Loop would fail at runtime", file=sys.stderr)
                return {"status": "success", "iterations": 0, "completed": [], "failed": []}
            raise
        except Exception as e:
            raise ExecutionError(f"Error parsing JSON file: {e}")

        # Apply filter if specified
        filter_config = loop_config.get("filter", {})
        if filter_config:
            json_items = self._apply_filter(json_items, filter_config)

        # Handle empty array
        if not json_items:
            print(f"No items to process in {source_path}", file=sys.stderr)
            return {"status": "success", "iterations": 0, "completed": [], "failed": []}

        # Check for parallel execution
        workers = loop_config.get("workers", 1)
        if workers > 1:
            # Use parallel execution
            if dry_run:
                print("[DRY RUN] JSON loop (parallel):", file=sys.stderr)
                print(f"  Source: {source_path}", file=sys.stderr)
                print(f"  Type: {loop_type}", file=sys.stderr)
                print(f"  Workers: {workers}", file=sys.stderr)
                print(f"  Items to process: {len(json_items)}", file=sys.stderr)
                if loop_config.get("path"):
                    print(f"  Path: {loop_config.get('path')}", file=sys.stderr)
                if filter_config:
                    print(f"  Filter: {filter_config}", file=sys.stderr)
                return {"status": "success", "iterations": len(json_items), "completed": [], "failed": []}

            return self._execute_parallel(
                task_def, loop_config, json_items, resolved_vars, adapter, workflow_config, dry_run=dry_run
            )

        # Sequential execution
        # Dry run mode: print loop info and return
        if dry_run:
            print("[DRY RUN] JSON loop:", file=sys.stderr)
            print(f"  Source: {source_path}", file=sys.stderr)
            print(f"  Type: {loop_type}", file=sys.stderr)
            print(f"  Items to process: {len(json_items)}", file=sys.stderr)
            if loop_config.get("path"):
                print(f"  Path: {loop_config.get('path')}", file=sys.stderr)
            if filter_config:
                print(f"  Filter: {filter_config}", file=sys.stderr)
            if loop_config.get("checkpoint-file"):
                print(f"  Checkpoint file: {loop_config.get('checkpoint-file')}", file=sys.stderr)
            print("  Items to process:", file=sys.stderr)
            for idx, item in enumerate(json_items[:10], 1):
                # Show preview
                if isinstance(item, dict):
                    preview = ", ".join([f"{k}={v}" for k, v in list(item.items())[:3]])
                    print(f"    {idx}. {preview}", file=sys.stderr)
                else:
                    print(f"    {idx}. {item}", file=sys.stderr)
            if len(json_items) > 10:
                print(f"    ... and {len(json_items) - 10} more items", file=sys.stderr)
            return {"status": "success", "iterations": len(json_items), "completed": [], "failed": []}

        # Load checkpoint if resume is enabled
        checkpoint_file = loop_config.get("checkpoint-file")
        if checkpoint_file:
            # Checkpoint paths may contain template variables (e.g. {{output-dir}}/ckpt.json)
            checkpoint_file = interpolate_variables(str(checkpoint_file), resolved_vars)
            checkpoint_file = os.path.abspath(os.path.expanduser(checkpoint_file))
        resume = loop_config.get("resume", False)
        checkpoint_manager = CheckpointManager()
        checkpoint = None

        if resume and checkpoint_file:
            checkpoint = checkpoint_manager.load_checkpoint(checkpoint_file)
            if checkpoint:
                print(f"Resuming from checkpoint: {checkpoint_file}", file=sys.stderr)

        # Initialize tracking
        start_index = 0
        completed_items = []
        failed_items = []

        if checkpoint:
            # Resume from checkpoint
            start_index = checkpoint.get("current_index", 0)
            completed_items = checkpoint.get("completed_items", [])
            failed_items = checkpoint.get("failed_items", [])

        # Execute task for each JSON item
        total = len(json_items)
        results = {
            "status": "success",
            "iterations": 0,
            "completed": completed_items.copy(),
            "failed": failed_items.copy(),
        }

        # Get verbose flag from workflow_config
        verbose = workflow_config.get("_verbose", False)

        for index in range(start_index, total):
            json_item = json_items[index]
            _emit_item_event(
                workflow_config,
                "loop_item_started",
                loop_type=loop_config.get("type", "json"),
                status="running",
                index=index,
                total=total,
                item_id=f"item-{index}",
            )
            remaining = total - index

            # Build loop variables - ensure item is always a dict
            if not isinstance(json_item, dict):
                # Wrap primitives
                json_item = self._wrap_primitive_item(json_item, index)

            loop_vars = {
                "loop": {"index": index, "total": total, "remaining": remaining, "item": json_item}
            }

            # Merge with resolved vars
            iteration_vars = {**resolved_vars, **loop_vars}

            # Print loop item details in verbose mode
            if verbose:
                print(f"\n=== JSON Loop Iteration {index + 1}/{total} ===", file=sys.stderr)
                if isinstance(json_item, dict):
                    for key, value in json_item.items():
                        print(f"  {key}: {value}", file=sys.stderr)
                else:
                    print(f"  Item: {json_item}", file=sys.stderr)
                print(f"  Remaining: {remaining}", file=sys.stderr)
                print("", file=sys.stderr)

            # Get retry configuration
            retry_config = loop_config.get("retry", {})
            max_attempts = retry_config.get("max-attempts", 1)
            on_failure = retry_config.get("on-failure", None)

            # Validate retry configuration
            if max_attempts < 1:
                raise ExecutionError("retry.max-attempts must be >= 1")
            if on_failure and on_failure not in ["skip", "retry", "abort"]:
                raise ExecutionError(
                    f"retry.on-failure must be 'skip', 'retry', or 'abort', got: {on_failure}"
                )

            # Create item identifier for tracking
            item_id = f"item-{index}"

            # Execute task with retry logic
            from .executor import execute_single_task

            task_succeeded = False
            task_failed = False
            last_error = None

            for attempt in range(1, max_attempts + 1):
                # Handle on-failure: skip (only try once)
                if on_failure == "skip" and attempt > 1:
                    break

                try:
                    if attempt > 1:
                        print(
                            f"Retrying item {index} (attempt {attempt}/{max_attempts})",
                            file=sys.stderr,
                        )

                    # Get debug flag from workflow_config
                    debug = workflow_config.get("_debug", False)

                    result = execute_single_task(
                        f"json-item-{index}",
                        task_def,
                        iteration_vars,
                        adapter,
                        workflow_config,
                        dry_run=dry_run,
                        debug=debug,
                    )

                    results["iterations"] += 1

                    if result["status"] == "success":
                        task_succeeded = True
                        break
                    elif result["status"] == "failed":
                        # Task returned failed status (on-error: continue/skip)
                        last_error = "Task returned failed status"
                        # Retry for 'retry' or 'abort' modes
                        if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                            continue  # Retry
                        else:
                            task_failed = True
                            break
                    elif result["status"] == "skipped":
                        # Task was skipped (counts as success for retry purposes)
                        task_succeeded = True
                        break

                except ExecutionError as e:
                    # Task failed with on-error: fail strategy or execution error
                    last_error = e
                    # Retry for 'retry' or 'abort' modes
                    if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                        print(f"Task failed: {e}. Retrying...", file=sys.stderr)
                        continue  # Retry
                    else:
                        task_failed = True
                        break

            # Handle final outcome after all retry attempts
            if task_succeeded:
                _emit_item_event(
                    workflow_config,
                    "loop_item_completed",
                    loop_type=loop_config.get("type", "json"),
                    status="success",
                    index=index,
                    total=total,
                    item_id=item_id,
                )
                completed_items.append(item_id)
                results["completed"].append(item_id)

            elif task_failed:
                _emit_item_event(
                    workflow_config,
                    "loop_item_failed",
                    loop_type=loop_config.get("type", "json"),
                    status="failed",
                    index=index,
                    total=total,
                    item_id=item_id,
                )
                failed_items.append(item_id)
                results["failed"].append(item_id)
                results["status"] = "partial"

                # Handle on-failure: abort
                if on_failure == "abort":
                    print(
                        f"Task failed after {max_attempts} attempt(s). Aborting loop (on-failure: abort)",
                        file=sys.stderr,
                    )
                    results["status"] = "failed"

                    # Save checkpoint before raising (skip in dry-run)
                    if checkpoint_file and not dry_run:
                        checkpoint_data = {
                            "type": loop_type,
                            "current_index": index + 1,
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                        }
                        checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

                    # Re-raise if it was an ExecutionError, otherwise raise new one
                    if isinstance(last_error, ExecutionError):
                        raise last_error
                    else:
                        raise ExecutionError(
                            f"Task failed after {max_attempts} attempt(s): {last_error}"
                        )

                # on-failure: skip or retry (retries exhausted) or None (default: raise)
                if on_failure == "skip":
                    print("Task failed. Skipping to next item (on-failure: skip)", file=sys.stderr)
                elif on_failure == "retry":
                    print(
                        f"Task failed after {max_attempts} attempt(s). Continuing to next item",
                        file=sys.stderr,
                    )
                else:
                    # on_failure is None (default behavior: raise ExecutionError)
                    results["status"] = "failed"

                    # Save checkpoint before raising (skip in dry-run)
                    if checkpoint_file and not dry_run:
                        checkpoint_data = {
                            "type": loop_type,
                            "current_index": index + 1,
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                        }
                        checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

                    # Re-raise if it was an ExecutionError, otherwise raise new one
                    if isinstance(last_error, ExecutionError):
                        raise last_error
                    else:
                        raise ExecutionError(f"Task failed: {last_error}")

            # Save checkpoint after each iteration (skip in dry-run)
            if checkpoint_file and not dry_run:
                checkpoint_data = {
                    "type": loop_type,
                    "current_index": index + 1,
                    "completed_items": completed_items,
                    "failed_items": failed_items,
                }
                checkpoint_manager.save_checkpoint(checkpoint_file, checkpoint_data)

        return results

    def _execute_parallel(
        self,
        task_def,
        loop_config,
        json_items,
        resolved_vars,
        adapter,
        workflow_config,
        dry_run=False,
    ):
        """
        Execute JSON items in parallel using ThreadPoolExecutor.

        Args:
            task_def: Task definition with prompt
            loop_config: Loop configuration with workers
            json_items: Parsed JSON items to process
            resolved_vars: Resolved variables
            adapter: CLI adapter instance
            workflow_config: Workflow configuration
            dry_run: If True, don't execute tasks

        Returns:
            dict: Execution results with status, iterations, completed, failed

        Raises:
            ExecutionError: If invalid configuration
        """
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from .executor import ExecutionError, execute_single_task

        workers = loop_config.get("workers", 1)
        total = len(json_items)
        results = {"status": "success", "iterations": 0, "completed": [], "failed": []}

        # Get verbose flag
        verbose = workflow_config.get("_verbose", False)
        debug = workflow_config.get("_debug", False)

        # Get retry configuration
        retry_config = loop_config.get("retry", {})
        max_attempts = retry_config.get("max-attempts", 1)
        on_failure = retry_config.get("on-failure", None)

        # Validate retry configuration
        if max_attempts < 1:
            raise ExecutionError("retry.max-attempts must be >= 1")
        if on_failure and on_failure not in ["skip", "retry", "abort"]:
            raise ExecutionError(
                f"retry.on-failure must be 'skip', 'retry', or 'abort', got: {on_failure}"
            )

        def process_item(index, json_item):
            """Process a single JSON item (executed in worker thread)."""
            _emit_item_event(
                workflow_config,
                "loop_item_started",
                loop_type=loop_config.get("type", "json"),
                status="running",
                index=index,
                total=total,
                item_id=f"item-{index}",
            )
            remaining = total - index

            # Ensure item is always a dict
            if not isinstance(json_item, dict):
                json_item = self._wrap_primitive_item(json_item, index)

            # Build loop variables
            loop_vars = {
                "loop": {"index": index, "total": total, "remaining": remaining, "item": json_item}
            }

            # Merge with resolved vars
            iteration_vars = {**resolved_vars, **loop_vars}

            # Print loop item details in verbose mode
            if verbose:
                print(f"\n=== JSON Loop Iteration {index + 1}/{total} (Parallel) ===", file=sys.stderr)
                if isinstance(json_item, dict):
                    for key, value in json_item.items():
                        print(f"  {key}: {value}", file=sys.stderr)
                else:
                    print(f"  Item: {json_item}", file=sys.stderr)
                print(f"  Remaining: {remaining}", file=sys.stderr)
                print("", file=sys.stderr)

            # Execute task with retry logic
            task_succeeded = False
            task_failed = False
            last_error = None
            item_id = f"item-{index}"

            for attempt in range(1, max_attempts + 1):
                if on_failure == "skip" and attempt > 1:
                    break

                try:
                    if attempt > 1:
                        print(
                            f"Retrying item {index} (attempt {attempt}/{max_attempts})",
                            file=sys.stderr,
                        )

                    result = execute_single_task(
                        f"json-item-{index}",
                        task_def,
                        iteration_vars,
                        adapter,
                        workflow_config,
                        dry_run=dry_run,
                        debug=debug,
                    )

                    if result["status"] == "success":
                        task_succeeded = True
                        break
                    elif result["status"] == "failed":
                        last_error = "Task returned failed status"
                        if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                            continue
                        else:
                            task_failed = True
                            break
                    elif result["status"] == "skipped":
                        task_succeeded = True
                        break

                except ExecutionError as e:
                    last_error = e
                    if (on_failure in ["retry", "abort"]) and attempt < max_attempts:
                        print(f"Task failed: {e}. Retrying...", file=sys.stderr)
                        continue
                    else:
                        task_failed = True
                        break

            _emit_item_event(
                workflow_config,
                "loop_item_failed",
                loop_type=loop_config.get("type", "json"),
                status="failed",
                index=index,
                total=total,
                item_id=item_id,
            )
            _emit_item_event(
                workflow_config,
                "loop_item_completed",
                loop_type=loop_config.get("type", "json"),
                status="success",
                index=index,
                total=total,
                item_id=item_id,
            )
            return {
                "index": index,
                "item_id": item_id,
                "succeeded": task_succeeded,
                "failed": task_failed,
                "error": last_error,
            }

        # Execute items in parallel
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(process_item, index, json_items[index]): index
                for index in range(total)
            }

            # Collect results as they complete
            for future in as_completed(futures):
                result = future.result()
                results["iterations"] += 1

                if result["succeeded"]:
                    results["completed"].append(result["item_id"])
                elif result["failed"]:
                    results["failed"].append(result["item_id"])
                    results["status"] = "partial"

                    # Handle on-failure: abort
                    if on_failure == "abort":
                        print(
                            "Task failed. Aborting loop (on-failure: abort)", file=sys.stderr
                        )
                        results["status"] = "failed"
                        # Cancel pending futures
                        for f in futures:
                            f.cancel()
                        raise ExecutionError(f"Task failed: {result['error']}")

                    # on-failure: skip or retry or None (default)
                    if on_failure == "skip":
                        print("Task failed. Skipping (on-failure: skip)", file=sys.stderr)
                    elif on_failure == "retry":
                        print("Task failed. Continuing to next item", file=sys.stderr)
                    elif on_failure is None:
                        # Default behavior: raise error
                        results["status"] = "failed"
                        # Cancel pending futures
                        for f in futures:
                            f.cancel()
                        raise ExecutionError(f"Task failed: {result['error']}")

        return results

    def _parse_json_file(self, file_path, loop_config):
        """
        Parse JSON file and extract array using optional path.

        Args:
            file_path: Path to JSON file
            loop_config: Loop configuration with optional 'path'

        Returns:
            list: List of JSON items (may be primitives or objects)

        Raises:
            ExecutionError: If JSON parsing fails or path doesn't point to array
        """
        import json

        from .executor import ExecutionError

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ExecutionError(f"Invalid JSON in file {file_path}: {e}")
        except Exception as e:
            raise ExecutionError(f"Error reading JSON file {file_path}: {e}")

        # Extract nested array if path is specified
        path = loop_config.get("path")
        if path:
            data = self._extract_nested_array(data, path)
        else:
            # Root must be an array
            if not isinstance(data, list):
                raise ExecutionError(
                    f"JSON file must contain an array at root. Found: {type(data).__name__}. "
                    f"Use 'path' field to extract nested array."
                )

        # Add internal index to each item
        items = []
        for idx, item in enumerate(data):
            # For objects, add _index field
            if isinstance(item, dict):
                item["_index"] = idx
                items.append(item)
            else:
                # For primitives, keep as-is (will be wrapped later)
                items.append(item)

        return items

    def _parse_jsonl_file(self, file_path):
        """
        Parse JSON Lines file (one JSON object per line).

        Args:
            file_path: Path to JSONL file

        Returns:
            list: List of JSON objects

        Raises:
            ExecutionError: If any line contains invalid JSON
        """
        import json

        from .executor import ExecutionError

        items = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue  # Skip empty lines

                    try:
                        obj = json.loads(line)
                        # Add internal index
                        if isinstance(obj, dict):
                            obj["_index"] = line_num - 1
                        items.append(obj)
                    except json.JSONDecodeError as e:
                        raise ExecutionError(
                            f"Invalid JSON on line {line_num} in {file_path}: {e}"
                        )
        except Exception as e:
            if isinstance(e, ExecutionError):
                raise
            raise ExecutionError(f"Error reading JSONL file {file_path}: {e}")

        return items

    def _extract_nested_array(self, data, path):
        """
        Extract nested array using dot notation path.

        Args:
            data: JSON data structure
            path: Dot-separated path like 'users.active'

        Returns:
            list: Extracted array

        Raises:
            ExecutionError: If path is invalid or doesn't point to array
        """
        from .executor import ExecutionError

        if not path:
            return data

        parts = path.split(".")
        current = data

        for i, part in enumerate(parts):
            if isinstance(current, dict):
                if part not in current:
                    raise ExecutionError(
                        f"Path '{path}' not found. Missing key '{part}' at level {i + 1}"
                    )
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                if idx >= len(current):
                    raise ExecutionError(
                        f"Path '{path}' invalid. Index {idx} out of range at level {i + 1}"
                    )
                current = current[idx]
            else:
                raise ExecutionError(
                    f"Path '{path}' invalid at '{part}'. Current value is {type(current).__name__}"
                )

        # Final value must be a list
        if not isinstance(current, list):
            raise ExecutionError(
                f"Path '{path}' does not point to an array. Found: {type(current).__name__}"
            )

        return current

    def _wrap_primitive_item(self, value, index):
        """
        Wrap primitive values in object for consistent API.

        Args:
            value: Primitive value (string, number, boolean, null)
            index: Current iteration index

        Returns:
            dict: Wrapped object with 'value', 'type', and '_index' fields
        """
        type_name = type(value).__name__
        if value is None:
            type_name = "null"
        elif isinstance(value, bool):
            type_name = "boolean"
        elif isinstance(value, int) or isinstance(value, float):
            type_name = "number"
        elif isinstance(value, str):
            type_name = "string"

        return {
            "value": value,
            "type": type_name,
            "_index": index
        }

    def _apply_filter(self, items, filter_config):
        """
        Apply filter conditions to JSON items.

        Supports:
        - Simple filter: {key: "field", value: "expected"}
        - Multiple conditions: {conditions: [...], operator: "AND|OR"}

        Args:
            items: List of JSON items
            filter_config: Filter configuration dict

        Returns:
            list: Filtered items

        Raises:
            ExecutionError: If filter configuration is invalid
        """
        from .executor import ExecutionError

        if not filter_config:
            return items

        # Simple filter (single condition)
        if "key" in filter_config and "value" in filter_config:
            return [item for item in items if self._matches_filter(item, filter_config)]

        # Multiple conditions
        if "conditions" in filter_config:
            conditions = filter_config.get("conditions", [])
            operator = filter_config.get("operator", "AND")

            if not conditions:
                raise ExecutionError("filter.conditions cannot be empty")

            if operator not in ["AND", "OR"]:
                raise ExecutionError(f"filter.operator must be 'AND' or 'OR', got: {operator}")

            filtered = []
            for item in items:
                matches = [self._matches_filter(item, cond) for cond in conditions]

                if operator == "AND" and all(matches):
                    filtered.append(item)
                elif operator == "OR" and any(matches):
                    filtered.append(item)

            return filtered

        return items

    def _matches_filter(self, item, condition):
        """
        Check if item matches a single filter condition.

        Supports nested key access via dot notation: "address.city"

        Args:
            item: JSON item (dict or primitive wrapper)
            condition: Filter condition with 'key' and 'value'

        Returns:
            bool: True if item matches condition
        """
        key = condition.get("key", "")
        expected_value = condition.get("value")

        if not key:
            return False

        # Navigate nested keys using dot notation
        parts = key.split(".")
        current = item

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return False  # Key not found
            else:
                return False  # Can't navigate non-dict

        # Compare final value
        return current == expected_value


class CheckpointValidationError(Exception):
    """Raised when checkpoint file is invalid or corrupted."""

    pass
