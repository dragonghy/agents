# apps/console/ Survey for Orchestration v1 Phase 3 (2026-05-02)

## TL;DR (3 lines)

- The existing console is a small, clean, read-only Vite+React+TS SPA over a FastAPI+aiosqlite backend (~2,000 LOC total), polling-only, no WebSocket, no auth, no writes.
- Its data model is hard-coded to the legacy world: agents.yaml `agents.<name>`, tmux-window-per-agent, `tickets.assignee` field, named instances (`dev-alex`, `qa-lucy`). None of those primitives survive in the v1 redesign.
- **Recommendation: partial rewrite** — keep the FastAPI + Vite scaffold, the SQLite read-only helper, the cost/brief readers, and the styles; throw away every page that's tied to "agent = tmux window with a name" (Agents, AgentDetail, TmuxStream) and replace with Profile / Session / TPM views driven by daemon REST + WebSocket.

## Tech stack

**Frontend** (`apps/console/frontend/`):
- Vite 5.4 + React 18.3 + TypeScript 5.7
- React Router DOM 6.30 for client-side routing
- Package manager: **npm** (package-lock.json present)
- No state library, no UI framework, no CSS framework — hand-rolled `fetch` + 313-line plain CSS file
- 3 deps total (react, react-dom, react-router-dom); 5 devDeps

**Backend** (`apps/console/backend/`):
- FastAPI ≥0.115 + Uvicorn (standard) ≥0.32
- aiosqlite ≥0.20 (async, opens DBs with `?mode=ro` URI)
- pyyaml, pydantic
- Package manager: **uv** (uv.lock present, `pyproject.toml` declares hatchling build)
- Python ≥3.11

Evidence: `apps/console/frontend/package.json`, `apps/console/backend/pyproject.toml`.

## Build / deploy

- `Makefile` at `apps/console/Makefile` is the single entry point: `install`, `dev`, `build`, `run`, `test`, `clean`.
- **Dev** (`make dev`): backend uvicorn on `127.0.0.1:3000` with `--reload`, frontend Vite dev server on `127.0.0.1:3001`. Vite proxies `/api/*` → `:3000`.
- **Prod** (`make build && make run`): `npm run build` writes the frontend bundle into `backend/app/static/` (gitignored), then FastAPI serves the SPA at `/` from a single port (3000).
- `AGENTS_REPO_ROOT` env var resolves the repo root (Makefile sets it from `../..`); falls back to walking up from `__file__` looking for `.agents-mcp.db` + `.agents-tasks.db`.
- No Dockerfile, no systemd unit, no launchd plist, no Cloudflare Tunnel, no current production deployment that I found. README explicitly says "Bound to 127.0.0.1:3000 by default. Add SSO + Cloudflare Tunnel later."

## Backend integration

**Direct SQLite reads** — the console does NOT call the daemon over HTTP. It reads two SQLite files at the repo root:

- `.agents-mcp.db` — `agent_profiles`, `messages` (P2P inbox/sent), `token_usage_daily`
- `.agents-tasks.db` — `workspaces`, `tickets`, `comments`

Both opened via `aiosqlite.connect(f"file:{path}?mode=ro", uri=True)` (`backend/app/db.py:14-22`). This is a deliberate design choice (README "Independence guarantees" section): the console works even when the daemon is down, and is provably read-only at the SQLite layer.

**Auxiliary data sources**:
- `agents.yaml` parsed via PyYAML (`agents` route only)
- `briefs/brief-YYYY-MM-DD.md` files on disk (`briefs` route)
- `tmux list-windows` / `tmux capture-pane -p` via `subprocess.run` (`agents` and `tmux` routes; explicitly never writes)

**API surface** (all under `/api`, all GET):

