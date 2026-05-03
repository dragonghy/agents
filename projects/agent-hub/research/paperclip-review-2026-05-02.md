# Paperclip Architectural Review (2026-05-02)

Reviewer notes: read-only review of `~/code/paperclip` against `~/code/agents`. Citations are `path:line` against the paperclip checkout snapshot at the time of review (latest commit pre-2026-05-02 release tag).

## TL;DR

- **Paperclip is a heavyweight Express/Drizzle/PG control plane** wrapping CLI agents (Claude Code, Codex, Cursor, Gemini, OpenCode, Pi, Cursor, OpenClaw, plus a `process` and `http` generic). It is structurally serious — single-tenant deployment, multi-company data model, full activity log, atomic checkout, budget enforcement, cron-driven scheduler — but every heartbeat re-spawns the underlying CLI as a fresh subprocess. That is the root cause of the token burn the human observed.
- **Tickets ("issues") are by far the strongest abstraction**: a single table with `parent_id` + a separate `issue_relations` table for blocker edges, plus a documented liveness contract (`doc/execution-semantics.md`) that distinguishes structure / dependency / ownership / execution. We should steal the data model and the liveness contract directly.
- **The adapter layer is also a strong borrowable pattern** — a small `ServerAdapterModule` interface (`server/src/adapters/types.ts`) plus a mutable registry, plus an external-plugin loader (`server/src/adapters/plugin-loader.ts`) that does on-demand UI parser extraction. Worth borrowing the *shape*; the per-heartbeat process spawn is what we should *not* borrow.
- **The heartbeat / live-event system is fragile by design**: live events ride a vanilla in-process `EventEmitter` with no replay buffer (`server/src/services/live-events.ts:7`). When the WebSocket disconnects, the gap is permanent. The transcript view has its own polling backstop, but the global `LiveUpdatesProvider` does not. That's why a reconnect can leave the UI inconsistent until you reload.
- **There is no first-class MCP installation surface for end-user agents.** Paperclip ships its own MCP *server* (`packages/mcp-server`) for agents to call into Paperclip, but it has no UI/CLI for adding 3rd-party MCPs (Google, etc.) into the agent's underlying Claude/Codex CLI. The "install MCP" flow degrades to "tell the agent where to write its config and burn tokens until it works."

## What paperclip is

- **Stack**: TypeScript / Node 20+ / pnpm workspace. Express server + React/Vite UI, Drizzle ORM over PostgreSQL (embedded PGlite for dev). Adapters live as workspace packages under `packages/adapters/*`. (`AGENTS.md`, `package.json`)
- **Mental model**: a board operator + a tree of agents inside a "company". Tickets ("issues") drive everything; each agent is invoked by a heartbeat scheduler that re-spawns the underlying CLI per tick. Budget, governance, and approval gates live in the control plane. Agents are external — they "phone home" via a REST API + bearer key.
- **Repo size**: ~277K lines of TypeScript across ~1,445 `.ts/.tsx` files. Big but manageable. The hot files are massive (`server/src/services/heartbeat.ts` is **7,855 lines**, `ui/src/pages/AgentDetail.tsx` is **4,239 lines**, `ui/src/pages/IssueDetail.tsx` is **3,889 lines**).
- **Top-level layout**:
  - `server/` — Express REST + orchestration services (`server/src/services/*`, ~80 files)
  - `ui/` — React board (`ui/src/pages/*`, 67 pages; `ui/src/components/*`, 149 components)
  - `packages/db` — Drizzle schema (~80 tables)
  - `packages/adapters/{claude,codex,cursor,gemini,opencode,pi,acpx,openclaw-gateway}-local` — one package per agent SDK
  - `packages/adapter-utils` — shared adapter helpers, prompt template, wake payload renderer
  - `packages/mcp-server` — Paperclip's own MCP server (Paperclip-as-tool, not for installing other MCPs)
  - `packages/plugins` — separate "plugin" subsystem for runtime/sandbox providers, distinct from adapters
  - `skills/` — markdown skill bundles symlinked into agent workspaces
  - `doc/` — spec docs (read these in order: `GOAL.md`, `PRODUCT.md`, `SPEC-implementation.md`, `execution-semantics.md`, `DATABASE.md`)
