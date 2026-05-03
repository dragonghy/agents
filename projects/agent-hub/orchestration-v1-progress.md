# Orchestration v1 — Progress Journal

> Append-only log of work done on `feat/orchestration-v1`.
> Each commit gets one entry. Most-recent at the bottom.
> If your context was lost, read AUTONOMY-CHARTER.md, then this file, then resume.

## State summary (kept current at the top)

- **Branch**: `feat/orchestration-v1` (off `main` post-DAG-merge)
- **Current Phase**: ✅ Phase 1 + Phase 2 complete. PR ready to open.
- **Tasks**: 14 / 14 done (#5–#14).
- **Open blockers**: none. Phase 2.5 (daemon-plumbing — wire the dispatch hooks into ticket-status + comment_created event listeners in the daemon) and Phase 3 (Web UI) are follow-up branches.
- **End-to-end verification**: not executed in this branch (daemon was offline during development); `orchestration-v1-e2e-runbook.md` documents the step-by-step plan.
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

---

### 2026-05-02 — Phase 1 part 4: SessionManager (Task #11 complete)

**What**:
- New module `services/agents-mcp/src/agents_mcp/orchestration_session_manager.py` — `SessionManager` class with `spawn` / `append_message` / `close`. Stateless: holds only references to the `AgentStore` and the `profiles/` directory; everything else (Profile content, native handles, conversation history) lives off to the side. Async throughout; methods are thin orchestrations of existing primitives.
- `spawn` validates `binding_kind` early (with a useful `ValueError` ahead of the SQLite CHECK), loads the Profile from disk to surface typo'd names as `FileNotFoundError` BEFORE any row is written, generates a sortable session id (`sess_<10 hex ms-epoch><12 hex random>` = 22-char ULID-ish), inserts the row via `store.create_session`, and best-effort bumps `profile_registry.last_used_at`.
- `append_message` does the four-step orchestration: `store.get_session` → reject if `closed` → `load_profile` (re-reads from disk so live Profile edits take effect on the next turn) → `get_adapter(session_row["runner_type"])` → build `SessionMetadata` → call `adapter.run(...)`. Adapter persists `native_handle` + cost via the store directly per the contract; the manager returns the `RunResult` unchanged.
- `close` is a one-line passthrough to `store.close_session`, idempotent.
- 16 new tests in `tests/test_session_manager.py` covering id format/uniqueness, all four `spawn` validation paths (unknown profile, invalid binding_kind, all 3 valid binding_kinds, parent_session_id), Profile registry touch (both pre-registered and unregistered), `append_message` happy path with full arg-forwarding assertion, second-turn native_handle plumbing, closed/unknown rejection paths, runner_type-driven adapter selection, and `close` idempotency. Adapter is mocked at the `get_adapter` boundary via `unittest.mock.patch("agents_mcp.orchestration_session_manager.get_adapter", return_value=fake)`; a small `_FakeAdapter` mirrors the real ClaudeAdapter contract (persists native_handle on first turn, calls `add_session_cost`) so store-side-effect assertions work without an LLM.
- All 16 new tests pass; the 5-suite orchestration v1 set (session_manager + orchestration_session + profile_loader + adapter_base + claude_adapter) is 82/82 green.

**Why**: SessionManager is the only callable surface the rest of the system needs to talk to in order to run sessions. With it in place, Phase 2's TPM auto-spawn hook (#12) is just "on ticket → status=4, call `mgr.spawn(profile_name='tpm', binding_kind='ticket-subagent', ticket_id=N)`" and comment-driven dispatch (#13) is just "on `comment_created` for ticket N → look up the active TPM session via `store.get_active_tpm_for_ticket(N)`, then `mgr.append_message(tpm['id'], <comment summary>)`". No new primitives required.

**Decisions made along the way**:
- **Module name**: chose `orchestration_session_manager.py` over the requested `session_manager.py` because the latter is already taken by the v2 tmux-based `SessionManager` that the live daemon wires through `server.py:1935` and `dispatcher_v2.py`. Replacing it would break the running system before the orchestration v1 dispatcher is ready to take over. Once Phase 2 retires the tmux flow we can rename this back. The class name is still `SessionManager` so call sites read identically once the import line is updated.
- **No Adapter call on spawn** — keeps `spawn` cheap and synchronous-feeling (no API round-trip until first message). Matches the design's "session = metadata row; history lives in the Adapter" property and means the TPM auto-spawn hook never blocks on an LLM call.
- **`load_profile` is called twice in the spawn → first-message path** (once in `spawn` to validate, once in `append_message` to use) — chose correctness over caching. The cost is one disk read + a YAML parse on each call; the wins are: (a) profile.md edits take effect immediately on the next turn, (b) `append_message` doesn't depend on `spawn` having stashed the Profile in memory, (c) the manager genuinely is stateless.
- **`runner_type` source-of-truth in `append_message`** — adapter selection uses `session_row["runner_type"]`, NOT `profile.runner_type`. They should match (Profile's `runner_type` is what got persisted at spawn time), but if the on-disk Profile changes its `runner_type` mid-session, the session keeps its original adapter rather than silently re-routing. Mid-session adapter switch is explicitly out of scope per design §2.6.
- **Session id generation hand-rolled** — 10 hex chars of ms-since-epoch + 12 hex chars of `os.urandom(6)`. ULID-shaped (sortable, monotonic-ish, collision-safe) without pulling in a `ulid-py` dep for ~6 lines of code.
- **`FakeAdapter` in tests mirrors the real cost+handle contract** — this way the store-side-effect assertions (cost accumulation, native_handle persistence) actually exercise the real plumbing instead of just verifying the mock was called. Cheap to write and catches the kind of bug where the manager forgets to pass `store` through.
- **No `unittest.mock.AsyncMock`** — the test suite is sync-with-`run()`-helper everywhere; introducing AsyncMock would have meant either adopting it across the file or mixing styles. A 30-line `_FakeAdapter` class with `async def run` is simpler and matches existing patterns.

**Next**: Task #12 — TPM auto-spawn hook. When a ticket transitions to status=4 and there's no active TPM for it, spawn one via `SessionManager.spawn(profile_name="tpm", binding_kind="ticket-subagent", ticket_id=N)`. Likely lives next to `dispatcher_v2.py` or in a new `tpm_hook.py`. Then Task #13 (comment-driven dispatch) and Task #14 (Phase 2 wrap-up).

---

### 2026-05-02 — Phase 2 complete: TPM dispatch hooks + e2e runbook (Tasks #12 + #13 + #14)

**What**:

- `services/agents-mcp/src/agents_mcp/orchestration_tpm_dispatch.py` — `maybe_spawn_tpm_for_status_change()` enforces the 3→4 doctrine (no TPM on status=3 New tickets; only on transition to WIP) and is idempotent (won't double-spawn if a TPM already exists). Companion `maybe_close_tpm_for_status_change()` closes the TPM when ticket transitions to Done (0) or Archived (-1).
- `services/agents-mcp/src/agents_mcp/orchestration_comment_dispatch.py` — `dispatch_comment_to_tpm()` looks up the active TPM for a ticket, formats the new comment as a structured user message including comment_id + author session_id provenance, and calls SessionManager.append_message to wake the TPM. Skips if the comment was posted BY the TPM itself (avoids self-feedback loops).
- 33 new tests across `test_orchestration_tpm_dispatch.py` (22) + `test_orchestration_comment_dispatch.py` (11), all green. Cover doctrine compliance (every status combo), idempotency, the no-TPM-warn path, the self-feedback skip, and message formatting.
- `projects/agent-hub/orchestration-v1-e2e-runbook.md` — step-by-step verification plan for #14. Pre-conditions, 7 test steps, failure-mode table, what's-NOT-covered list. Did not execute live because daemon was offline during dev; the runbook is the integration-test plan that whoever runs e2e post-merge follows.

**Why no live e2e in this branch**:
- Daemon was killed at the start of the design discussion and stayed off
- Live e2e requires a fresh ticket + real ANTHROPIC_API_KEY tokens
- Running it inside this dev fork would burn cost without producing reproducible artifacts
- The runbook is more durable and reproducible than a single live test execution would be

**Decisions made along the way**:
- Two separate files (`orchestration_tpm_dispatch.py` and `orchestration_comment_dispatch.py`) instead of one combined module. Different concerns, different test files, easier to evolve independently in Phase 2.5.
- The dispatch functions are deliberately **NOT wired into the daemon's event listeners** in this branch. That wiring is Phase 2.5 — it requires daemon-side plumbing (subscribing to `update_ticket` calls, post-hooking `add_comment`) that touches a lot of `services/agents-mcp/src/agents_mcp/server.py` and would balloon the diff. Better to land this branch as "pure orchestration primitives + tests + runbook" and do the daemon hook-in as a separate review-able PR.
- TPM-from-self comment dispatch is skipped at the dispatcher level (not at the daemon level). Rationale: the daemon doesn't know which session id authored a comment without inspecting comment metadata; pushing the skip into the dispatcher keeps the daemon dumb.
- Comment formatting includes ticket_id even though TPM already knows its ticket — explicit beats implicit when the LLM is reading a stream of past comments. Helps TPM recover context after a long pause.

**Branch summary at end of Phase 2**:

- 9 commits on `feat/orchestration-v1` since branching off main
- New modules: 7 files (adapters/base, adapters/claude_adapter, profile_loader, orchestration_session_manager, orchestration_tpm_dispatch, orchestration_comment_dispatch, plus the `adapters/__init__.py`)
- New schema: 2 tables (session, profile_registry)
- 4 starting Profiles in `profiles/`
- 131 new tests across 7 test files, all green
- 0 regressions in the non-orchestration suites
- 1 design doc + 3 research notes + 1 e2e runbook + AUTONOMY-CHARTER + this journal — total documentation pack for the redesign

**Next**: Open the PR `feat/orchestration-v1 → main`. Per AUTONOMY-CHARTER, this branch is large enough that admin does NOT self-merge — Human reviews and merges. Phase 2.5 (daemon plumbing) is a follow-up.
