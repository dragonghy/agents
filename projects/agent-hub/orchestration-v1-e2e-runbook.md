# Orchestration v1 — End-to-End Verification Runbook (Task #14)

This runbook documents how to verify the orchestration system works end-to-end **after** `feat/orchestration-v1` is merged to main and the daemon is brought back online. It is the integration test plan for Task #14.

We did NOT execute the e2e test in the development conversation because:
- The daemon was killed during the design discussion
- A real e2e requires a live ticket + real Claude API calls
- The dispatch hooks (`orchestration_tpm_dispatch.py`, `orchestration_comment_dispatch.py`) are not yet wired into the daemon's event listeners — that's the Phase 2.5 daemon-plumbing work which can land in a follow-up PR

## Pre-conditions

Before running this runbook, verify:

```bash
# 1. Branch merged to main
git -C ~/code/agents log --oneline main | head -5
# expect: feat(orchestration): ... commits visible

# 2. claude-agent-sdk installed
cd ~/code/agents/services/agents-mcp && uv pip list | grep claude-agent
# expect: claude-agent-sdk >= 0.1.72

# 3. ANTHROPIC_API_KEY available
echo "${ANTHROPIC_API_KEY:0:10}..."  # don't print full key
# expect: sk-ant-...

# 4. profiles/ directory populated
ls ~/code/agents/profiles/
# expect: developer/  housekeeper/  secretary/  tpm/

# 5. Schema includes session + profile_registry tables
sqlite3 ~/code/agents/.agents-mcp.db ".tables" | tr ' ' '\n' | grep -E '^(session|profile_registry)$'
# expect: both lines present

# 6. Daemon running
curl -s http://localhost:8765/api/v1/health
# expect: 200 OK

# 7. Profile registry populated by daemon boot
sqlite3 ~/code/agents/.agents-mcp.db "SELECT name FROM profile_registry"
# expect: developer / housekeeper / secretary / tpm
```

## Step 1 — Pick a low-stakes ticket

Pick a ticket currently at `status=3` (New) that won't cause real-world side effects if the agent runs amok. A documentation update or refactor is ideal.

```bash
mcp__agents__list_tickets status=3 limit=20
```

Note the ticket id `T`. Don't use a production-critical ticket for the first run.

## Step 2 — Manually trigger TPM auto-spawn (status 3 → 4)

```python
# Via MCP tool:
mcp__agents__update_ticket(ticket_id=T, status=4)

# Then call the dispatch hook directly:
from agents_mcp.orchestration_tpm_dispatch import maybe_spawn_tpm_for_status_change
from agents_mcp.orchestration_session_manager import SessionManager
from agents_mcp.store import AgentStore

store = AgentStore("/Users/huayang/code/agents/.agents-mcp.db")
await store.initialize()
sm = SessionManager(store, profiles_dir=Path("/Users/huayang/code/agents/profiles"))
session_id = await maybe_spawn_tpm_for_status_change(
    sm, store, ticket_id=T, old_status=3, new_status=4
)
print(f"Spawned TPM: {session_id}")
```