- **Where the interesting code lives**:
  - Heartbeat lifecycle: `server/src/services/heartbeat.ts` (7,855 lines, single file)
  - WebSocket live events: `server/src/realtime/live-events-ws.ts` + `server/src/services/live-events.ts`
  - Adapter dispatch: `server/src/adapters/{registry,plugin-loader,types,index}.ts`
  - Per-CLI invocation: `packages/adapters/claude-local/src/server/execute.ts` (860 lines, the per-tick subprocess)
  - Default agent prompt: `packages/adapter-utils/src/server-utils.ts:90-105` (`DEFAULT_PAPERCLIP_AGENT_PROMPT_TEMPLATE`)
  - Wake payload rendering: `packages/adapter-utils/src/server-utils.ts:594-810` (`renderPaperclipWakePrompt`)
  - Issue ("ticket") schema: `packages/db/src/schema/issues.ts` + `issue_relations.ts`
  - Liveness contract (the gem): `doc/execution-semantics.md`

## Strengths — by subsystem

### 1. Ticket hierarchy

The ticket model is well-thought-out and notably better than `~/code/agents`'s flat-with-parent_id + ad-hoc graph. Three things make it work:

**Structure vs. dependency are separated tables**:
- `issues.parent_id` (`packages/db/src/schema/issues.ts:29`) — strict tree, used for work-breakdown and rollup, *not* dependency.
- `issue_relations` (`packages/db/src/schema/issue_relations.ts:6`) — separate edge table with `type: 'blocks'`. Currently only `blocks` is used, but the table is shaped for more relation types.
- Why this matters: in our harness today, "blocked by another ticket" is an in-band convention in Leantime tickets/comments. Paperclip's separation lets the scheduler answer "is this ticket waiting on something?" with a single edge query.

**A separate liveness contract for status × ownership × execution**:
- See `doc/execution-semantics.md` §1 ("structure / dependency / ownership / execution"). Each non-terminal status (`todo`, `in_progress`, `in_review`, `blocked`) has an explicit liveness rule (§7).
- The contract is enforced by a periodic reconciler: `heartbeat.reconcileIssueGraphLiveness()` and `heartbeat.scanSilentActiveRuns()` (`server/src/index.ts:760-779`) walk the ticket graph and create *visible recovery issues* when an agent-owned ticket has no live execution path. Compare this to our pitfall #8 ("silent failure bugs in scrapers") — Paperclip enforces the same principle at the orchestration layer.

**Identifier ergonomics**:
- Each ticket has a UUID `id` *and* a human-readable `identifier` (e.g. `ENG-123`). Both can be used as URL/route keys (`packages/db/src/schema/issues.ts:43,81`). The MCP/REST API accepts either anywhere an issue id is expected (`doc/TASKS-mcp.md`).

**Origin tracking**:
- `originKind`, `originId`, `originRunId`, `originFingerprint` (`issues.ts:44-47`) classify how the ticket was created. Combined with conditional unique indexes (`issues.ts:85-133`), this prevents duplicate auto-generated tickets — e.g. there can be only one open `harness_liveness_escalation` per source ticket. Our harness has no such guard; we'd duplicate recovery tickets if a watchdog ran twice.

### 2. Agent management

Agents are first-class rows with rich state, not config files. `packages/db/src/schema/agents.ts:14-45`:

- `status` enum: `idle | running | error | pending_approval | terminated | paused`
- `reports_to` (FK to `agents.id`) — strict org tree (no multi-manager)
- `adapter_type` + `adapter_config` (jsonb) — adapter binding lives on the agent row
- `runtime_config` (jsonb) — runtime policy like `modelProfiles.cheap.adapterConfig` for a low-cost lane (`SPEC-implementation.md:153`)
- `budget_monthly_cents` + `spent_monthly_cents` — per-agent budget
- `last_heartbeat_at` — used by the scheduler to decide whether to enqueue a tick
- `permissions` (jsonb) — per-agent gates (e.g. who can hire)

