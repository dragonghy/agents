# Orchestration v1 — Multi-Agent Demo Transcript

**Date**: 2026-05-02 23:26 PDT
**TPM session**: `sess_9dec80c6d27728cebf2fe6`

## Scenario

- **Ticket ID**: 999100 (synthetic — not in production Leantime)
- **Headline**: Add index on orders.user_id to fix slow OrderHistoryView query

```
The OrderHistoryView page is loading in 3-4 seconds for users with more than ~500 orders. Profiling shows the query SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 50 is doing a full table scan. We probably need an index, but want a second pair of eyes before shipping.
```

## Totals

- **TPM turns**: 3
- **Tokens in**: 404,028 (includes cache reads)
- **Tokens out**: 8,586
- **Estimated cost**: $1.3409 USD (at Sonnet $3 in / $15 out per 1M)

## Subagent sessions spawned by TPM

| Session | Profile | Status | Tokens in | Tokens out |
|---|---|---|---|---|
| `sess_9dec82982ebdf527ce7316` | developer | active | 125,094 | 2,056 |
| `sess_9dec8178e9eca0ea76c1c5` | architect | active | 20,507 | 1,040 |

## TPM turn-by-turn

### Turn 1

**User input:**

```
Investigate this slow query and propose a fix. The slow query is:
    SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 50
The orders table has ~5M rows. Decide whether an index is the right fix, design it if so, and report back via a ticket comment.
```

**TPM assistant text:**

```
I need to load the TPM orchestration tools to handle this ticket.Analysis complete. The architect identified the root cause: without indexes, the database performs full table scans across 5M rows, then sorts all matching results.

**Recommended fix**: Create a composite index on `(user_id, created_at DESC)`:
```sql
CREATE INDEX idx_orders_user_created ON orders(user_id, created_at DESC);
```

This design allows the database to (1) seek directly to the user's partition, (2) read pre-sorted rows, and (3) stop after 50, eliminating both the scan and sort overhead.

Trade-offs: adds write overhead on inserts/updates, but acceptable for read-heavy workloads. Should verify with `EXPLAIN` after creation.

The full analysis has been posted to ticket #999100.
```

_Tokens: in=93,848 out=2,623_

### Turn 2

**User input:**

```
Update: I see your previous response. What's the next concrete tool call? If the work is done, close the ticket. If you're waiting on something, post a comment explaining what and mark the ticket Blocked. Otherwise, keep coordinating.
```

**TPM assistant text:**

```
Ticket marked **Blocked**. The investigation and design are complete, but implementation can't proceed—the developer found no `orders` table in this codebase. Posted a comment explaining we need clarification on whether this is a real database in another project or a hypothetical scenario. Awaiting Human input.
```

_Tokens: in=107,623 out=1,865_

### Turn 3

**User input:**

```
Update: I see your previous response. What's the next concrete tool call? If the work is done, close the ticket. If you're waiting on something, post a comment explaining what and mark the ticket Blocked. Otherwise, keep coordinating.
```

**TPM assistant text:**

```
The ticket is already marked Blocked. But reconsidering: if this was a test scenario for investigation only, the investigation is complete. No further tool call is needed—the ticket is in its terminal state (Blocked, waiting on external input about which database to implement against).

However, if you're signaling this was purely an investigation task with no real implementation expected, then I should close it:Ticket #999100 closed as Done. The investigation and proposal are complete and documented in the ticket comments.
```

_Tokens: in=56,956 out=1,002_

## Final ticket state

- **Status**: 0
- **Comments posted**: 2

### Comments

**1. comment_id=1** (author=`tpm:sess_9dec80c6d27728cebf2fe6`)

```
## Query Analysis Complete

**Problem**: The query `SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 50` is performing full table scans on a 5M-row table, then sorting results before returning 50 rows.

**Recommended fix**: Add a composite index:
```sql
CREATE INDEX idx_orders_user_created ON orders(user_id, created_at DESC);
```

**Why this design**:
- Column order: `user_id` first (equality filter) → `created_at` second (sort operation)
- Composite beats separate indexes: allows DB to seek to user partition AND read pre-sorted results
- `DESC` matches query sort direction for optimal index scan

**Trade-offs**:
- Write overhead: every INSERT/UPDATE to orders will update this index (acceptable for read-heavy workloads)
- Assumes good `user_id` cardinality distribution... [+122 chars]
```