| Path | Source | Notes |
|---|---|---|
| `GET /api/health` | repo+filesystem | Reports DB existence |
| `GET /api/workspaces` | tasks.db `workspaces` | List + detail |
| `GET /api/agents` | agents.yaml + mcp.db + tmux + tasks.db | Joined view |
| `GET /api/agents/{id}` | same | One agent |
| `GET /api/agents/{id}/tickets` | tasks.db `tickets WHERE assignee=?` | |
| `GET /api/agents/{id}/inbox` | mcp.db `messages WHERE to_agent=?` | |
| `GET /api/agents/{id}/sent` | mcp.db `messages WHERE from_agent=?` | |
| `GET /api/tickets` | tasks.db | Filterable by workspace/status/assignee |
| `GET /api/tickets/board` | tasks.db | Kanban shape (status 3/4/1) |
| `GET /api/tickets/{id}` | tasks.db | |
| `GET /api/tickets/{id}/comments` | tasks.db `comments WHERE module IN (...)` | |
| `GET /api/briefs` | filesystem | List recent |
| `GET /api/briefs/{date}` | filesystem | Markdown body |
| `GET /api/cost/summary` | mcp.db `token_usage_daily` | Sonnet pricing |
| `GET /api/tmux/{session}/windows` | `tmux list-windows` | |
| `GET /api/tmux/{session}/{window}/capture` | `tmux capture-pane -p` | ANSI strip optional |