The state machine is enforced server-side (`SPEC-implementation.md:404-415`). `terminated` is irreversible. `error → idle` requires explicit transition. Compare this to our `agents.yaml` flat config + ad-hoc `assistant-aria.extra_mcp_servers` — Paperclip's model is more rigid but easier to query and audit.

The hire flow is governed by an `approvals` table with type `hire_agent` (`SPEC-implementation.md:691`) — board approval is required by default for new agents. We don't have an equivalent gate.

### 3. Agent ↔ ticket adapter (the dispatch path)

This is the bridge between "ticket is ready" and "agent picks it up". Paperclip's design is **wake-driven, push, with atomic checkout** (`SPEC-implementation.md:539-555`):

1. Scheduler `heartbeat.tickTimers()` runs every 30s (`server/src/index.ts:718` + `config.heartbeatSchedulerIntervalMs`, default 30,000ms minimum 10,000ms).
2. For each non-paused agent with `policy.enabled && policy.intervalSec > 0` and `now - lastHeartbeatAt >= intervalSec`, it calls `enqueueWakeup(agentId, {source: "timer"})` (`heartbeat.ts:7775-7807`).
3. `enqueueWakeup` (`heartbeat.ts:6594-`) does budget checks, status checks, tree-hold checks, then writes a `heartbeat_runs` row with status `queued`.
4. `startNextQueuedRunForAgent` (`heartbeat.ts:4817`) picks the next queued run respecting `policy.maxConcurrentRuns` (default 20, clamp 1..50 per `SPEC-implementation.md:679`), prioritizing dependency-ready, in-progress, higher-priority issues.
5. **Atomic checkout** at `POST /issues/:issueId/checkout` (`SPEC-implementation.md:540-554`): a single SQL `UPDATE` with `WHERE id = ? AND status IN (?) AND (assignee_agent_id IS NULL OR = :agentId)`. Updated row count = 0 → `409 Conflict`. This is exactly the safe pattern.
6. `executionRunId` and `checkoutRunId` are different fields with different meanings (`doc/execution-semantics.md` §5). The first is "who owns execution rights right now"; the second is "which run is actually live". This separation is what makes recovery work — Paperclip can clear stale `executionRunId`s on restart while preserving `checkoutRunId` ownership.

Push model + atomic checkout = no scheduler/agent races. Compare to our daemon's 30s dispatch cycle reading `agents-tasks.db`: same shape, but we don't have the row-level conflict semantics.

### 4. UI design

The UI is genuinely polished. The strengths I could see from code:

- **`LiveUpdatesProvider` centralizes all React-Query invalidation** off a single WebSocket (`ui/src/context/LiveUpdatesProvider.tsx`, ~1,000 lines). One socket per company; every other component just reads from React Query. This is the right architecture for a multi-pane app.
- **Toast suppression for the "currently visible" issue** — when you're staring at issue ENG-123 and a comment lands on it, the toast is suppressed because you're already going to see the comment in-place (`LiveUpdatesProvider.tsx:232-302`). Small but high-quality detail.
- **Dual-source transcripts**: `useLiveRunTranscripts.ts` ingests from the WebSocket *and* polls `heartbeatsApi.log(runId, offset, limit)` on an interval (`ui/src/components/transcript/useLiveRunTranscripts.ts:215-265`). The poll backstops gaps when the WS misses events. (Note: only the transcript view does this. The global `LiveUpdatesProvider` does not — which is part of why the human saw freezes.)
- **Server-rendered SVG org chart**: `server/src/routes/org-chart-svg.ts` exists. Suggests they care about the company-tree visualization being deterministic.
- 67 pages × 149 components. Likely Tailwind + shadcn (`ui/components.json`). Storybook is wired in (`pnpm storybook`).

### 5. SDK adapter layer

`server/src/adapters/types.ts` defines `ServerAdapterModule` — a minimal interface every adapter implements: `execute`, `testEnvironment`, optional `sessionCodec`, `listSkills`/`syncSkills`, `listModels`, `getQuotaWindows`, etc. (See the imports in `server/src/adapters/registry.ts:1-100`.)