**2. comment_id=2** (author=`tpm:sess_9dec80c6d27728cebf2fe6`)

```
## Implementation blocked

The developer cannot proceed because there is no `orders` table in the current codebase (agent-orchestrator or trading projects). 

**Investigation complete**:
- ✓ Root cause identified (full table scan + sort on 5M rows)
- ✓ Solution designed (composite index on user_id, created_at DESC)
- ✓ Trade-offs documented

**Blocked on**:
- Which project/database should this index be applied to?
- Is this a hypothetical scenario (analysis-only), or is there a real `orders` table in a different codebase?

Awaiting clarification to proceed with implementation.
```

## What worked

- The Claude Agent SDK's `create_sdk_mcp_server` + `@tool` decorator surface dropped in cleanly. No fallback to a stdio MCP subprocess was needed.
- The TPM correctly chose `architect` for the diagnosis turn and `developer` for the implementation turn based purely on the Profile descriptions in `profiles/<name>/profile.md` frontmatter — no extra prompt-engineering required.
- The `tpm:<session_id>` author tag on `post_comment` calls naturally feeds the comment-dispatch self-feedback skip (`dispatch_comment_to_tpm` already filters on it).
- The "tool, don't talk" anti-pattern callout in the TPM prompt was effective. The TPM's assistant text was short summaries of what its tool calls had already done, not narration of what it intended to do.
- All four tools were exercised: `spawn_subagent` (twice — architect + developer), `post_comment` (twice — analysis + blocked-status), `mark_ticket_status` (twice — Blocked then Done). `push_message` was not called in this run because each subagent's first response was already informative enough; that's a Profile-decision behavior, not a wiring gap.
- Real subagents were spawned with proper `parent_session_id` and showed up in `list_sessions(ticket_id=999100)` post-run; their token counts were captured and added to the totals.

## What didn't / paper-cuts

- The TPM emits a small prelude before its first tool call ("I need to load the TPM orchestration tools to handle this ticket."). Harmless but clutters the assistant text. Could be dampened by tightening the prompt.
- On turn 3 the TPM called `mark_ticket_status(999100, 0)` despite the ticket already being status=1 (Blocked). It interpreted the follow-up nudge as "you can close the ticket if the work is done", which is defensible but stricter coordinators would say "status is terminal, no action".
- `AgentStore.list_sessions` doesn't support a `parent_session_id` filter; the demo had to filter in Python. Trivial follow-up to add a column-filter.
- Comment text in this transcript is truncated at 800 chars via the demo's `truncate()` helper. The untruncated payload is in the sibling JSON dump.
- The TPM seamlessly transitioned through Blocked → Done in two consecutive turns. Whether this is correct behavior or a "should have stayed Blocked" depends on what the kickoff message implied. Future demos should use prompts that pin the desired terminal state more explicitly.

## Anything weird

- The kickoff scenario described an `orders` table that doesn't actually exist in this repo. The Developer subagent — given the `agent-hub` MCP and Read access — correctly noticed the table was absent and reported "can't proceed; no such table." This is exactly the action-vs-effect verification (CLAUDE.md pitfall #14) we wanted: subagents are *not* hallucinating success; they're checking what's actually there. Good signal that the wiring is forwarding real toolchains, not just text.
- Token counts include cache-read tokens (the SDK rolls them into `input_tokens` for cost purposes), which inflates the `tokens_in` figure compared to a simple "new content" measure. Cost estimate uses Sonnet input rate ($3/1M) for all of `tokens_in`; in practice cache reads are billed cheaper, so the $1.34 figure is an upper bound.

## Reproduction

```
uv run --project services/agents-mcp \
  python services/agents-mcp/scripts/orchestration_demo.py \
  --max-turns 6
```

Auth: SDK picks up keychain credentials via the `claude` CLI, so any account that's logged in via `claude login` can rerun this. Synthetic ticket lives in a tmp SQLite DB under `/tmp/orch-demo-*/`; nothing touches the real `.agents-tasks.db`.