**Daemon-bundled counterpart at `services/agents-mcp/src/agents_mcp/web/`** (note: separate, older):
- `api.py` is **1049 lines** (~10× the new console's 588 backend lines). It DOES talk through the daemon's `client`/`store`/`config` directly (in-process), supports POST/PUT/DELETE for ticket CRUD, comments, messaging.
- `events.py` (61 lines) implements a `WebSocket /ws` event bus with broadcast — already exists, but `apps/console/` doesn't use it.
- `static/` has a minimal pre-built bundle (450-byte index.html). Looks like an early SPA that predated PR #22.

The new console (`apps/console/`) deliberately does NOT share code with `agents_mcp/web/` — README "Independence guarantees" calls this out. This is a known split that the human is now asking us to resolve.

## Routes / pages

Pages from `App.tsx`:

| Route | Component | Purpose |
|---|---|---|
| `/` | `Overview` (inline) | Dashboard: AgentPanel(compact) + CostDashboard(compact) + TicketBoard(embedded) |
| `/agents` | `AgentPanel` | Grid of agent cards with tmux dot, role, workload, profile.current_context preview |
| `/agents/:id` | `AgentDetail` | Identity / Workload / Profile cards + tickets + inbox + sent messages |
| `/board` | `TicketBoard` | Kanban (New / In Progress / Blocked) for the active workspace |
| `/briefs` | `BriefHistory` | List of briefs + selected day's markdown content |
| `/cost` | `CostDashboard` | Today / 7d / lifetime USD + per-agent breakdown |
| `/tmux` | `TmuxStream` | Tmux window picker + 5s-polled `capture-pane` output |

Sidebar has a workspace switcher (`<select>` over `/api/workspaces`) that flows down to TicketBoard via prop.

## State management

- **None.** No React Query, no SWR, no Zustand, no Redux, no Context.
- Each page does its own `useEffect` + `useState` + `setInterval(load, REFRESH_MS)`.
- `api.ts` is a 92-line hand-rolled `fetch` wrapper with one helper per endpoint (`get<T>(path)`).
- No caching, no dedup, no global error boundary, no auth header injection. If two pages need the same agent list, they'll fetch it twice.

## Live updates

**Polling only.** Cadences (constants in each component):
- AgentPanel: 10 s
- TicketBoard: 15 s
- CostDashboard: 30 s
- TmuxStream: 5 s
- BriefHistory, AgentDetail: load-once, no polling

The README explicitly says "WebSocket / SSE — using simple polling (5s tmux, 10s tickets/agents). [...] Phase 1." A WebSocket bus exists in `services/agents-mcp/src/agents_mcp/web/events.py` but the new console doesn't connect to it.

## Component pattern + code quality

- Components are mostly **page-specific**, not reusable. AgentPanel and CostDashboard each accept a single `compact?` prop to be re-used in the Overview view; that's the only sharing primitive. No design-system layer (no `<Card>`, `<Button>`, etc.).
- Code quality is **clean and consistent**: small functions, sane TypeScript types in `types.ts`, predictable polling pattern, every fetch checks `cancelled` before setState. No obvious bugs, no over-engineering.
- CSS is plain, namespaced by class, ~313 lines, dark theme with CSS variables. Polished enough; no Tailwind / styled-components / CSS modules.
- TypeScript is strict-ish (`tsc -b --noEmit` runs in CI per `package.json`). Type definitions match backend response shapes by hand — no codegen, no OpenAPI client.

Overall, this looks like a competent ~1-engineer-week prototype, not "production architecture." Easy to extend; easy to throw away.

## What's deprecated for the new system

Cross-referencing the design doc (`projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md`):

| Console asset | Why it's deprecated under v1 |
|---|---|
| `/agents` page (`AgentPanel.tsx`) | "Agents" as named instances (admin / dev-alex / qa-lucy / ops / assistant-aria) go away. Replaced by **Profile registry** (`tpm`, `developer`, `housekeeper`, `secretary`, `architect`, `qa`...). The card semantics ("which agent has which workload?") become "which Profile has which active sessions?" — different shape. |
| `/agents/:id` page (`AgentDetail.tsx`) | Same reason. Profile detail page replaces it but has different sub-tabs (recent sessions, system prompt, declared tools, declared MCPs, version log) and no inbox/sent (P2P messages are explicitly being deprecated — see design doc §"Pillar 3: agents MCP — legacy P2P will be deprecated"). |
| `/tmux` page (`TmuxStream.tsx`) | Design doc §2.7: "tmux retained only for: admin's permanent debug window... New per-ticket sessions have no tmux footprint." Tmux is no longer where agent work happens. The session view replaces it with daemon-streamed conversation transcripts. |
| `_tmux_status()` helper in `routes/agents.py` | Same reason — agent liveness no longer maps to tmux window pane_activity. Liveness becomes "session has unprocessed messages" or "session is mid-LLM-call." |
| `agent_inbox` / `agent_sent` endpoints | P2P message bus is being retired. Comments-on-tickets is the new bus. |
| `agents.yaml` parsing in `_load_agents_yaml` / `_expand_agents` | The new "registry" is `profiles/<name>/profile.md` files, not `agents.yaml` v1 entries. |
| `tickets.assignee` filter in `agent_tickets` | Design doc §"What changed": "Ticket no longer has a fixed `assignee` in the orchestration sense." Filtering by assignee becomes meaningless — every active ticket has a TPM session and many subagent sessions. |
| Direct `?mode=ro` SQLite reads | Conflicts with the design's "daemon goes from router to runner" — Web UI is supposed to read live state via REST + WebSocket from the daemon, not bypass it. The "console works when daemon is down" guarantee disappears (acceptable, design doc §"Out of scope: Direct CLI / SSH access to the daemon. Web UI is the only operator surface"). |
| Polling for everything | Design doc explicitly calls for WebSocket / SSE for live streaming (§"Phase 3 — Web UI Phase 2 (interactive): Session view with live streaming (SSE / WebSocket from daemon)"). Polling at 5–30 s is fine for Phase 1 but is the wrong cadence for "watch a Profile think." |

## What's salvageable

| Asset | Why keep it |
|---|---|
| **Vite + React 18 + TS scaffold** + `tsconfig` + `vite.config.ts` + `index.html` | Modern, minimal, exactly what the design doc asks for. Zero reason to rewrite. |
| **FastAPI + Uvicorn + aiosqlite scaffold** + `Makefile` | Same. The new daemon will run FastAPI anyway; there's nothing to gain by switching frameworks. |
| **`backend/app/repo.py`** | Path resolver via `AGENTS_REPO_ROOT` env. Reusable as-is. |
| **`backend/app/db.py`** read-only helper | Useful for any read-only queries (cost dashboard, brief history). Worth keeping. |
| **`backend/app/pricing.py`** | Sonnet pricing constants + `estimate_usd()`. Will be needed by the cost dashboard the design doc specifies for Phase 5. |
| **`/api/cost/summary` endpoint + `CostDashboard` component** | Cost dashboard is explicitly called out as a Phase 5 deliverable. The current implementation already aggregates per-agent; extending to per-Profile / per-session / per-ticket is straightforward. |
| **`/api/briefs` + `BriefHistory` component** | Briefs are independent of the orchestration redesign — they're disk-backed markdown files. Keep verbatim. |
| **`/api/workspaces` + `WorkspaceSwitcher`** | Workspace model survives unchanged (design doc §"Pillar 1: Memory — no redesign"). |
| **`/api/tickets` + `/api/tickets/{id}/comments` + `TicketBoard` component** | Ticket model survives. Tile / Kanban shape is reusable. **Comments-as-event-stream** in the new model means the comments endpoint will need a streaming variant, but the read-side shape stays. |
| **`styles.css`** (313 lines) + dark-theme palette | Decent visual baseline. README mentions the v1 design language should "borrow from paperclip's UI patterns" — paperclip review notes their CSS isn't anything we want to lift directly, so the existing palette is a reasonable starting point. |
| **`api.ts` fetch helper pattern** | The `get<T>(path)` shape is fine; we'll add WebSocket helpers and POST helpers alongside it. |
| **TypeScript types in `types.ts`** | Workspace, Ticket, BriefSummary, CostSummary types stay. Agent / AgentMessage / TmuxWindow types go. |
| **The "single port via static mount" deployment pattern** in `main.py` | The SPA-served-from-FastAPI pattern is exactly what we want for a Cloudflare-tunneled future. |

## Recommendation: **partial rewrite** (keep scaffold + cost/briefs/tickets/workspaces; throw out agents/tmux/messaging; build new Profile/Session/TPM pages)

**Justification (5 sentences)**:

1. The existing console's *foundation* (Vite+React scaffold, FastAPI scaffold, Makefile, single-port deploy, RO SQLite helper, pricing module, styles) is exactly the stack the v1 design doc would have us pick anyway — there's no architectural reason to rewrite from zero, and a clean rewrite wastes ~600 LOC of working scaffolding.
2. However, **every page that exposes "agents"** (`AgentPanel`, `AgentDetail`, `TmuxStream`) maps onto primitives the redesign explicitly retires: named instances (dev-alex / qa-lucy), `tickets.assignee`, tmux windows, P2P inbox messages. Those screens need fresh information architecture, not edits — a Profile is not a renamed Agent and a Session is not a tmux window.
3. The existing console **ignores the daemon's WebSocket bus** at `services/agents-mcp/src/agents_mcp/web/events.py` and reads SQLite directly. The new design explicitly says "Web UI reads daemon state via REST + WebSocket for live updates" — so the data-fetching layer (`api.ts`, the polling intervals, the lack of a global event subscription) needs to be reworked anyway.
4. The two backend codebases (`apps/console/backend/` vs. `services/agents-mcp/src/agents_mcp/web/api.py`) need to **converge** — running both is a known maintenance burden the README itself flags as "Phase 3 decision." Lift-and-extend without touching that split would inherit the schism.
5. **Concretely: keep `apps/console/`'s Vite + FastAPI shells, retire its `web/api.py` daemon-bundled twin in the same patch, kill the agent/tmux pages, and add Profile / Session / Live-stream pages on top.** Estimated salvage: ~40-50% of the existing files (cost, briefs, tickets, workspaces, scaffolding); ~50-60% rewrite (everything agent-named, tmux, P2P messaging, plus the entire WebSocket subscription layer that doesn't exist yet).