(Phase 2.5 will wire the hook directly into the daemon's `update_ticket` handler so this happens automatically.)

## Step 3 — Verify TPM session exists

```bash
sqlite3 ~/code/agents/.agents-mcp.db \
  "SELECT id, profile_name, status, native_handle FROM session WHERE ticket_id=$T AND profile_name='tpm'"
```

Expect: one active row with `profile_name='tpm'`, `status='active'`, `native_handle=NULL` (no LLM call yet).

## Step 4 — Add a comment, watch TPM wake up

```python
# Add a comment to the ticket:
mcp__agents__add_comment(module="ticket", module_id=T, comment="What's the next concrete step here?")

# Manually fire the comment dispatcher:
from agents_mcp.orchestration_comment_dispatch import dispatch_comment_to_tpm
result = await dispatch_comment_to_tpm(
    sm, store,
    ticket_id=T,
    comment_id=<the new comment id>,
    comment_body="What's the next concrete step here?",
    author_session_id=None,  # human author
)
print(f"Dispatched to TPM: {result}")
```

This call hits Claude. Expect:
- ANTHROPIC_API_KEY usage charge of ~$0.01-0.05 for a single TPM turn
- Latency ~5-15s
- A new entry in the session's JSONL at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`
- `session.cost_tokens_in` and `cost_tokens_out` updated
- `session.native_handle` populated with the SDK's session id

## Step 5 — Verify the TPM responded sensibly

```bash
# Inspect TPM's reply via the SDK JSONL:
cat ~/.claude/projects/*/<sdk-session-id>.jsonl | tail -5 | jq

# Or via the runner_type-aware history API once Web UI lands.
```

The TPM should produce a structured plan:
- A statement of what it understood from the comment
- A choice: handle directly / spawn subagent / post a comment / wait
- If "spawn subagent": a description of which Profile + what task

The TPM should NOT actually post a comment back to the ticket itself yet — that's Phase 2.5+ (TPM tool-use binding). For this runbook, we're verifying TPM reasoning works, not autonomous action.

## Step 6 — Test status close behavior

```python
mcp__agents__update_ticket(ticket_id=T, status=0)

await maybe_close_tpm_for_status_change(store, ticket_id=T, new_status=0)
```

Verify:

```bash
sqlite3 ~/code/agents/.agents-mcp.db \
  "SELECT status, closed_at FROM session WHERE ticket_id=$T AND profile_name='tpm'"
```

Expect: `status='closed'`, `closed_at` populated.

## Step 7 (optional) — End-to-end with subagent spawn

Once Phase 2.5 lands (TPM has tools to actually call SessionManager.spawn from within its system prompt), repeat steps 2-6 but watch the TPM spawn a Developer or Housekeeper session and observe the chain through subagent_session → comment → TPM wake → eventual ticket close.

## Failure modes & diagnostics

| Symptom | Likely cause | Fix |
|---|---|---|
| `FileNotFoundError: profile.md` on spawn | profiles/ dir not where SessionManager expects, or not git-pulled after merge | Verify `profiles_dir` in daemon init points at the actual top-level `profiles/` |
| `KeyError: 'tpm'` in profile_registry | Daemon hasn't run `ProfileLoader.scan()` since boot | Restart daemon, or call `loader.scan()` manually |
| Adapter raises `RuntimeError: missing session_id from result` | Claude SDK didn't emit a session id (network blip, malformed mock) | Retry the call; if persistent, capture the SDK's response stream and file an upstream issue |
| `session.cost_tokens_in == 0` after a real LLM call | Adapter's token extraction missed the usage event | Check `claude_adapter._extract_tokens` against the actual `ResultMessage.usage` shape |
| TPM dispatch silently does nothing | No active TPM for the ticket (closed prematurely?), or comment was posted by the TPM session itself (self-feedback skip) | Inspect `get_active_tpm_for_ticket` + the comment's `source_session_id` |
| Same comment dispatched twice → double TPM wake | Daemon's comment_created event listener has retry logic without dedupe | Add dedupe by `comment_id` at the listener level (Phase 2.5 plumbing) |
| Daemon crashes mid-LLM-call | Anthropic API error, OOM, etc. | Restart daemon; in-flight LLM call lost (the only durable state is the SDK's JSONL which the SDK only writes after final result event); next comment retries |

## What's NOT covered in v1

- **Auto-routing to non-Claude adapters** — only Claude adapter is implemented. OpenAI / Gemini come in Phase 5.
- **Web UI live streaming** — Phase 3.
- **Telegram channel sessions** — Phase 4.
- **TPM's tool-use that actually posts comments / spawns subagents** — Phase 2.5 (TPM has a system prompt instructing it but not yet the actual tool bindings; current TPM "speaks" but doesn't "act").
- **Cost dashboard** — Web UI Phase 3.
- **Cycle prevention if TPM-spawned subagent's comment triggers TPM which spawns the same subagent again** — application-level loop detection is a Phase 2.5 concern.

## When this runbook is satisfactorily green

- Steps 1-6 all complete without error
- Step 5 shows TPM reasoning that any reasonable observer would call "sensible"
- Token costs match rough expectation (~$0.01-0.10 for a basic TPM round trip)
- No regression in pre-existing dispatcher / tmux flows (the legacy paths are still on the branch unchanged in v1; we're additive)

Then `feat/orchestration-v1` has met its Phase 1 + Phase 2 acceptance bar. Phase 2.5 (daemon plumbing) and Phase 3 (Web UI) are follow-up branches.