The registry has three layers:

1. **Built-ins** (`process`, `http`, plus 8 local CLI adapters) — registered statically at startup.
2. **Mutable runtime registry** — `registerServerAdapter()` / `unregisterServerAdapter()` / `requireServerAdapter()` (`server/src/adapters/registry.ts`, see `adapter-plugin.md` for the rationale). Built-ins go through the same mutable map.
3. **External plugins** — `server/src/adapters/plugin-loader.ts` loads packages from `~/.paperclip/adapter-plugins.json`. `loadExternalAdapterPackage()` (line 166) imports the package's `createServerAdapter()` and validates it. There's also `reloadExternalAdapter()` (line 206) that busts the ESM module cache via a `?t=${Date.now()}` query string — clever for dev iteration without server restart.

UI parsers live alongside the adapter package (`./ui-parser` export with a contract version field, `plugin-loader.ts:82-141`) and are extracted on demand. The parser source is sandboxed and run in a worker (`ui/src/adapters/sandboxed-parser-worker.ts`) so a bad parser can't crash the board UI.

This layer is genuinely well-shaped. The interface is small enough to implement cleanly and the contract is expressed in code, not config.

## Weaknesses — by failure mode

### 1. Token burn — why?

Three compounding causes:

**(a) Every heartbeat re-spawns Claude as a fresh subprocess with a freshly-rebuilt prompt.**

`packages/adapters/claude-local/src/server/execute.ts:307-660`. Each invocation:

1. Builds a runtime config (cwd, env, workspace stuff) — `buildClaudeRuntimeConfig`, lines 114-268.
2. Builds a "prompt bundle" — symlinks all relevant skills into a content-addressed cache dir, plus an `agent-instructions.md` file (`prompt-cache.ts:132-172`).
3. Renders `DEFAULT_PAPERCLIP_AGENT_PROMPT_TEMPLATE` (15 multi-line bullets — `server-utils.ts:90-105`) AND `renderPaperclipWakePrompt` (the per-wake delta, can be 50+ lines including comment summaries, blocker summaries, child issue summaries — `server-utils.ts:594-810`) AND a "session handoff note" AND a "task context note".
4. Spawns `claude --print - --output-format stream-json --verbose [--resume <sessionId>] [--append-system-prompt-file ...] --add-dir <skillsDir>` and feeds the prompt over stdin (`execute.ts:577-654`).

The Claude CLI then loads its own context (CLAUDE.md, MCPs, tool defs) on top of the injected prompt. So each tick pays for: Paperclip-injected prompt (1-3K tokens) + Claude CLI's own boot context (5-15K tokens) + skill files re-read (varies). Without a session resume, the agent re-reads its system prompt every 30 seconds.

**(b) Session resume is conditional on a fragile match**:

`execute.ts:495-537`. `--resume <sessionId>` is only used when **all** of these are true:
- `runtimeSessionId` (last session id from `agent_task_sessions`) is non-empty
- `runtimePromptBundleKey` matches the current bundle key (i.e. skills + instructions content-hash unchanged)
- `runtimeSessionCwd` matches `effectiveExecutionCwd`
- Remote execution identity matches (or both are local)

Any change to skills (touching a skill file rebuilds the bundle key — `prompt-cache.ts:86-107` hashes file contents recursively), any cwd change, any remote-execution identity change → resume is rejected, fresh session, full system-prompt re-injection. The code even logs "...will not be resumed in <cwd>. Starting a fresh remote session." (line 515). So a single skill edit blows the cache for every agent that uses that skill.

**(c) Recovery and watchdog loops produce *more* heartbeats**:

