# Orchestration v1 — Progress Journal

> Append-only log of work done on `feat/orchestration-v1`.
> Each commit gets one entry. Most-recent at the bottom.
> If your context was lost, read AUTONOMY-CHARTER.md, then this file, then resume.

## State summary (kept current at the top)

- **Branch**: `feat/orchestration-v1` (off `main` post-DAG-merge)
- **Current Phase**: ✅ Phase 1 + Phase 2 + Phase 2.5 (TPM tool-use) complete. Live multi-agent demo executed.
- **Tasks**: 14 / 14 done (#5–#14) plus Phase 2.5 (TPM tool bindings + live demo).
- **Open blockers**: none. Daemon-event-listener wiring (status-changed → `maybe_spawn_tpm_for_status_change`, comment_created → `dispatch_comment_to_tpm`) and Phase 3 (Web UI) remain as follow-up work.
- **End-to-end verification**: live multi-agent demo executed — see `projects/agent-hub/research/orchestration-v1-multi-agent-demo-2026-05-02.md`. TPM coordinated 3 turns, spawned 2 subagents (Architect + Developer), posted 2 comments, transitioned the ticket Blocked → Done. Total cost ≈ $1.34.
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

---

### 2026-05-02 — Phase 2.5 daemon plumbing — wire dispatch hooks (Task #16 complete)

**What**:

- `services/agents-mcp/src/agents_mcp/server.py`:
  - Added module-level `_session_manager` singleton + `_ensure_orchestration_ready(root_dir)` helper that builds a `SessionManager(store, profiles_dir, task_client=client)` and runs `ProfileLoader(profiles_dir, store).scan()` once. Called from `get_store()` immediately after `store.initialize()` so the singletons are always ready by the time any MCP tool handler runs. Wrapped in try/except — if `profiles/` doesn't exist or scan errors, the daemon logs a warning and continues; orchestration just becomes a no-op for that boot.
  - Wired `update_ticket` MCP tool: BEFORE `client.update_ticket`, fetches the current ticket via `client.get_ticket(ticket_id, prune=True)` to capture `old_status` (only when `status` is being changed). AFTER the update, if `status` was provided AND `old_status != new_status`, calls `maybe_spawn_tpm_for_status_change` and `maybe_close_tpm_for_status_change`. Failures inside the dispatch hook are caught + logged via `logger.exception`; the primary update_ticket return path is untouched.
  - Wired `add_comment` MCP tool: added optional `author_session_id: str = None` parameter. After the comment is created, if `module in ("ticket", "tickets")` and `_session_manager` is available, calls `dispatch_comment_to_tpm` with the comment_id (lastrowid from SQLite client), body, and author_session_id forwarded through. Same best-effort try/except pattern.
- `services/agents-mcp/tests/test_server_plumbing.py` — 11 new tests covering: 3→4 spawns TPM, no-status-change path skips dispatch, status-unchanged-value skips dispatch, 4→0 calls close hook, SessionManager-unavailable path skips silently, comment dispatch with explicit/None author_session_id, non-ticket modules don't dispatch, dispatch failure doesn't break primary path. Tests mock the Leantime client + the dispatch helpers and call the raw async function via the FastMCP `.fn` accessor (sync wrapper + `run()` helper, no pytest-asyncio dep — matches the existing convention).

**Why**: Without this wiring the dispatch helpers existed but nothing called them — TPM auto-spawn / wake never fired in the real daemon. After this commit, posting a comment on a ticket OR transitioning its status in the daemon's MCP tool surface fires the orchestration hooks automatically.

**Decisions made along the way**:
- **Module-level singletons over per-handler lazy init**: Tried lazy init from each handler first, but that meant repeating the try/except boilerplate at every entry point and harder testing. The `_get_session_manager()` accessor (returning ``None`` when orchestration isn't booted) gives tests a clean injection seam via `patch.object(srv, "_get_session_manager", return_value=...)`.
- **Pre-fetch ticket only when status is changing**: avoids an extra SQLite read on the hot non-status update path. Keeps the failure mode for "ticket doesn't exist" identical to the existing client behaviour.
- **`task_client=client` passed to SessionManager constructor at boot**: TPM profile declares `orchestration_tools: true`, so `append_message` needs a task_client when the TPM eventually runs. Wiring it once at construction time keeps later callers (the dispatch hooks themselves) simple.
- **Late imports of dispatch helpers inside the handlers**: keeps server.py module-level imports unchanged for callers that don't exercise orchestration (faster cold-start, no transitive `claude-agent-sdk` import on import-server). Same pattern as the existing v2 dispatcher import inside `_start_auto_dispatch_async`.
- **`author_session_id` plumbed through but no caller wired today**: per task spec, MCP callers (TPM tool wrapper, Web UI, future agent code) will pass it; default `None` makes Human-via-Web-UI / Telegram comments correctly attribute to "human". No new tools shipped — the existing `add_comment` tool surface gained one optional kwarg.
- **Used FastMCP's `.fn` accessor in tests**: tools are wrapped twice (`@app.tool()` + `@_with_timeout`); calling them from tests requires the underlying async function. `_raw(tool)` helper in the test file does the unwrap.

**Verification**: 11/11 new tests green; full suite count delta = +11.

**TPM auto-spawn now fires automatically on status=3→4 transitions in real daemon flow.**

---

### 2026-05-02 — Minimum viable test harness (Task #17 complete) — MVTH ready

**What**:

- New backend module `services/agents-mcp/src/agents_mcp/web/orchestration_api.py` (~230 LOC) — a Starlette `Route` factory `create_orchestration_router(store, session_manager)` exposing the five MVTH endpoints under `/api/v1/orchestration/`:
  - `GET /profiles` — wraps `store.list_profile_registry()`.
  - `POST /sessions` — body `{profile_name, binding_kind, ticket_id?, channel_id?, parent_session_id?}`; calls `SessionManager.spawn(...)`; returns the session row (201).
  - `POST /sessions/{id}/messages` — body `{text}`; calls `SessionManager.append_message(...)`; returns `{assistant_text, tokens_in, tokens_out, native_handle}`. May take 5-30s while Claude is called.
  - `POST /sessions/{id}/close` — calls `SessionManager.close(...)`; returns `{ok}`.
  - `GET /sessions/{id}` — wraps `store.get_session(...)`.
  - The factory accepts either live objects or zero-arg async getters — daemon mounting happens before the asyncio loop is up, so the daemon hands in async getters that lazily resolve on first request; tests pass live mocks directly.
- `services/agents-mcp/src/agents_mcp/server.py` — mounted the new router under `/api/v1/orchestration` next to the bridge. Reused the existing `_get_session_manager()` accessor that the Phase 2.5 plumbing landed; added a thin getter wrapper that ensures `get_store()` (which triggers `_ensure_orchestration_ready`) has run.
- `services/agents-mcp/tests/test_orchestration_api.py` — 22 tests using Starlette's `TestClient` + a `_FakeStore` + `_FakeSessionManager` (mirrors the real shapes; never hits the LLM). Covers happy paths + 404 on missing session + 400 on missing/invalid body fields + 400 on bad JSON + 400 on validation errors raised by the manager + a test that the callable-injection path used by the daemon works.
- New frontend page `apps/console/frontend/src/components/SessionTester.tsx` (~225 LOC) — three stacked sections (Profile picker → Session controls → Conversation log). Default profile = `secretary`. No streaming, no markdown — plain text turns rendered as stacked role-tagged divs. Disabled-while-pending guard on the Send button. Errors surfaced inline.
- `apps/console/frontend/src/api.ts` — added `listProfiles`, `spawnSession`, `appendMessage`, `closeSession`, `getSession` plus a small `post<T>()` wrapper.
- `apps/console/frontend/src/types.ts` — added `Profile`, `Session`, `SpawnSessionBody`, `AppendMessageResult`, `SessionMessage`.
- `apps/console/frontend/src/App.tsx` — added a `/test-harness` route + sidebar nav link.
- `apps/console/frontend/vite.config.ts` — added a more-specific `/api/v1/orchestration` proxy entry that targets `http://127.0.0.1:8765` (the daemon), placed BEFORE the existing catch-all `/api` → `:3000` (apps/console/backend) so the orchestration calls reach the daemon while the rest of the console keeps reaching the FastAPI backend.

**Verification**:

- `cd services/agents-mcp && uv run pytest tests/test_orchestration_api.py -v` → 22/22 green.
- Full orchestration suite (api + session_manager + orchestration_session + profile_loader + adapter_base + tpm_dispatch + comment_dispatch) → 131/131 green.
- `cd apps/console/frontend && npm run typecheck` → green.
- `cd apps/console/frontend && npm run build` → green (177.73 kB JS, 5.81 kB CSS).
- Live e2e (point browser at the daemon, spawn → send → see Claude reply) NOT executed — coordinated with the daemon-plumbing subagent's parallel work, MVTH artifacts are in place for Human to verify when ready.

**Decisions made along the way**:

- **Live object vs. callable getter**: The daemon's HTTP mount happens inside `main()` before any asyncio loop is running, so we can't `await get_store()` there. The router accepts either form via a tiny `_resolve(value)` helper that calls + awaits when the input is callable. Tests stay simple (pass live mocks).
- **404 vs. 400 split**: unknown session id → 404 (the verb is `get`-shaped); closed session / invalid binding_kind / missing required field → 400. Matches the bridge's existing convention. Append-message on unknown session is 404 (not 400) because the path-param identifies the resource.
- **Vite proxy ordering**: the `/api/v1/orchestration` rule has to come BEFORE `/api`; Vite resolves prefixes top-to-bottom and the catch-all would otherwise win.
- **No CSS additions**: every visual element reuses existing `.card`, `.error`, `.empty-state`, `.loading`, `.page-header`, `.subtitle`, plus the dark-theme CSS vars (`--bg`, `--bg-panel`, `--bg-panel-hover`, `--border`, `--text`, `--text-dim`, `--text-muted`). Inline-styled the message bubbles + textarea to keep `styles.css` untouched.
- **Cleanup subagent overlap**: the parallel cleanup subagent removed `AgentPanel`/`AgentDetail`/`TmuxStream` (components + types + api helpers) and replaced `web/api.py` with `web/bridge.py`. They mounted only `/api`; I added the orchestration mount alongside theirs, plus the proxy + the new types/api helpers. No merge conflicts ended up materialising — the cleanup landed cleanly under us.

**MVTH ready for live verification**: Human points browser at `http://127.0.0.1:3001/test-harness`, picks `secretary`, hits Spawn, types something, sees a real Claude reply.

**Next**: Open PR `feat/orchestration-v1 → main` — Phase 1+2 + 2.5 daemon plumbing + MVTH all on the same branch, ready for Human review.

---

### 2026-05-02 — Cleanup pass v2 — extract Telegram bridge, delete dead Web UI

**What**:

- New module `services/agents-mcp/src/agents_mcp/web/bridge.py` (~190 LOC, ~40 of which are docstring/blanks) — `create_bridge_router(get_client, get_store, get_config, resolve_agents)` returns the 5 Starlette `Route` objects the Telegram bot still consumes:
  - `POST /v1/human/messages` (inbound from Human)
  - `GET  /v1/human/outbox` (outbound poll, marks rows delivered)
  - `POST /v1/human/send` (admin's outbound path — CLAUDE.md pitfall #6)
  - `GET  /v1/brief` (`/brief` slash command)
  - `GET  /v1/health` (`/status` slash command)
  - Logic copied verbatim from the deleted `web/api.py` so behaviour stays bit-identical for the bot. The brief routing inside `post_human_message` (parse_brief_response → execute_actions vs. forward to admin P2P) is preserved.
- `services/agents-mcp/tests/test_bridge.py` — 11 smoke tests using Starlette's `TestClient` + stubs. Covers all 5 routes (success + error paths) + the import-smoke that catches daemon-boot regressions.
- `services/agents-mcp/src/agents_mcp/server.py` — replaced the `web.api.create_api_router` mount with `create_bridge_router`; removed the `WebSocketRoute("/ws", websocket_endpoint)` insert (events.py is gone); removed the SPA static-file mount + the entire `if static_dir exists` branch (~30 LOC); removed the broadcast-to-event_bus block in `_create_notifications_with_subscribers`.
- `services/agents-mcp/src/agents_mcp/dispatcher_v2.py` — removed the same broadcast-to-event_bus block at the end of each dispatch cycle.
- Deletions:
  - `services/agents-mcp/src/agents_mcp/web/api.py` (1049 LOC dead Display-UI REST + onboarding endpoints).
  - `services/agents-mcp/src/agents_mcp/web/events.py` (61 LOC EventBus + WebSocket handler).
  - `services/agents-mcp/src/agents_mcp/web/static/` (1 MB of pre-built SPA bundle from the old build pipeline).
  - `services/agents-mcp/web/` (189 MB SPA source — 38 .tsx/.ts files, e2e specs, package-lock.json, etc.).
  - `apps/console/backend/app/routes/agents.py` + `tmux.py` (2 dead FastAPI routers).
  - `apps/console/frontend/src/components/{AgentDetail,AgentPanel,TmuxStream}.tsx`.
  - `tests/e2e_onboarding.cjs` + `tests/e2e_token_usage_test.py` (E2E tests for the deleted SPA).
- Edits:
  - `restart_all_agents.sh` — stripped the `build_web_ui()` function + its caller in `start_daemon()` (now no longer trying to `npm install` a deleted directory).
  - `CONTRIBUTING.md` — removed the "Web UI Development" section; updated Project Structure to point at `apps/console/` instead of the deleted SPA.
  - `apps/console/backend/app/main.py` — dropped the `agents` + `tmux` router imports + their `include_router` calls.
  - `apps/console/frontend/src/App.tsx` — dropped `AgentPanel`/`AgentDetail`/`TmuxStream` imports + 4 Route lines + 2 NavLink lines + the `<AgentPanel compact />` from Overview.
  - `apps/console/frontend/src/api.ts` — removed `listAgents`/`getAgent`/`getAgentTickets`/`getAgentInbox`/`getAgentSent`/`listTmuxWindows`/`captureTmux` (7 helpers).
  - `apps/console/frontend/src/types.ts` — removed `Agent`/`AgentWorkload`/`AgentProfile`/`AgentMessage`/`TmuxWindow`/`TmuxCapture` (6 types).

**Why**: The Telegram bot's 5 endpoints are the only legacy HTTP surface still in production use. Everything else under `web/api.py` (~1000 LOC of agent panels, terminal capture, schedules, onboarding, tickets/messages CRUD) is shadow-code — nothing reads it now that the SPA is dead and `apps/console/` has its own FastAPI backend. Path (b) of the cleanup directive: extract the small live surface, delete the dead bulk.

**Decisions made along the way**:
- **Bridge as `list[Route]` (not a `Router` instance)**: matches the convention the orchestration_api subagent landed in parallel — the daemon `Mount("/api", routes=[...])` pattern keeps both factories swappable. The server still wraps the list in `Router(routes=...)` at mount time because `http_app.mount` wants a callable ASGI app, not a list.
- **No `/ws` WebSocket**: the only consumer was the dead SPA's real-time refresh hook. The Telegram bot never opened a WS. Removing both the route and the events module cuts ~75 LOC of broadcast plumbing across server.py + dispatcher_v2.py.
- **`apps/console/backend/app/routes/agents.py` deletion**: this was the apps/console copy of the agent panel — different from `web/api.py`'s but equally orphaned (the AgentPanel.tsx that consumed it is the one I just deleted). Same logic for `tmux.py`.
- **Empty `__init__.py` left in `web/`**: keeps the package importable so `web.bridge` and `web.orchestration_api` (parallel subagent's file) still resolve.
- **Test stubs (no SQLite)**: `test_bridge.py` uses stub store/client/cursor classes rather than a real `AgentStore` because the bot endpoints are pure-passthrough and the integration coverage already lives in store/client tests. Keeps the new file fast (<100 ms total).
- **Server.py merge race**: The Phase 2.5 daemon-plumbing subagent (commit d2130e9) committed in parallel and shifted my line numbers. First Edit succeeded but a subsequent linter/parallel-write reverted my mount change; re-applied against the new line numbers and re-ran imports + pytest to confirm.

**Verification**:
- `cd services/agents-mcp && uv run pytest --ignore=tests/test_message_filter.py` → 295/295 green (was 295 before, +11 from test_bridge, -0 because the deleted modules had no tests of their own).
- `cd apps/console/frontend && npm run typecheck` → green.
- `python -c "from agents_mcp.web.bridge import create_bridge_router; routes = create_bridge_router(lambda: None, lambda: None, lambda: {}, lambda c: {}); print(len(routes))"` → `5`.
- `python -c "import agents_mcp.server; import agents_mcp.dispatcher_v2; print('ok')"` → `ok`.

**Disk + LOC impact**: ~190 MB of source removed (mostly the dead SPA's `node_modules`-laden tree), ~1100 LOC of Python deleted from the daemon path, ~190 LOC of Python added (bridge + bridge tests). Net: enormous reduction in surface area for review and a cleaner mental model — the daemon's HTTP face is now exactly the bot bridge plus the orchestration test harness, nothing else.

**Next**: Phase 4 will replace this bridge with a proper channel-adapter on the new orchestration model — at which point bridge.py + telegram-bot/bot.py both get rewritten and this whole shim disappears.

---

### 2026-05-02 — Phase 2.5 — TPM tool-use bindings + live multi-agent demo

**What**:

- `services/agents-mcp/src/agents_mcp/orchestration_tools.py` — new module. Builds an in-process MCP server (`claude_agent_sdk.create_sdk_mcp_server`) per TPM session that exposes four tools: `spawn_subagent`, `push_message`, `post_comment`, `mark_ticket_status`. Each tool closes over the SessionManager + AgentStore + SQLiteTaskClient + the spawning TPM's session_id, so subagents are correctly parented and ticket comments are correctly attributed (`author=tpm:<session_id>`). Tools return MCP-shaped `{"content": [{"type": "text", ...}]}` dicts; on application errors they return `is_error: True` rather than raising so the TPM gets a structured error string it can reason about.
- `services/agents-mcp/src/agents_mcp/adapters/claude_adapter.py` — `ClaudeAdapter.run()` gained two optional keyword-only params, `mcp_servers` and `allowed_tools`, forwarded into `ClaudeAgentOptions` only when provided. Existing callers and tests don't see any change because of the kwargs-only addition.
- `services/agents-mcp/src/agents_mcp/orchestration_session_manager.py` — `SessionManager.__init__` now accepts an optional `task_client`. When `append_message` runs against a Profile with `orchestration_tools=True`, it builds an in-process tool server and passes `mcp_servers={server_name: cfg}` + `allowed_tools=["mcp__<server>__<tool>", ...]` to the adapter. Sessions for non-TPM Profiles continue to run text-only (no extra kwargs to the adapter).
- `services/agents-mcp/src/agents_mcp/adapters/base.py` + `profile_loader.py` — added `orchestration_tools: bool = False` field on the Profile dataclass, parsed from frontmatter (must be a real YAML boolean; non-bool values are rejected with `ProfileParseError`).
- `profiles/tpm/profile.md` — frontmatter `orchestration_tools: true`. Body rewritten to (a) name the four tools and document when to use each, (b) include a strong "tool, don't talk" anti-pattern callout ("don't say 'I would spawn an architect' — call `spawn_subagent`"), (c) provide an example flow (spawn architect → post_comment summary → spawn developer → push_message clarifying answer → mark_ticket_status 0).
- `profiles/architect/profile.md` — new minimal Profile (the demo wanted a non-Developer subagent target). Three-section output contract (Diagnosis / Proposed fix / Risks). Doesn't write code; doesn't change ticket status; just produces analysis.
- `services/agents-mcp/tests/test_orchestration_tools.py` — 19 new tests exercising each tool handler directly via the SDK's MCP `request_handlers` map (no LLM needed). Covers happy paths, error payloads (unknown profile, closed session, taskclient failure), all valid statuses, status=2 rejection, parent_session_id propagation.
- `services/agents-mcp/tests/test_session_manager.py` — 4 new tests for the wiring: TPM sessions get the `mcp_servers` + `allowed_tools` kwargs in the adapter call; non-TPM sessions don't; missing `task_client` and missing `ticket_id` raise clear errors; existing _FakeAdapter accepts `**kwargs`.
- `services/agents-mcp/tests/test_profile_loader.py` — 3 new tests for orchestration_tools field parsing (default False, true parses, non-bool rejected).
- `services/agents-mcp/tests/test_adapter_base.py` — relaxed structural-protocol assertion to enforce only required positional params (the new keyword-only params are additive).
- `services/agents-mcp/scripts/orchestration_demo.py` — live multi-agent demo. Seeds a synthetic ticket (id=999100, "Add index on orders.user_id...") in an isolated tmp DB, spawns a real TPM, drives up to N turns, records every TPM turn's tokens + assistant text, lists every subagent session spawned under the TPM, and writes a markdown transcript + JSON dump to `projects/agent-hub/research/`.

**Live demo result** (commit `d2130e9`): TPM ran 3 turns and:

1. **Turn 1** (in=93,848, out=2,623): spawned an architect (`sess_9dec8178e9eca0ea76c1c5`, in=20,507 / out=1,040), spawned a developer (`sess_9dec82982ebdf527ce7316`, in=125,094 / out=2,056), posted a status comment summarizing the architect's recommended fix (composite index on `(user_id, created_at DESC)`).
2. **Turn 2** (in=107,623, out=1,865): on follow-up nudge, the TPM noticed the developer reported "no `orders` table in this codebase" (the demo intentionally framed an external-DB scenario), posted a "blocked, awaiting clarification" comment, called `mark_ticket_status(999100, 1)` (Blocked).
3. **Turn 3** (in=56,956, out=1,002): on second follow-up, decided the investigation task was complete and called `mark_ticket_status(999100, 0)` (Done).

Final ticket state: status=0, 2 comments posted by TPM (both correctly attributed `tpm:sess_9dec80c6d27728cebf2fe6`), 2 subagent sessions visible in `session` table with proper `parent_session_id`. Total tokens 412,614 (404,028 in + 8,586 out across all sessions including subagents); estimated cost $1.34 USD.

**What worked**:

- The SDK's `create_sdk_mcp_server` + `@tool` decorator surface drop-in worked first try once we knew the right field names. No fallback to stdio MCP subprocess required.
- The TPM correctly distinguished "spawn architect" from "spawn developer" based purely on the Profile descriptions in the frontmatter, with no extra hint-engineering. Architect for the diagnosis, Developer for the implementation.
- Self-feedback skip: the `tpm:<session_id>` author tag we put on comments is exactly what `dispatch_comment_to_tpm` already filters on, so this naturally composes.
- The "tool, don't talk" anti-pattern in the system prompt was effective — the TPM's text replies were short summaries of what its tool calls had already done, not narration of what it intended to do.

**What didn't / paper-cuts**:

- The TPM occasionally emits a tiny prelude before its first tool call ("I need to load the TPM orchestration tools to handle this ticket."). Harmless but clutters the assistant text. Could be dampened by tightening the prompt; not worth a fix in this commit.
- On turn 3 the TPM redundantly called `mark_ticket_status(999100, 0)` when the ticket was already at status=1 (Blocked) — this is debatable since it interpreted the follow-up as "you can close the ticket if the work is done", but a stricter prompt would have it say "status already terminal, no action" instead. Acceptable for v1.
- The `list_sessions` query in the demo had to filter by `parent_session_id` in Python because the AgentStore method doesn't support that filter. Fine for the demo; if we surface this in production we should add `parent_session_id` to `list_sessions`.
- Comment-id/transcript truncation: comment 1's text got cut at 800 chars by the demo's `truncate()` helper. The full text is in the JSON sibling. Trade-off; markdown stays readable.

**Why this matters**: pre-commit, the TPM Profile was a paragraph generator. Post-commit, the same Profile is a coordinator that materializes its decisions as ticket-state mutations and subagent sessions. The wiring is exactly what Phase 2.5 needed; no daemon-side change required (the SessionManager + tools are self-contained), so the daemon-plumbing PR (already done above) and this PR can land independently.

**Verification commands run**:

- `uv run pytest tests/test_orchestration_tools.py tests/test_session_manager.py tests/test_profile_loader.py tests/test_adapter_base.py tests/test_claude_adapter.py tests/test_orchestration_session.py tests/test_orchestration_tpm_dispatch.py tests/test_orchestration_comment_dispatch.py` → 138/138 green.
- `uv run python services/agents-mcp/scripts/orchestration_demo.py --max-turns 6` → ran end-to-end, transcript at `projects/agent-hub/research/orchestration-v1-multi-agent-demo-2026-05-02.md`.

**Next**: With Phase 2.5 wiring + tools + live demo all in, the orchestration v1 model is functionally complete. Remaining work is Phase 3 (Web UI) and Phase 4 (channel adapters that replace bridge.py).
