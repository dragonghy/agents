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

---

### 2026-05-02 — Phase 1 part 2: Profile loader + 4 starting Profiles (Tasks #9 + #10 complete)

**What**:
- New module `services/agents-mcp/src/agents_mcp/profile_loader.py` — `ProfileLoader` class that walks `profiles/<name>/profile.md`, parses frontmatter (YAML) + body, and reconciles against the `profile_registry` table. Hash-aware: unchanged files yield `"unchanged"` so `loaded_at` only ticks on real changes. Bad files are logged and surfaced as `"errored"` results without clobbering an existing registry row. Standalone `load_profile(name, profiles_dir)` function returns a `Profile` dataclass for session-creation-time reads.
- Imports `Profile` / `ProfileParseError` from `agents_mcp.adapters.base` (Task #8's interface). The dataclass picked the all-keyword construction path so Task #8's later refinement to default-value `description`/`file_path`/`file_hash` was non-breaking.
- 19 new tests in `tests/test_profile_loader.py` covering parse success, every malformed-frontmatter case (missing delimiters, missing required fields, malformed YAML, bad list types, empty body), hash determinism, and the four `scan()` outcomes (`loaded` / `updated` / `unchanged` / `errored`) plus the "preserve existing row when new file is malformed" guarantee. Hermetic — synthetic profile files in tmp_path, fresh AgentStore on tmp sqlite.
- Four starting Profiles under `profiles/<name>/profile.md`:
  - `tpm` — per-ticket coordinator (1 page); knows the four ticket statuses, the comments-only event source, and that subagent private content is invisible.
  - `developer` — code work in this codebase (1.5 pages); reads `claude.md` first, follows the development-lifecycle skill, calls out pitfalls #10 / #13 / #14 by number.
  - `housekeeper` — daily-life ops (1.5 pages); covers WeChat focus etiquette, FDA-on-terminal pitfall #15, attributedBody decode-failure pitfall #16, and the ok=True ≠ delivered verification rule.
  - `secretary` — front-door generalist for Telegram + Web UI (1 page); the four-shapes routing model (small thing / daily-life / ticket-driven / bigger-than-chat) and the explicit "you replace what admin used to do" framing.
- Each profile has a "References" section pointing back to the relevant skills + claude.md pitfalls.
- Tests passing: 19/19 new + 81/81 across the four nearby suites I exercised (profile_loader, orchestration_session, ticket_dependencies, workspaces). No regressions.

**Why**: Profile registry is the discovery layer everything else in Phase 1 reads. Without `scan()` populating `profile_registry`, the session manager (Task #11) has nothing to look up; without the four starting Profile bodies, there's nothing to actually run. The hand-written prompts establish the conventions for future Profiles (terse, references-section-at-end, claude.md pitfalls cited by number).

**Decisions made along the way**:
- Used PyYAML for frontmatter parsing — already a dep (`pyproject.toml`), keeps the loader compact (~80 lines of parse logic vs. a hand-rolled parser).
- `_parse_profile_text()` is strict about both delimiters and required fields rather than recovering silently. Silent acceptance hides typos; loud failure is surfaced via `ProfileParseError` and the loader's `"errored"` result code.
- When a re-scan finds a malformed file replacing a previously-good one, the old registry row is preserved untouched. Rationale: a bad edit shouldn't blow away the daemon's working view; a separate test pins this behavior.
- `scan()` returns a list (not a dict) so the caller can see order and detect the rare case where the same name appears twice on disk (would manifest as two consecutive entries; the upsert just clobbers, which is correct).
- `Profile` is a frozen dataclass with `tuple[str, ...]` for the list fields so it stays hashable / comparable for tests.
- Coordinated against Task #8's parallel work: the `Profile` dataclass now lives in `agents_mcp.adapters.base` (their commit landed locally between my schema reads and the loader implementation). My loader uses keyword-only construction so the field-default reorder Task #8 made was non-breaking.

**Next**: Task #11 — session manager. With Profile in place, the manager can load a Profile by name and hand it (plus session metadata) to the Adapter for the first turn.