`server/src/index.ts:718-783` — every 30s the same `setInterval` runs:
- `heartbeat.tickTimers()` (timer-driven wakes)
- `routines.tickScheduledTriggers()` (cron triggers)
- `heartbeat.reapOrphanedRuns()` (5-min staleness threshold)
- `heartbeat.promoteDueScheduledRetries()`
- `heartbeat.resumeQueuedRuns()`
- `heartbeat.reconcileStrandedAssignedIssues()`
- `heartbeat.reconcileIssueGraphLiveness()`
- `heartbeat.scanSilentActiveRuns()`
- `heartbeat.reconcileProductivityReviews()`

If anything looks "stranded" the reconciler **enqueues another wake**. So a single stuck ticket can trigger continuation wakes, recovery wakes, productivity-review wakes — each one a fresh Claude invocation.

The default `intervalSec` minimum is 30s and `maxConcurrentRuns` defaults to 20 (`SPEC-implementation.md:679`, `heartbeat.ts:7783-7789`). With 5 agents × heartbeat every 60s × ~10K-token prompts × no session resume on skill edit, it is entirely plausible to burn $10+ in an idle hour without producing any output — especially because the default prompt template tells the agent to "Start actionable work in this heartbeat" (`server-utils.ts:94`), which means each tick the agent does *something* (fetches state, comments, attempts work) before exiting.

### 2. Heartbeat fragility — why?

The user-facing "heartbeat" disconnects are about the WebSocket, not the agent heartbeat scheduler. They share the name confusingly. There are three real bugs in the live-event design:

**(a) No replay buffer.** `server/src/services/live-events.ts:1-54`:

```ts
const emitter = new EventEmitter();
emitter.setMaxListeners(0);
let nextEventId = 0;
function toLiveEvent(input: ...) {
  nextEventId += 1;
  return { id: nextEventId, companyId, type, createdAt, payload };
}
export function publishLiveEvent(input) {
  const event = toLiveEvent(input);
  emitter.emit(input.companyId, event);
  return event;
}
```

A vanilla in-process `EventEmitter`. If a subscriber isn't connected when an event fires, the event is gone. The id is monotonic and per-server-process (so it resets on restart). There is no event store, no resume-from-id semantics. The WebSocket layer (`server/src/realtime/live-events-ws.ts:208`) just calls `subscribeCompanyLiveEvents` and forwards events live.

**(b) Server-side ping kills the connection silently.** `live-events-ws.ts:190-199`:

```ts
const pingInterval = setInterval(() => {
  for (const socket of wss.clients) {
    if (!aliveByClient.get(socket)) {
      socket.terminate();
      continue;
    }
    aliveByClient.set(socket, false);
    socket.ping();
  }
}, 30000);
```

If a client misses one pong (network blip, OS suspend, browser throttling a background tab), the next interval terminates it. The browser sees an `onclose` and reconnects with exponential backoff (1s → 15s, `LiveUpdatesProvider.tsx:949-957`). During the gap, all events are lost — and there's no resume token, so the UI just starts receiving events again from "now". State that changed during the gap remains stale in React Query until either (i) the user navigates and forces a re-fetch or (ii) some unrelated invalidation happens.

**(c) "Says heartbeat again" almost certainly = the React-Query cache was rebuilt from stale REST data after reconnect, while a new heartbeat was already running.** Because `LiveUpdatesProvider` only invalidates React Query on incoming events (`invalidateHeartbeatQueries` etc., line 609-625), and reconnect doesn't replay the events that fired during the gap, the cached "active run" can show the old run as still queued/running long after it actually finished. The UI then renders a stale "heartbeat" pill.

The transcript view dodges this because it polls `heartbeatsApi.log(runId, offset, limit)` independently (`useLiveRunTranscripts.ts:215-265`) — but that's a per-component fix, not a systemic one. The "freeze" the human reported is the global UI's React-Query state going stale and not being refreshed until the next manual action.

### 3. MCP installation pain — why?

**There is no first-party MCP installer in paperclip for end-user agent-side MCPs.** Searching the entire repo for MCP install/config code yields three things:

1. `packages/mcp-server/` — Paperclip's *own* MCP server. This is the inverse direction: a tool the agent can call to read/write Paperclip tickets. Not relevant to "I want my agent to use a Google MCP."
2. `packages/adapters/claude-local/src/server/claude-config.ts:1-15` — `SEEDED_SHARED_FILES` lists exactly: `.credentials.json`, `credentials.json`, `settings.json`, `settings.local.json`, `CLAUDE.md`. **`.mcp.json` is not in the list.** So when paperclip seeds the remote Claude config, MCP server definitions don't travel with it.
3. The Claude CLI (the actual subprocess) reads its own `~/.claude/settings.json` and `~/.claude.json` per its own rules. Paperclip just spawns the CLI; whatever MCPs the operator has registered in *their* Claude config is what the agent gets.

So the user-facing flow when the human said "I tried to install a Google MCP":

- There's no UI in paperclip for it. The user (probably) asked the agent to do it.
- The agent presumably tried `claude mcp add ...` or to write to `~/.claude/settings.json`. But the agent doesn't run as the operator's user, doesn't have an interactive Claude CLI session, and the Paperclip-prepared `claude-config-seed` directory copy excludes MCP config files.
- The agent loops, retries, asks for clarification, burns tokens, never produces a working MCP.

The deeper design issue: **paperclip treats the agent CLI as opaque**. It seeds auth credentials and a CLAUDE.md, sets some env vars (`PAPERCLIP_*`), and otherwise punts. There's no abstraction for "tools the agent can call beyond what Paperclip itself exposes." Compare to our harness (pitfall #13) where this surface is at least *thinkable* via `agents.<name>.extra_mcp_servers` — we have a place to put the answer, even if we did the wrong thing with `mcp_servers:` originally.

## Orchestration model — three dimensions

The Worker / Role / Session decomposition is not how Paperclip thinks about it. Paperclip has:

| Concept | Where it lives | Notes |
|---|---|---|
| **Agent identity** (≈ Worker) | `agents` row | UUID `id`, `name`, `role`, `reports_to`, `adapter_type`, `permissions`. Persistent. |
| **System prompt / behavior** (≈ Role) | `agents.adapter_config.instructionsFilePath` (per-agent, points at a markdown file like `AGENTS.md`) + `DEFAULT_PAPERCLIP_AGENT_PROMPT_TEMPLATE` (global, baked into the binary) + skill bundles | **Fused into the agent identity.** One agent has exactly one instructions file. To run the same person under a different role, you make a new agent. |
| **Conversation thread** (≈ Session) | `agent_task_sessions` row, keyed by `(companyId, agentId, adapterType, taskKey)` | `taskKey` is typically the issue id, so each (agent, ticket) pair gets its own session. The session id (`sessionDisplayId`) is the underlying CLI's session id — `claude --resume <id>`. |

Concrete answers to the questions in the brief:

- **Can the same agent identity have multiple system prompts in different contexts?** No. Every agent has exactly one `adapter_config` and one `instructionsFilePath`. To change behavior, you create another agent.
- **Does a session resume across reconnects, or always start fresh?** It tries to. `agent_task_sessions.sessionParamsJson.sessionId` is read on each new heartbeat; if the conditions in `execute.ts:495-537` (matching cwd, prompt bundle key, remote-execution identity) all hold, the underlying CLI is invoked with `--resume`. Otherwise it starts fresh. **Importantly, this is `claude --resume` — replaying the CLI-side conversation cache, not a Paperclip-side state.** Paperclip itself has no notion of conversation continuity beyond pointing the CLI at its previous session id. If `~/.claude` was wiped, the resume would fail silently and the agent would start fresh.
- **Is there a notion of agent identity that's distinct from "this session"?** Yes — the `agents` table is the persistent identity. Sessions are per-(agent, task) and recreated freely. But the agent identity is fused with role.
- **What ties a worker to a ticket — pull, push, claim, dispatch?** **Push, with atomic checkout.** The scheduler `enqueueWakeup`s for the agent (push); the agent's run process calls `POST /issues/:issueId/checkout` (atomic claim). Failed claim returns 409 with current owner. There is no agent-side polling of a queue; the agent process is invoked-then-exited per heartbeat.