## File-by-file inventory (only files >50 lines)

| File | Lines | Purpose | Salvageable |
|---|---|---|---|
| `apps/console/backend/app/main.py` | 98 | FastAPI app + CORS + SPA mount + health | **Y** (keep almost as-is) |
| `apps/console/backend/app/repo.py` | 49 | Path resolver | Y (under 50; mention for completeness) |
| `apps/console/backend/app/routes/agents.py` | 227 | Agents list/detail + tmux status + inbox/sent | **N** (entire file is tied to deprecated primitives) |
| `apps/console/backend/app/routes/tickets.py` | 99 | Ticket list/board/detail/comments | **Y** (read-side shape stays) |
| `apps/console/backend/app/routes/cost.py` | 98 | Cost summary aggregation | **Y** (extend to per-Profile/session/ticket) |
| `apps/console/backend/app/routes/tmux.py` | 91 | Tmux capture-pane endpoints | **N** (tmux is retired for sessions) |
| `apps/console/backend/app/routes/briefs.py` | 44 | Brief list/detail | Y (under 50) |
| `apps/console/backend/app/routes/workspaces.py` | 30 | Workspaces list/detail | Y (under 50) |
| `apps/console/frontend/src/App.tsx` | 118 | Sidebar + routes + Overview | **Partial** — keep shell, replace nav items |
| `apps/console/frontend/src/api.ts` | 92 | fetch wrapper + endpoint helpers | **Partial** — keep `get<T>()` and ticket/cost/brief/workspace helpers; drop agent/tmux/inbox helpers; add WebSocket helpers |
| `apps/console/frontend/src/types.ts` | 112 | TS types for all responses | **Partial** — keep Workspace / Ticket / BriefSummary / CostSummary; drop Agent / AgentMessage / TmuxWindow / TmuxCapture |
| `apps/console/frontend/src/styles.css` | 313 | Plain CSS, dark theme | **Y** (extend; no need to rewrite) |
| `apps/console/frontend/src/components/AgentDetail.tsx` | 149 | Agent detail with inbox/sent/tickets | **N** (replace with Profile detail page) |
| `apps/console/frontend/src/components/CostDashboard.tsx` | 105 | Today/7d/lifetime + by-agent | **Y** (extend grouping to Profile/Session/Ticket) |
| `apps/console/frontend/src/components/AgentPanel.tsx` | 92 | Agent grid | **N** (replace with Profile registry / Active Sessions list) |
| `apps/console/frontend/src/components/TmuxStream.tsx` | 89 | Tmux pane viewer | **N** (replace with Session live-stream view) |
| `apps/console/frontend/src/components/TicketBoard.tsx` | 82 | Kanban board | **Y** (keep; consider switching from `assignee` to "TPM session active y/n" indicators) |
| `apps/console/frontend/src/components/BriefHistory.tsx` | 75 | Brief list + markdown viewer | **Y** (keep verbatim) |

(Files <50 lines: `db.py` 36, `pricing.py` 32, `repo.py` 49, `__init__.py`s, `briefs.py` 44, `workspaces.py` 30, `main.tsx` 13, `index.html` 21, `vite.config.ts` 19, `tsconfig.json`, `package.json`, `pyproject.toml` — all keep-or-trivially-extend.)

## Out-of-scope facts I noticed

- The daemon-bundled `services/agents-mcp/src/agents_mcp/web/api.py` (1049 lines) implements **write** endpoints (POST tickets, comments, messages, workspaces) that `apps/console/` does not have. If the v1 redesign keeps any of those write paths, lifting them from `web/api.py` rather than re-implementing in `apps/console/backend/` is the lower-risk move. The two should be reconciled into one codebase (the design doc implies `apps/console/` becomes the single Web UI surface).
- The daemon already has a working `WebSocket /ws` broadcast bus (`web/events.py`); the new console can subscribe to it without writing new transport — this matches the design doc's "Daemon implements a small in-process pub/sub. WebSocket / SSE pushes events to web UI."
- `apps/console/backend/tests/test_smoke.py` exists (per Makefile) but I didn't read it — note that any rewrite needs to keep the smoke-test pattern.
