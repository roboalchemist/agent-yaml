# Example Service Docstring Update Workflow

## Overview
This workflow automatically updates all endpoint docstrings in example-service to follow the RFC standard. It processes 480+ endpoints, creating one branch and PR per owner.

## Key Features

### Resume Support
The workflow is fully resumable - you can stop and restart it at any time:

1. **Branch Creation**: Checks if branches already exist before creating
2. **Docstring Updates**: Skips endpoints that already have proper docstrings
3. **PR Creation**: Checks if PRs already exist before creating new ones

### Direct gh CLI Usage
Phase 3 uses `gh pr create` commands directly with:
- Automatic PR existence checking
- Proper branch and base configuration
- Comprehensive PR descriptions with file lists

### No Timeout
Removed timeout limits - the workflow runs until completion (estimated several hours for 480 endpoints).

## Workflow Phases

### Phase 1: Create ALL Branches and Draft PRs (BEFORE processing endpoints)
```
1. Extract unique owners using csvtool:
   csvtool col 6 example-service/docs/endpoint_owners.csv | tail -n +2 | sort -u

2. Slugify each owner (lowercase, hyphens)

3. For each owner:
   BRANCH CREATION:
   - Checks if branch docstring-update/{owner-slug} exists
   - Creates branch if needed, otherwise fetches latest
   - Pushes to remote

   DRAFT PR CREATION:
   - Checks if PR already exists using gh pr list
   - If not exists: Creates DRAFT PR with placeholder body
   - If exists: SKIP
```

### Phase 2: Docstring Updates (CSV Loop - processes 480 endpoints)
```
For each endpoint in example-service/docs/endpoint_owners.csv:
  1. Switches to owner's branch
  2. Checks if docstring already updated (for resume)
  3. If already updated: SKIP
  4. If not updated:
     - Reads docstring standard
     - Updates/creates comprehensive docstring
     - Commits: "Update docstring for {function} in {file}"
     - Pushes immediately to existing branch
```

### Phase 3: Update PRs with Endpoint Lists, Add Reviewers, and Mark Ready
```
For each branch docstring-update/*:
  1. Extract owner name from branch
  2. Filter CSV to get ALL endpoints for this owner
  3. Build formatted list: "{Methods} {Route} → {Function} in {File}"
  4. Get PR number using gh pr list
  5. Update PR body with complete endpoint list using gh pr edit
  6. Mark PR ready for review: gh pr ready {PR-number}
  7. Try to add owner as reviewer:
     a. Try common username mappings
     b. If unclear: gh api search/users to find username
     c. If found: gh pr edit --add-reviewer {username}
     d. If not found: SKIP (let GitHub auto-suggest)
```

### Phase 4: Final Unified Summary
```
- Lists all PRs with stats
- Shows commit counts per branch
- Creates SINGLE summary file: docstring-update-summary.txt
```

## Usage

### First Run
```bash
cd ~/github/agent-yaml-main
agent-yaml run tasks/example-service-docstring-update.yaml --verbose
```

### Resume After Interruption
```bash
# Same command - workflow automatically detects existing work
agent-yaml run tasks/example-service-docstring-update.yaml --verbose
```

### Dry Run (Validation Only)
```bash
agent-yaml run tasks/example-service-docstring-update.yaml --dry-run
```

## Resume Logic

### Branch + PR Check (Phase 1)
```bash
# For each owner extracted via csvtool:
git branch -a | grep "docstring-update/{owner-slug}"
# If found: skip creation, fetch latest
# If not found: create and push

gh pr list --repo example-org/example-repo \
  --head docstring-update/{owner-slug} \
  --base master \
  --json number
# If PR exists: SKIP
# If PR not exists: CREATE as DRAFT
```

### Docstring Check (Phase 2)
```bash
# For each endpoint:
1. Read current docstring
2. Check if it follows standard (has all sections)
3. Check git log: git log -1 --oneline -- {file} | grep "{function}"
# If complete: SKIP
# If incomplete: UPDATE
```

### PR Update (Phase 3)
```bash
# For each branch:
1. Filter CSV for owner's endpoints
2. Update PR body with full endpoint list
3. Mark PR ready: gh pr ready {PR-number}
4. Find GitHub username:
   a. Try common mappings
   b. If unclear: gh api search/users --field q="{Owner Name}"
   c. If found: gh pr edit --add-reviewer {username}
   d. If not found: SKIP reviewer assignment (let GitHub auto-suggest)
```

## Configuration

### Source Files
- **Endpoints CSV**: `~/projects/example-repo/example-service/docs/endpoint_owners.csv`
- **Docstring Standard**: `~/projects/example-repo/example-service/docs/docstring_standard.md`

### Base Branch
- **Base**: `master`
- **New Branches**: `docstring-update/{owner-slug}`

### Output Files
- **SINGLE UNIFIED FILE**: `example-service/docs/docstring-update-summary.txt` - Complete summary with:
  - All PRs created with URLs
  - Commit counts per branch
  - Total endpoints processed
  - Workflow timestamps

## Error Handling
- **Strategy**: `on-error: continue`
- **Impact**: One failed endpoint doesn't stop the entire workflow
- **Commits**: Each commit is atomic and pushed immediately
- **Resume**: Workflow can be restarted at any time

## Expected Runtime
- **480 endpoints** × ~30-60 seconds each = **4-8 hours**
- **No timeout** - runs until completion
- **Progress tracked** in git commits (can monitor with `git log`)

## Monitoring Progress

### Check Branches
```bash
cd ~/projects/example-repo
git branch -a | grep docstring-update
```

### Check Commits on a Branch
```bash
git checkout docstring-update/your-handle
git log --oneline | head -20
```

### Check PRs
```bash
gh pr list --head "docstring-update/*" --base master
```

## Troubleshooting

### Workflow Interrupted
- Simply re-run the same command - resume logic handles existing work

### Git Authentication
- Ensure `gh auth status` shows authenticated
- Ensure git credentials are configured

### Missing Files
- Ensure base branch `master` exists and is up to date
- Ensure CSV files exist at specified paths

## Files Modified
This workflow modifies:
- Branch creation: No files
- Docstring updates: Python files in `example-service/` (endpoint definitions)
- PR creation: No files (creates PRs via GitHub API)

## Safety Features
1. **Read-only docstring check**: Skips already-updated functions
2. **Atomic commits**: Each endpoint is a separate commit
3. **Immediate push**: Progress never lost
4. **PR existence check**: Prevents duplicate PRs
5. **Branch existence check**: Prevents duplicate branches
6. **Error isolation**: `on-error: continue` prevents cascade failures