**Implication for our harness.** Paperclip fuses Worker and Role. That's a design choice that simplifies the data model (one agent = one identity = one prompt) but *prevents* the thing we're trying to do — having `dev-alex` work on a feature ticket and then a code review ticket with a different review-flavored prompt. To get that in Paperclip you'd need two agents (`dev-alex-implementer`, `dev-alex-reviewer`) and synchronize their sessions manually. Our intuition that those should be separable is correct, and Paperclip's model is the limiting case to argue against.

## What's worth borrowing (for ~/code/agents)

1. **The issue / issue_relations data model + liveness contract**.
   - Pattern: separate `parent_id` (structure) from `issue_relations` (typed dependency edges). Add a documented contract for what "non-terminal status with no live execution path" means and a periodic reconciler that creates *visible* recovery tickets when invariants break.
   - Why: solves our pitfall #8 (silent failure) at the orchestration layer instead of per-script. Right now we discover stuck tickets only when Human notices.
   - Cost: medium. Schema is small (one new table + a few fields on `tickets`). The reconciler is the real work — a few hundred lines of "walk the graph and check invariants." Paperclip's own `reconcileIssueGraphLiveness` lives inside `heartbeat.ts:7855` lines, but the *concept* is small; their version is bloated by other things.
   - Doesn't transfer cleanly: their tight integration with `executionRunId` / `checkoutRunId` assumes one-tmux-window-per-ticket, which is approximately our model already, so this part should map cleanly.

2. **Atomic checkout via single-row UPDATE with status guard**.
   - Pattern: `POST /issues/:id/checkout` does `UPDATE WHERE id = ? AND status IN (?) AND (assignee IS NULL OR = :me)`. Updated row count = 0 → 409. (`SPEC-implementation.md:540-554`.)
   - Why: cheap concurrency safety. We claim tickets via Leantime API today; if two daemons ever run, we'd race. With our SQLite `.agents-tasks.db` we already have single-writer, but the pattern is good defensive design and trivial to add.
   - Cost: small. One SQL statement.
   - Doesn't transfer: nothing — this is a primitive.

3. **`ServerAdapterModule` interface + mutable registry**.
   - Pattern: a small interface (`execute`, `testEnvironment`, `sessionCodec`, `listModels`, ...) plus a `register/unregister` runtime registry, plus an optional external plugin loader.
   - Why: today our `templates/v2/*.md` are agent-type prompts, but the actual SDK binding is hardcoded into `setup-agents.py` and the daemon. If we wanted to add Codex or Gemini, we'd have to edit the harness. Paperclip's adapter shape would let us add a new SDK by writing one Python module.
   - Cost: medium. Probably 200-400 lines of Python to define the interface + registry + a stub loader. We don't need the external plugin sub-system yet.
   - Doesn't transfer cleanly: their `--resume <sessionId>` semantics rely on CLI-specific session state living in `~/.claude` etc. In tmux-window-based agents the equivalent is "scroll back the same window," which is a different model.

4. **`agent_task_sessions` keyed by `(agent, adapter, taskKey)`**.
   - Pattern: a table that maps "this agent on this ticket" to a CLI session id. Lets the dispatcher say `claude --resume <id>` only when the bundle hash + cwd match.
   - Why: today our session stickiness is tmux-window-name + `~/.claude/projects/` symlinking (memory note "Session stickiness"). It works but is fragile across rename. Persisting the linkage in a small DB table would survive a window restart.
   - Cost: small. One table + a write at session-end.
   - Doesn't transfer cleanly: we'd need to define what "session id" means for a tmux-based agent — probably the path to a Claude `~/.claude/projects/<hash>/` directory.

5. **Origin classification for auto-generated tickets**.
   - Pattern: `originKind` + `originId` + `originFingerprint` on the issue, with conditional unique indexes that prevent more than one open ticket per `(originKind, originId)` of certain types. (`packages/db/src/schema/issues.ts:85-133`.)
   - Why: Prevents the watchdog from creating duplicate recovery tickets. Our daemon can today; this would be a clean fix.
   - Cost: small. Three text columns + a partial unique index per origin type.
   - Doesn't transfer: nothing.

