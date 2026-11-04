# Parallel Loop Execution

Agent-yaml supports parallel execution of loop iterations using the `workers` parameter. This allows processing multiple items concurrently, significantly reducing total execution time.

## Basic Parallel Execution

```yaml
loop:
  type: csv
  source: "data.csv"
  workers: 3  # Process 3 items in parallel
  columns: [id, name]

prompt: "Process {{loop.item.name}}"
```

**Result**: 10 items processed in ~4 iterations instead of 10 sequential iterations.

---

## Option 1: Directory Pool

Use existing directories, assigning them round-robin to workers:

```yaml
template-variables:
  checkout-1: ~/projects/repo-a
  checkout-2: ~/projects/repo-b
  checkout-3: ~/projects/repo-c

task:
  - parallel-review:
      loop:
        type: csv
        source: "prs.csv"
        workers: 3
        directory-pool:
          - "{{checkout-1}}"
          - "{{checkout-2}}"
          - "{{checkout-3}}"
        columns: [number, branch]
      prompt: |
        Worker {{loop.worker.id}} using {{loop.worker.directory}}

        cd {{loop.worker.directory}}
        git fetch origin {{loop.item.branch}}
        git checkout {{loop.item.branch}}
        # Work...
```

**Worker assignment**:
- Item 0 → directory-pool[0] (Backend-3)
- Item 1 → directory-pool[1] (Backend-5)
- Item 2 → directory-pool[2] (Backend-6)
- Item 3 → directory-pool[0] (Backend-3) - round-robin
- Item 4 → directory-pool[1] (Backend-5)
- etc.

**Use when**:
- You have pre-existing repo clones or directories
- You want explicit control over which directories are used
- You're not in a git repository

---

## Option 2: Git Worktrees (Recommended for Git Workflows)

Auto-create temporary git worktrees, each on a different branch:

```yaml
task:
  - parallel-review:
      loop:
        type: csv
        source: "prs.csv"
        workers: 3
        git-worktrees:
          enabled: true
          base: "{{gitroot}}/.worktrees"
          branch-field: "branch"
          name-template: "pr-{{loop.item.number}}"
          cleanup: true
        columns: [number, branch, title]
      prompt: |
        Worker {{loop.worker.id}} in worktree {{loop.worker.directory}}

        # Branch {{loop.item.branch}} already checked out!
        # No need for git checkout

        git merge origin/master --no-edit
        git push origin {{loop.item.branch}}
        # Work...
```

**What happens**:
1. Loop reads CSV (e.g., 10 PRs)
2. Creates ThreadPool with 3 workers
3. For each item:
   - Runs: `git worktree add {{gitroot}}/.worktrees/pr-147173 branch-name`
   - Sets `{{loop.worker.directory}}` to worktree path
   - Executes prompt in worktree (branch already checked out)
   - On completion: `git worktree remove {{gitroot}}/.worktrees/pr-147173` (if cleanup=true)

**Use when**:
- Working with git repositories
- Want automatic branch isolation
- Want efficient disk usage (worktrees share .git database)
- Need automatic cleanup

**Advantages over directory-pool**:
- No need for multiple repo clones (saves 15GB per clone)
- Faster checkout (instant worktree creation)
- Automatic cleanup
- Shared git database (single fetch updates all worktrees)

---

## Configuration Options

### `workers` (integer, optional, default: 1)
Number of parallel workers. Set to 1 or omit for sequential execution.

### `directory-pool` (array of strings, optional)
List of directories to assign to workers via round-robin.

**Validation**:
- All directories must exist
- Warning if pool size < workers (some workers will share directories)

### `git-worktrees` (object, optional)
Auto-create git worktrees for parallel execution.

**Fields**:
- `enabled` (boolean, required): Must be true
- `base` (string, required): Base path for worktrees (supports template variables)
- `branch-field` (string, required): CSV column containing branch name
- `name-template` (string, optional): Template for worktree directory name (default: `worker-{{loop.worker.id}}`)
- `cleanup` (boolean, optional, default: true): Remove worktrees after execution

**Validation**:
- Must be in a git repository
- `branch-field` must exist in CSV columns
- Cannot use both `directory-pool` and `git-worktrees`

---

## Worker Variables

When using `directory-pool` or `git-worktrees`, these variables are available:

- `{{loop.worker.id}}` - Worker ID (0 to workers-1)
- `{{loop.worker.directory}}` - Assigned directory or worktree path

**Without directory-pool or git-worktrees**: Worker variables are NOT injected (all workers share the same directory).

---

## Example: Docstring PR Review (Parallel)

```yaml
directory: ~/projects/example-repo-1
template-variables:
  prs_csv: "/tmp/agent-yaml-doc-prs.csv"   # normally written by an earlier task

task:
  - discover-prs:
      prompt: "Find open PRs, write to {{prs_csv}}"

  - parallel-review:
      loop:
        type: csv
        source: "{{prs_csv}}"
        workers: 3
        git-worktrees:
          enabled: true
          base: "{{directory}}/.docstring-review-worktrees"
          branch-field: "branch"
          name-template: "pr-{{loop.item.number}}"
          cleanup: true
        columns: [number, branch, title]
      prompt: |
        # Worktree {{loop.worker.directory}} (branch already checked out)
        # Merge master, run council, implement fixes, commit, push
```

**Performance**:
- 10 PRs × 11 min each = 110 minutes sequential
- With 3 workers: ~37 minutes (3x speedup)
- With 5 workers: ~22 minutes (5x speedup)

---

## Error Handling

Parallel execution respects the `on-error` setting:

```yaml
on-error: continue  # Continue processing remaining items if one fails

loop:
  workers: 3
```

**Behavior**:
- If item 2 fails, items 3, 4, 5... continue processing
- Failed items are logged
- Worktree cleanup still happens (in finally block)

---

## Limitations

1. **Shared global timeout**: All workers share the same per-task timeout from `cli-agent-config`
2. **No worker-specific variables**: All workers use the same template variables (except loop.worker.*)
3. **Directory pool round-robin only**: No custom assignment strategies
4. **Git worktrees require CSV column**: Must have a branch field in CSV

---

## Migration from Sequential to Parallel

**Before** (sequential):
```yaml
- review-loop:
    loop:
      type: csv
      source: "prs.csv"
    prompt: "Review PR {{loop.item.number}}"
```

**After** (parallel with directory pool):
```yaml
- review-loop:
    loop:
      type: csv
      source: "prs.csv"
      workers: 3
      directory-pool: [Backend-3, Backend-5, Backend-6]
    prompt: "cd {{loop.worker.directory}} && Review PR {{loop.item.number}}"
```

**After** (parallel with worktrees):
```yaml
- review-loop:
    loop:
      type: csv
      source: "prs.csv"
      workers: 3
      git-worktrees:
        enabled: true
        base: ".worktrees"
        branch-field: "branch"
    prompt: "Review PR {{loop.item.number}} (already in worktree)"
```

---

## Best Practices

1. **Start with 3 workers** - Balance parallelism with resource usage
2. **Use git-worktrees for git workflows** - Much more efficient than multiple clones
3. **Enable cleanup** - Remove worktrees after completion to save disk space
4. **Set appropriate timeouts** - Each worker gets the same timeout, so size for the slowest item
5. **Monitor resource usage** - 5+ workers may strain CPU/memory depending on task complexity
