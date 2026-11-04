# Docstring PR Review Workflow

## Overview
This workflow automates the review and fixing of docstring PRs using a council of AI tools to ensure quality and consistency.

## What It Does

### Single Combined Loop Per PR
For each PR, in one continuous operation:
1. **Council Review**: Uses `/ask-council` to get consensus from multiple AI tools
2. **Implement Fixes**: Immediately checks out branch, applies fixes, commits, and pushes
3. **Log Ambiguities**: Records any standard ambiguities to the ambiguities file
4. **Cleanup**: Deletes temporary review file before moving to next PR

### Dynamic PR Discovery
Instead of a hardcoded list, the workflow searches GitHub for:
- Open PRs in `example-org/example-repo`
- Title contains "Update docstrings for"
- Created by the configured user
- Auto-merge is NOT enabled

## Workflow Phases

### Phase 1: Discover PRs
```
1. Creates workspace directory
2. Searches GitHub using gh CLI
3. Filters out PRs with auto-merge enabled
4. Writes matching PRs to CSV file
```

### Phase 2: Review and Fix (single loop over CSV)
```
For each PR:
  Step 1: Merge latest master into PR branch
  Step 2: Run /ask-council to review docstrings
  Step 3: If issues found → implement fixes, autofix, commit, push
  Step 4: Append ambiguities to ~/Desktop/docstring_standard_ambiguities.md
  Step 5: Return to master
```

### Phase 3: Summary
```
Creates summary of all PRs reviewed and ambiguities found
```

## Usage

### Run the Workflow
```bash
cd ~/github/agent-yaml
agent-yaml run tasks/docstring-pr-review.yaml --verbose
```

### Dry Run (Validation)
```bash
agent-yaml run tasks/docstring-pr-review.yaml --dry-run
```

## Configuration

### Template Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `workspace` | `{directory}/.docstring-review-workspace` | Working directory for intermediate files |
| `github-user` | `your-handle` | GitHub username to filter PRs by author |
| `docstring-standard` | `example-service/docs/docstring_standard.md` | Path to docstring standard |
| `ambiguities-file` | `~/Desktop/docstring_standard_ambiguities.md` | Where to append ambiguities |

### Customizing the Search
To change the PR search criteria, modify the `discover-prs` task:
```yaml
gh pr list --repo example-org/example-repo \
  --author "{{github-user}}" \
  --state open \
  --search "Update docstrings for in:title" \
  --json number,title,headRefName,url,autoMergeRequest
```

## Output Files

| File | Description |
|------|-------------|
| `{workspace}/open-docstring-prs.csv` | List of PRs to review |
| `{workspace}/summary.md` | Final summary |
| `~/Desktop/docstring_standard_ambiguities.md` | Accumulated ambiguities (persists across runs) |

**Note**: Temporary review files (`pr-{number}-review.md`) are created and deleted during each PR's processing.

## Error Handling
- `on-error: continue` - One failed PR doesn't stop the workflow
- Each PR is processed independently in a single pass (review → fix → cleanup)

## The Council Review Prompt
The council examines:
1. **Conformance**: Do docstrings follow the standard format?
2. **Accuracy**: Is the content of each docstring accurate?
3. **Ambiguities**: Where did council members disagree?

Results include:
- Numbered list of deviations (with agreement count)
- Proposed fixes
- Standard ambiguities that caused disagreement

## Ambiguities File Format
```markdown
## PR #147192 - Update docstrings for feature_flags_api.py
Reviewed: 2025-01-28T23:45:00-08:00

- Whether to include return type in docstring when also using type hints
- How to document optional parameters vs required parameters
- Whether to include example usage for simple endpoints

---
```