6. **The wake delta prompt format (when *not* doing token-burn things)**.
   - Pattern: when resuming a session, instead of re-injecting the full system prompt, inject a small "Resume Delta" block that contains *only* what changed (`renderPaperclipWakePrompt` with `resumedSession=true`, `server-utils.ts:608-624`). Inline the new comments rather than telling the agent to fetch them.
   - Why: cuts heartbeat cost. Our agents currently re-read the full ticket on every wake.
   - Cost: medium. Requires a notion of "what's new since last wake" per-agent, which requires per-agent watermarks on tickets (we sort of have this in the inbox model).

## What's worth avoiding

1. **Per-heartbeat CLI subprocess as the only execution mode.** This is the architectural tax that makes everything else expensive. If you commit to "every wake = fresh process," you're locked into either re-reading system prompts or building a brittle resume cache. Our tmux-window-per-agent model has its own pain (manual restarts, scroll-back leakage) but at least the conversation is genuinely persistent — no resume gymnastics.

2. **In-process EventEmitter as the only event bus.** Paperclip's `live-events.ts` works for a single-server local-trusted deployment, but it has no replay, no persistence, and no consistency story across server restarts. If we add live-event broadcast to our daemon, we should make events monotonically-id'd and replayable from a small ring buffer (last 1000 events, kept in SQLite or in-memory). Otherwise we'll reproduce the "freeze on reconnect" bug.

3. **Fusing role into agent identity.** Paperclip has one `instructionsFilePath` per agent. We've already noticed this is the wrong factoring (the question Human is wrestling with). If/when we redesign, **keep Worker (identity, persistent) and Role (prompt, swappable) as separate dimensions**, and let Session bind a (Worker, Role) pair to a Ticket. Paperclip is a cautionary tale here.

4. **Watchdog loops that re-wake the agent on every "stuck" condition.** Paperclip's recovery loops can each enqueue a wake; in pathological cases they fan out (continuation wake → productivity review wake → stranded recovery wake → ...). Each wake = one fresh Claude invocation. The intention is good ("don't let work die silently") but the implementation costs $$. Our equivalent should be "create a *visible* ticket for the human/admin to triage" rather than "burn tokens trying to auto-recover." We already do this for some flows; codify it.

5. **A 7,855-line `heartbeat.ts`.** This file does everything: wakeup, queue, scheduler, atomic checkout, runtime services, watchdog reconciliation, productivity review, cost accounting, retry logic. It's an architectural smell — once a service has no boundaries, every change costs more than the last. If we grow our daemon, force boundaries early.

6. **Treating the agent CLI as fully opaque.** Without an MCP-config seam, paperclip can't do a clean "install Google MCP for this agent." We already sort-of have one (`agents.<name>.extra_mcp_servers`); we should formalize it and surface it in the UI.

## Open questions for human follow-up

1. **What model was the human running when "tons of tokens" got burned?** Opus vs Sonnet vs Haiku changes the cost story by 5-10×. If it was Opus on the default 30s heartbeat with multiple agents, even *correct* behavior would feel expensive.

2. **Did the human see the "Starting a fresh remote session" log line in the agent transcripts?** That would confirm the resume cache was being invalidated. It's the cheapest signal for "yes, you're paying for full system-prompt re-injection every tick."

3. **When the heartbeat WS disconnected, did the underlying agent actually keep running, or did the UI show ghost activity that wasn't real?** The two failure modes look identical from the dashboard; only `heartbeat_runs.status` in the DB tells you which it was. This affects whether the fix is "replay events on reconnect" or "actually kill the run when the operator sees disconnect."

4. **What was the exact MCP install attempt?** Did the human ask the agent to run `claude mcp add ...` (which would only affect the agent's transient session and not survive)? Or to edit `~/.claude/settings.json` (which the agent doesn't run as its owner-permissions in some configs)? The fix is different per case.

5. **How many tickets were active during the reported "freeze"?** If `>20`, the `maxConcurrentRuns` clamp + watchdog re-wake interaction may be the culprit rather than the WS layer.
