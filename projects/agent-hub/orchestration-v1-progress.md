# Orchestration v1 — Progress Journal

> Append-only log of work done on `feat/orchestration-v1`.
> Each commit gets one entry. Most-recent at the bottom.
> If your context was lost, read AUTONOMY-CHARTER.md, then this file, then resume.

## State summary (kept current at the top)

- **Branch**: `feat/orchestration-v1` (off `main` post-DAG-merge)
- **Current Phase**: 1 (schema done; Adapter + Profile loader + 4 profiles + session manager next)
- **Tasks**: 14 total; #5/#6/#7 done; #8 (Adapter) is up next
- **Open blockers**: none
- **apps/console/ decision**: partial rewrite (keep tickets/cost/briefs/workspaces + Vite+FastAPI scaffold; replace agent-named pages with Profile/Session/TPM views; reconcile against `services/agents-mcp/src/agents_mcp/web/api.py`). Recorded in `apps-console-survey-2026-05-02.md`.

## Entry log (oldest → newest)

### 2026-05-02 — `7a89aa1` — Phase 0 commit 1: design + research notes

**What**: First commit on the branch. Three files dropped in:
- `projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md` (full design doc, ~1100 lines)
- `projects/agent-hub/research/paperclip-review-2026-05-02.md` (architectural review of paperclip)
- `projects/agent-hub/research/claude-sdk-session-model-2026-05-02.md` (SDK research findings)

**Why**: Capture the discussion-derived design before any code. Future readers (including future-me) can read these to understand intent without re-deriving.

**Next**: Survey `apps/console/` (existing read-only Web Console from PR #22) to decide lift vs. rewrite. Then start Phase 1 schema work.

---

### 2026-05-02 — `294cef8` — Phase 0 commit 2: autonomy charter + this journal

**What**: Two files to support autonomous long-running work:
- `projects/agent-hub/AUTONOMY-CHARTER.md` — decision rules + escalation criteria + recovery protocol
- `projects/agent-hub/orchestration-v1-progress.md` — this file

**Why**: Human is unavailable for an extended period; needs a system that persists my mandate through context compaction. Charter codifies "decide, don't ask" with explicit escalation criteria. Journal is the resume-from-anywhere recovery file.

**Next**: Survey `apps/console/` to inform Phase 3 decisions. Then schema work (Task #7).

---

### 2026-05-02 — Subagent A — apps/console/ survey (Task #6 complete)

**What**: Background subagent surveyed `apps/console/` end-to-end and produced
`projects/agent-hub/research/apps-console-survey-2026-05-02.md`.

**Findings**: Vite + React + TypeScript SPA, ~2000 LOC, polling-only, no auth, FastAPI backend at `apps/console/api/`. Pages tied to deprecated primitives (AgentPanel, AgentDetail, TmuxStream, agents.yaml-driven `/api/agents`, P2P inbox/sent) are unsalvageable in the new model. Pages tied to enduring primitives (TicketBoard, CostDashboard, BriefHistory, workspaces) plus the Vite + FastAPI + Makefile + RO-SQLite + pricing scaffold are reusable.

**Decision**: Partial rewrite. Keep scaffold + tickets/cost/briefs/workspaces; throw out everything agent-named; add Profile registry + Session view + TPM/comments-as-event-stream views. Reconcile with `services/agents-mcp/src/agents_mcp/web/api.py` (1049-line older sibling) to end up with one Web UI codebase rather than two.

**Next**: Schema work (Task #7).

---

### 2026-05-02 — `9a0935c` — Phase 1 part 1: session + profile_registry schema (Task #7 complete)

**What**:
- Added `session` and `profile_registry` tables to `_SCHEMA` in `store.py`.
- 12 new `AgentStore` methods: `create_session`, `get_session`, `update_session_native_handle`, `add_session_cost`, `close_session`, `list_sessions`, `get_active_tpm_for_ticket`, `upsert_profile_registry`, `get_profile_registry`, `list_profile_registry`, `touch_profile_used`.
- 16 new tests in `tests/test_orchestration_session.py` (sync style, matches `test_ticket_dependencies.py` convention, no pytest-asyncio dep).
- Full suite: 166/166 passing (excluding pre-existing `test_message_filter.py` ordering flake).

**Why**: Foundation for everything else in Phase 1. Adapter, session manager, TPM dispatch all need these tables to exist + their CRUD to be reliable.

**Decisions made along the way**:
- No `session_message` table — Adapter native storage (Claude SDK's JSONL) is the source of truth for conversation history. Application asks Adapter `render_history(session_id)` when needed.
- `binding_kind` is a CHECK-constrained enum at the DB level (ticket-subagent / human-channel / standalone). Catches typos at insert time.
- `get_active_tpm_for_ticket` filters on `parent_session_id IS NULL` — the TPM is the root of the per-ticket session tree, not its descendants.
- Profile registry is a discovery cache; `file_hash` lets us detect file changes and re-load, but Profile content itself stays in the .md file as source of truth.

**Next**: Task #8 — Adapter interface + Claude adapter (`claude-agent-sdk-python`). Need to install the SDK package and design the protocol so future adapters can drop in cleanly.
