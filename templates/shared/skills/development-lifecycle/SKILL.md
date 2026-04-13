---
name: development-lifecycle
description: Complete development workflow — from ticket pickup to CI green. Every development task follows this lifecycle.
---

# Development Lifecycle

Every development task follows this lifecycle. Steps may be skipped for trivial tasks, but the default is to follow all steps.

## Step 1: Pickup & Plan

**Set ticket to status=4** (In Progress), then read ALL comments for context.

Before touching any code, make a plan:
- Understand the full scope of the problem
- Identify which files need to change
- Think about edge cases and potential issues
- Consider how to test the changes

**Comment on ticket:**
```
## Plan
### Problem
[1-2 sentences: what needs to happen and why]

### Approach
[Key decisions and file changes planned]

### Risks / Open Questions
[Anything uncertain]
```

## Step 2: Research & Sync

If the task involves unfamiliar territory:
- Read relevant code, docs, and existing tests
- Check if similar work was done before (search tickets, git log)
- Understand the conventions already in place

**Comment on ticket:**
```
## Research
### Findings
[What you learned that affects the plan]

### Updated Plan (if changed)
[Adjustments based on research]
```

## Step 3: Implement (in Worktree)

**Always use a git worktree** for implementation to avoid affecting the main branch or other agents.

```bash
# Create worktree
git worktree add /tmp/wt-<ticket-id> -b feat/<short-description>

# Work in the worktree
cd /tmp/wt-<ticket-id>
# ... make changes, commit incrementally ...

# When done, push the branch
git push -u origin feat/<short-description>

# Clean up worktree (but keep branch)
cd /path/to/main/repo
git worktree remove /tmp/wt-<ticket-id>
```

Commit early and often. Each commit should leave the code in a working state.

**Comment on ticket:**
```
## Implementation Complete
### Branch
`feat/<short-description>`

### Changes
- [file]: [what changed]
- [file]: [what changed]

### Commits
- abc1234: [message]
- def5678: [message]
```

## Step 4: Test

Run tests **before** creating the PR:

1. **Unit tests**: Run the project's test suite
2. **Integration / E2E tests**: If applicable, run end-to-end tests
3. **Manual verification**: For UI or API changes, verify the behavior manually

If tests fail, fix and re-test. Do not proceed with failing tests.

**Comment on ticket:**
```
## Test Report
### Tests Run
- [test suite]: [pass/fail, count]
- [manual check]: [result]

### Evidence
[Actual command output, not just "it works"]

### Issues Found & Fixed
- [issue]: [fix applied]
```

## Step 5: Pull Request

Create a PR with a clear description:

```bash
gh pr create --title "<short title>" --body "$(cat <<'EOF'
## Summary
[1-3 bullet points]

## Test Plan
- [x] Unit tests pass
- [x] Integration tests pass
- [ ] Manual verification

## Ticket
Closes #<ticket-id>

## Test Report
[Copy from Step 4]
EOF
)"
```

**Comment on ticket** with the PR URL.

## Step 6: CI Observation

After creating the PR:
1. Check CI status: `gh pr checks <pr-number>`
2. If CI fails, diagnose and fix
3. Push fixes to the same branch
4. Repeat until CI is green

**Do NOT close the session until CI is green.** If CI takes too long (>10 min), note the PR number in the ticket and let the session idle — the monitor will release it, and a future session can pick up the CI check.

## Step 7: Completion

When CI is green:
1. Mark ticket status=0 (Done)
2. Update project `claude.md` if the task produced reusable knowledge
3. Create follow-up tickets for any out-of-scope items discovered

## When to Skip Steps

| Task Type | Skip |
|---|---|
| One-line fix / typo | Skip Plan, Research, Worktree. Direct commit to main. |
| Config change | Skip Research, PR. Direct commit. |
| Complex feature | Follow all steps. |
| Bug fix | May skip Research if root cause is obvious. Always test. |

## Key Rules

- **Never commit directly to main for non-trivial changes.** Use a branch + PR.
- **Never say "tests pass" without showing output.** Evidence or it didn't happen.
- **Never close a ticket without a completion comment.** The next agent needs context.
- **Always use worktree for implementation.** Protects main branch from broken intermediate states.
