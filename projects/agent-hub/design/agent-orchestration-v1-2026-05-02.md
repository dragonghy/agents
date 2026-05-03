# Agent Orchestration Redesign — v1 Design Doc

**Date**: 2026-05-02
**Author**: admin (forked discussion session) + Human (Chairman)
**Status**: Draft for review
**Scope**: Agent Orchestration layer rewrite. Memory and Tooling layers receive minimal touch.

---

## TL;DR

1. **Three-pillar split**: Memory (Ticket System), Orchestration (Profile + Session + TPM), Tooling (MCP / Skills / Daemons / Channels). They're decoupled — changing one shouldn't ripple into the others.
2. **Profile = the agent**. There is no "Worker" abstraction. A Profile is a system prompt + capability set + description. `dev-alex`-the-name-with-ID was a fiction; `Developer` Profile is real.
3. **Session is stateless**. Each message into a session = an independent agent request; full conversation history is reconstructed from storage and re-injected into the LLM. No long-lived agent process. State lives in tickets.
4. **TPM (Coordinator) per ticket** — itself just another Profile, with a special purpose: read ticket comments, decide next action, spawn / message subagents, drive ticket to closure.
5. **Sessions can exist without tickets** — Telegram chats, Web UI direct sessions, scheduled tasks. Ticket binding is optional metadata, not architectural.
6. **Daemon goes from router to runner**. tmux + CLI dispatch dies; daemon hosts the SDK clients, makes API calls, streams to Web UI, handles cost / cache / retries.
7. **Multi-SDK via Adapter layer** — Claude / OpenAI / Gemini are pluggable behind a single internal interface; Profile picks runner.
8. **Comments are the bus** — subagents never talk to each other directly. TPM is the only orchestrator. Human can drop into any session and chat directly.

---

## Goals

- Decouple **what an agent is** (Profile) from **what it's doing right now** (Session) from **what it remembers** (Ticket).
- Survive daemon restart without losing work-in-flight: state lives in tickets + serialized session history, not in-memory.
- Support multiple LLM providers under one orchestration model.
- Make Web UI the primary surface for agent operations; Telegram / Slack become I/O channels into the same model.
- Allow Human to drop directly into any agent's conversation without going through ticket comments.

## Non-goals

- Reuse the existing tmux-based dispatcher. It's being retired.
- Preserve `dev-alex` / `qa-lucy` named instances. The new Profile system makes per-name instances unnecessary; old data stays for audit but new sessions don't materialize them.
- Preserve current `claude --agent <name>` CLI bootstrap. SDK invocation replaces it.
- Build a new Ticket System. The existing Workspace → Project → Ticket model + the soft-dependency DAG just merged is sufficient.
- Cross-LLM agent switching mid-session. A session is bound to one Adapter for its lifetime. (Future work — possible but not v1.)

---

## Three-Pillar Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  Memory                                                          │
│  ─────────                                                       │
│  Ticket System: workspace → project → ticket → comments          │
│  Soft-dep DAG: ticket_dependencies (parent → child edges)        │
│  Single source of truth for "what's the work, what was decided"  │
│                                                                  │
│       ↑ read/write via ticket APIs and comments                  │
│       │                                                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Orchestration                                                   │
│  ─────────                                                       │
│  Profile registry: Developer, Architect, QA, TPM, ...            │
│  Session manager: stateless sessions, multi-binding              │
│  TPM Coordinator: per-ticket Profile that drives the work        │
│  Adapter layer: Claude SDK / OpenAI SDK / Gemini SDK pluggable   │
│  Daemon: hosts SDK runners, makes API calls, streams results     │
│                                                                  │
│       ↑ Profile capabilities reference from registry             │
│       │                                                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Tooling                                                         │
│  ─────────                                                       │
│  MCP servers: agents-mcp, google_personal, imessage_personal,    │
│               wechat_personal, microsoft, 1password, agent-hub   │
│  Skills: shared (templates/shared/skills/) + per-Profile         │
│  Local daemons: telegram-bot, mcp-daemon, leantime API           │
│  Third-party channels: Telegram, Slack, Web UI                   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Decoupling principle**: changing tooling (add a new MCP) doesn't require changing orchestration. Changing the LLM provider (swap Claude for Gemini for one Profile) doesn't require changing memory. Each pillar communicates with adjacent pillars through narrow, documented interfaces.

---

## Pillar 1: Memory — Ticket System (recap)

No redesign. We keep what we have, plus the soft-dep DAG that just landed.

### Hierarchy

```
Workspace (1=Work, 2=Personal)
└── Project (Leantime project entity, e.g. agent-hub)
    └── Ticket
            • Status: 0=Done / 1=Blocked / 3=New / 4=WIP / -1=Archived
            • Priority, tags, assignee, comments
            • Relationships: parent → child via ticket_dependencies
                  edge (A, B) means "A depends on B" = "B is A's child / prerequisite"
                  example: #493 (umbrella) depends on #494, #495 (sub-tickets)
```

### What changed in this redesign

- **Ticket no longer has a fixed `assignee`** in the orchestration sense. The tag stays for filtering / display, but dispatch logic doesn't read it. Instead, every active ticket has a TPM session, and the TPM decides which Profiles to spawn.
- **Comments become a typed event stream**, not just freeform text. Comments still display as text, but the orchestrator emits events on `comment_created`, with metadata (`source_session_id`, `source_profile`, `comment_kind`).

### Soft-dep DAG semantics (just merged on `feat/ticket-dag-soft-deps`)

- Edge direction: `(parent, child)` — parent depends on child
- DAG is **soft**: dispatcher does not consult dependencies. Profiles / TPM decide for themselves whether they're blocked.
- Backfill: every existing `dependingTicketId` and `milestoneid` produces an edge `(parent_id, ticket_id)`.
- New API: `add_ticket_dependency`, `get_ticket_dependencies` (children, one hop), `get_ticket_descendants` (full subtree), `get_ticket_dependents` (parents, one hop), `get_ticket_ancestors`, `remove_ticket_dependency`. Cycle detection rejects edges that close a loop.
- Old APIs (`update_depends_on`, `get_children`, `get_parent_chain`, `upsert_subtask`, `get_all_subtasks`) preserved; they read/write the DAG internally for consistency.

---

## Pillar 3: Tooling — Inventory (no design work)

Existing components, lifted from the current system. Each Profile declares its capabilities by referencing entries here.

### MCP servers (currently registered or planned)

| MCP | Scope | Purpose |
|---|---|---|
| `agents` | All agents | Ticket CRUD, comments, message bus (legacy P2P will be deprecated) |
| `agent-hub` | Most agents | VM management, browser automation, SSH, memory facts |
| `1password` | ops + admin | Credential reads |
| `microsoft` | (work agents only — pre-existing leak, see pitfall #13) | Outlook + Teams |
| `google_personal` | assistant-aria only | Gmail + Calendar + Drive |
| `imessage_personal` | assistant-aria only | iMessage read + send |
| `wechat_personal` | assistant-aria only | WeChat read + send (4.x AXName parser, clipboard CJK paste) |

Per-Profile isolation is enforced at config load (see claude.md pitfall #13: top-level `mcp_servers:` leaks; use `extra_mcp_servers:` per agent / per Profile).

### Skills (shared)

`templates/shared/skills/`: agent-identity, claude-md-guide, daily-journal, deep-dive, development-lifecycle, executive-brief, inspect-agents, publishing, tasks, ticket-comment-protocol, ...

### Skills (per-Profile)

`agents/<profile>/.claude/skills/`: per-agent symlinks. Examples:
- `assistant-aria` has `personal-mcp-toolkit`, `google-personal-mcp` (private to it)
- `admin` has `create-skill`, `dispatch`, `system-testing`, `inspect-agents`

### Local daemons / services

- `services/agents-mcp/` — central MCP daemon (will be heavily extended; see Orchestration)
- `services/telegram-bot/` — Telegram I/O
- `services/imessage-mcp/`, `services/wechat-mcp/` — local UI-automation MCPs
- Leantime API at `http://localhost:9090/api/jsonrpc` — ticket store

### Third-party channels

- Telegram (existing bot)
- Slack (planned, same channel-adapter shape)
- Web UI (planned, primary surface; reads daemon state via REST + WebSocket for live updates)

**Tooling interface contract**: a Profile declares its tooling needs in its definition (frontmatter); the orchestrator resolves them at session-creation time and provides them to the LLM. Profiles never bind to specific tool implementations — they bind to logical names (`gmail.search`) and the registry hands back the active impl.

---

## Pillar 2: Orchestration — The Redesign

This is the body of the doc. Everything else is recap or context.

### 2.1 Profile

A **Profile** is a static definition describing one kind of agent. Format inspired directly by Claude Code's `.claude/agents/<name>.md`:

```markdown
---
name: architect
description: Senior software architect. Reads code, identifies design issues, proposes structural fixes. Use when a ticket requires "is this approach sound?" before implementation.
runner_type: claude-sonnet-4.6
tools:
  - Read, Glob, Grep, Bash
mcp_servers:
  - agents
  - agent-hub
skills:
  - development-lifecycle
  - claude-md-guide
---

# System prompt

You are an experienced software architect. Your role is...
```

### Profile registry

- One file per Profile in `profiles/<name>/profile.md`
- Loaded by daemon at startup
- `description` field is **machine-readable** — it's what TPM uses to pick which Profile to spawn ("read every Profile's description, pick the most relevant for this work")
- Versioned: editing a Profile creates a new revision; existing sessions keep using the version they were spawned with (so re-running an old session is reproducible)

### Profile examples (initial set)

| Profile | Description (truncated) | Use |
|---|---|---|
| `tpm` | Per-ticket coordinator. Reads comments, decides next action, spawns/messages subagents | 1 per active ticket |
| `architect` | Senior architect, designs structural fixes | Spawned by TPM for design questions |
| `developer` | Implements code changes, tests, opens PRs | Spawned by TPM for implementation |
| `qa` | E2E + requirement verification | Spawned by TPM for verification |
| `data_scientist` | Analyses data, produces tables / plots | Spawned by TPM for data questions |
| `secretary` | Front-door generalist for ad-hoc Human conversations. Routes requests, spawns subagents (housekeeper for life tasks, TPM-handles for ticket work, etc.). Plays the role admin used to. | Default Profile for Telegram and Web UI direct-chat |
| `housekeeper` | Daily-life ops: email, calendar, messaging | Spawned by `secretary` when a Human request needs concrete personal-life action |
| `ops` | Infra, domains, servers (existing role) | TPM-spawned or Human-direct |

### What was wrong with the old `dev-alex` / `qa-lucy` / etc. naming

Those were `(template, instance_name)` pairs. The instance name had no semantic value — `dev-alex` and a hypothetical `dev-emma` would have identical behavior. The persona was a fiction. Multiple parallel Developer sessions today spawn 3 separate `dev-alex` sessions that pretend to share an identity but don't.

In the new model, "Developer" is a Profile, and each spawn is just a Session of that Profile. No instance names. If you need to identify a specific running session, you use its `session_id`.

### 2.2 Session

A **Session** is a single conversation thread with one Profile.

#### Schema

```sql
CREATE TABLE session (
  id              TEXT PRIMARY KEY,           -- e.g. "sess_01H..."
  profile_name    TEXT NOT NULL,
  ticket_id       INTEGER,                    -- nullable
  binding_kind    TEXT NOT NULL CHECK (
                    binding_kind IN ('ticket-subagent', 'human-channel', 'standalone')
                  ),
  channel_id      TEXT,                       -- e.g. "telegram:<chat_id>", null for non-channel
  parent_session_id TEXT,                     -- which session spawned this (TPM session, or null)
  status          TEXT NOT NULL CHECK (status IN ('active', 'closed')),
  runner_type     TEXT NOT NULL,              -- e.g. "claude-sonnet-4.6", "gpt-5"
  native_handle   TEXT,                       -- Adapter-specific: for Claude, the SDK session_id;
                                              -- for future adapters, whatever they need to locate history
  created_at      TEXT DEFAULT (datetime('now')),
  closed_at       TEXT,
  cost_tokens_in  INTEGER DEFAULT 0,
  cost_tokens_out INTEGER DEFAULT 0
);
```

**No `session_message` table** — conversation history lives in each Adapter's native store. For the Claude Agent SDK, that's `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`, written by the SDK itself when we call `query(session_id=...)`. The SDK reloads the JSONL automatically on each call. We just hold the `session_id` in `native_handle` and pass it back to the SDK every turn.

When future Adapters land (OpenAI / Gemini), each will pick its own native storage — could be a per-Adapter table, an external service, or files. The application layer never reads conversation history directly; it always asks the Adapter via `render_history(session_id)`.

(See research notes: `projects/agent-hub/research/claude-sdk-session-model-2026-05-02.md`.)

#### Stateless execution

The key design choice: **a session is not a long-lived process**. Each "message into a session" = one Adapter call. The Adapter is responsible for loading the prior history and submitting it to the LLM. For the Claude Agent SDK, that means:

1. Look up the Profile (system prompt + tooling)
2. Look up the session's `native_handle` (SDK session_id) and `runner_type`
3. Call the Adapter — for Claude: `query(prompt=new_message, session_id=native_handle, ...)`. The SDK reloads the JSONL, applies any compaction, calls the API, streams back results, and appends to the JSONL.
4. Adapter returns final result + token usage
5. Daemon updates session metadata (cost counters, last-message timestamp) and emits events

This means:
- **No idle-state resource consumption on our side** — session metadata is rows in SQLite; the actual history is on disk in the SDK's JSONL. No process holds anything.
- **Restarts are safe** — daemon dying mid-call drops at most one in-flight LLM request; the SDK's JSONL is intact and reloadable.
- **Auto compaction free** — Claude SDK does it via `compact_boundary` events. We don't implement summarization ourselves. If we ever want custom compaction policy per Profile, we hook `PreCompact`.
- **Prompt caching free** — Anthropic's prompt cache eats the unchanged prefix on consecutive turns; ~90% discount on repeat tokens.
- **No "hibernate / resume" code path** — every turn is a one-shot Adapter call.

#### Two states only

- `active` — at least one message has been processed; ready to receive more
- `closed` — explicitly terminated; no more messages will be processed

No `idle`. The model collapses idle into active because there's no resource to release.

#### Three binding kinds

| Binding | Has `ticket_id`? | Has `channel_id`? | Triggered by | Lifecycle |
|---|---|---|---|---|
| `ticket-subagent` | ✅ | maybe | TPM (for that ticket) | TPM creates, TPM closes (or ticket close) |
| `human-channel` | ❌ usually | ✅ (`telegram:<id>`, `slack:<id>`, `web:<conn_id>`) | Human message into channel | Human or `/end` closes |
| `standalone` | ❌ | ❌ | Cron / webhook / programmatic | Whoever spawned closes |

A single session belongs to exactly one binding kind. Conversion is not supported (close + spawn new instead).

#### Session ↔ Ticket relationship

- A ticket can have many sessions (one TPM + many subagents over its lifetime).
- A session belongs to at most one ticket.
- Subagent sessions reference their parent (the TPM session) via `parent_session_id`.
- TPM session has `parent_session_id = NULL`.

### 2.3 TPM (Coordinator)

The **TPM** is a Profile, not a special class of object. What makes TPM special is its instructions:

> You are the Coordinator for ticket #N. Read the ticket's comments and decide what to do next. You can:
>
> - Spawn a new subagent (give it a Profile + a task description)
> - Push a follow-up message into an existing subagent's session (provide session_id and the message)
> - Post a comment to the ticket (status update, summary, escalation)
> - Mark the ticket done / blocked
> - Wait (no action; let more events arrive)
>
> You wake up on every `comment_created` event for your ticket. You do NOT see anything except ticket data and comments. Subagent sessions' private content is invisible to you.

#### TPM lifecycle

- Created when a ticket transitions to status=4 (WIP) for the first time, or explicitly by the dispatcher when the system decides "this ticket needs a coordinator now".
- Persists across the ticket's life. Closed when the ticket is closed (status=0 / status=-1).
- Wakes on every `comment_created` event for its ticket. Each wake is one LLM call.
- Cost: dominated by ticket history. Prompt cache (with a stable system prompt + slowly-growing comment list) keeps per-wake cost low — typically the new tokens are just "what new comment(s) did I see + what should I do".

#### Why one TPM per ticket and not one global

- Concurrency: each ticket evolves independently; TPMs in parallel don't conflict.
- Cost isolation: long-running busy ticket doesn't slow down a quick ticket's TPM.
- Restart granularity: TPM crash on ticket #500 doesn't touch ticket #501.
- Profile freedom: a future "Personal TPM" Profile (different system prompt, different tools) can run on personal-workspace tickets while the standard TPM runs on work tickets — same architecture, different instructions.

### 2.4 Communication topology

```
                            ┌────────────────────────┐
                            │ Ticket #N              │
                            │   comments[]           │
                            │   (the only bus)       │
                            └─────────┬──────────────┘
                                      ▲
                                      │ posts comment
                                      │
        ┌─────────────────────────────┼──────────────────────────┐
        │                             │                           │
        │                             │                           │
   reads comments              reads comments              reads comments
        │                             │                           │
        ▼                             ▼                           ▼
   ┌─────────┐                  ┌──────────┐               ┌──────────┐
   │  TPM    │── push msg ────▶│ Architect│               │Developer │
   │ session │── push msg ────▶│ session  │               │ session  │
   │         │── spawn ───────▶│          │               │          │
   └─────────┘                  └─────┬────┘               └─────┬────┘
        ▲                             │                           │
        │                             ▼                           ▼
   reads comments               post comment                 post comment
                                (event source)              (event source)

                             Human can drop in to ANY session:
                                Web UI / Telegram / Slack
                                                │
                                                ▼
                                  inserts user message
                                  (private, TPM doesn't see directly;
                                   subagent decides what to summarize
                                   back to ticket comment)
```

#### Rules

1. **Subagents never message each other directly**. There is no peer-to-peer SDK call between subagents.
2. **TPM is the only orchestrator**. All "let's do this next" decisions originate in TPM.
3. **Comments are the only inter-session bus**. A subagent's results reach other subagents only via TPM reading the comment and pushing follow-up messages.
4. **Human drop-in is a session-level act**, not ticket-level. Human chats with a Profile inside a session; the conversation is private to that session unless the Profile chooses to summarize back to the ticket comment.
5. **TPM only sees ticket data**. It never sees private session content (Human ↔ subagent chat). It only sees what subagents elected to commit as comments.

### 2.5 Event model

Daemon emits events; subscribers (TPM sessions, channel adapters, web UI) consume them.

| Event | Payload | Subscribers |
|---|---|---|
| `comment_created` | ticket_id, comment_id, author_session_id, comment_kind | TPM session for that ticket |
| `ticket_status_changed` | ticket_id, old_status, new_status | (rare) Profiles that need to react to status changes |
| `session_completed` | session_id, ticket_id?, profile_name | Web UI (live update) |
| `session_message_appended` | session_id, seq, role | Web UI (live stream) |
| `human_channel_message` | channel_id, session_id, body | Channel adapters |

Daemon implements a small in-process pub/sub. WebSocket / SSE pushes events to web UI. Telegram bot subscribes to events for its channels. The earlier giggly-stirring-dijkstra plan in store.py partially implements this; we'll extend it.

### 2.6 Adapter layer

A Profile's `runner_type` selects an Adapter. Each Adapter implements:

```python
class Adapter(Protocol):
    async def run(
        self,
        profile: Profile,
        history: list[Message],
        new_message: Message,
        tool_executor: ToolExecutor,
        on_stream_chunk: Callable[[str], None],
    ) -> RunResult:
        """
        Single LLM API call.
        Sends profile.system_prompt + history + new_message to the LLM.
        Streams response chunks via on_stream_chunk.
        Returns final result + token counts + any tool calls made.
        """
```

Adapters live in `services/agents-mcp/src/agents_mcp/adapters/`:

- `claude_adapter.py` — Anthropic SDK
- `openai_adapter.py` — OpenAI SDK
- `gemini_adapter.py` — Google AI SDK

A Profile declares `runner_type: claude-sonnet-4.6` or `runner_type: gpt-5` etc. The daemon's session manager looks up the matching Adapter and routes calls.

**No mid-session adapter switch in v1.** A session is bound to its `runner_type` from creation. Switching requires closing and re-spawning.

### 2.7 Daemon: from router to runner

#### Today

- Light process. SQLite + a few REST endpoints. Polls for tickets every 30s and dispatches by `tmux send-keys` into a `claude --agent <name>` window.
- Heavy work happens in the spawned Claude Code CLI processes.

#### After redesign

- Heavy process. Hosts the SDK clients in-process (one per Adapter). When a session needs to run, daemon:
  1. Loads session history from SQLite
  2. Calls the Adapter's `run()` with profile + history + new message
  3. Adapter calls Anthropic / OpenAI / Gemini API
  4. Streams response chunks back (websocket → web UI; database append → eventually consistent for non-streaming clients)
  5. Persists final messages
  6. Emits `session_completed` event, which may trigger TPM (for ticket-bound sessions) or notify Human (for channel-bound)
- tmux retained only for: admin's permanent debug window, `mcp-daemon` legacy fallback. New per-ticket sessions have no tmux footprint.
- Cost tracking: each Adapter call returns `cost_tokens_in/out`; daemon aggregates per session, per profile, per ticket, per day.
- Concurrency: daemon handles N concurrent sessions via asyncio. SDK calls are I/O-bound (long-tail latency), so async scales well.
- Crash recovery: in-flight LLM calls are lost (transient). Session history and ticket state are intact (durable). On restart, daemon re-emits `session_completed` for any session that was mid-call (best-effort) and lets TPM re-evaluate.

---

## UI Surface

### Web UI (primary)

```
┌────────────────┬──────────────────────────────────────────────┐
│ Sidebar        │  Main pane                                   │
│                │                                              │
│ ▾ Workspaces   │  [select a session or ticket from sidebar]   │
│   Work         │                                              │
│   Personal     │                                              │
│                │                                              │
│ ▾ Tickets      │                                              │
│   #493 ●       │                                              │
│   #500         │                                              │
│   #503         │                                              │
│                │                                              │
│ ▾ Active       │                                              │
│   Sessions     │                                              │
│   tpm-#493 ●   │                                              │
│   arch-#493    │                                              │
│   tg:huayang   │                                              │
│   web:abc      │                                              │
│                │                                              │
│ ▾ Profiles     │                                              │
│   tpm          │                                              │
│   architect    │                                              │
│   developer    │                                              │
│   ...          │                                              │
└────────────────┴──────────────────────────────────────────────┘
```

Three primary views:

- **Ticket view**: ticket header, comments stream, session list (pick a session → switch to Session view), DAG of dependencies, actions (close, reassign, manual comment).
- **Session view**: full conversation history with one Profile, live-streaming if active. Human can type into the input → message gets inserted into session and triggers an LLM call. Below the input: "post summary back to ticket" toggle.
- **Profile registry**: list of installed Profiles, their descriptions, recent sessions per Profile. CRUD on Profile definitions (writes to file → reloaded by daemon).

### Web UI design language — borrow from paperclip

Paperclip's UI design is rated as one of its actual strengths (see `projects/agent-hub/research/paperclip-review-2026-05-02.md`). We adopt their visual / interaction patterns where they translate cleanly:

- **Sidebar-driven navigation** with collapsible sections (workspaces, tickets, sessions, profiles)
- **Inline streaming view** for live agent output (text + tool calls + tool results, all in a single scrollback)
- **Status badges** on tickets / sessions (active dot, blocked indicator, cost badge)
- **Side-pane drop-in chat** that opens beside the ticket without losing context

We do **not** copy paperclip's underlying state management — their no-replay-buffer event stream and single-ping disconnect logic were called out in the review as failure modes to avoid. Our backend pushes events with replay support, sessions are restart-safe via DB.

### Telegram (channel adapter)

- Each Telegram chat with the bot is one or more `human-channel` sessions.
- **One chat = one Profile at a time.** No multi-Profile chat. If the user wants another Profile to chime in, the current Profile spawns a subagent itself; we don't bring a second Profile directly into the chat.
- First message → spawn session with Profile = `secretary` (default). `secretary` decides whether to handle the request itself, or to spawn a subagent (e.g. `housekeeper` for life-task actions, TPM-driven flow for ticket-bound work).
- `/profile <name>` switches to a different Profile — closes the current session, opens a new one with the new Profile.
- `/new` closes current session, opens a fresh one with the same Profile.
- `/list` shows recent sessions for this chat.
- `/session <session_id>` resumes an old session (re-loads its history; subsequent messages append to it).
- Messages in / out flow through the daemon's channel adapter, which calls `session_message_appended` events.

### Out of scope for v1

- **Slack adapter.** Same channel-adapter shape would work, but it's not a current need.
- **Direct CLI / SSH access** to the daemon. Web UI is the only operator surface. No `agents-cli` in v1; debug via Web UI logs / database inspection.

---

## Comparison with Claude Agent Teams

We compared notes earlier. TL;DR: borrow the surface API + interaction patterns; reject the lifecycle and state-storage assumptions.

### Borrow

| Claude Teams pattern | How we use it |
|---|---|
| `Agent(subagent_type, prompt, run_in_background)` | TPM's `spawn_session(profile, prompt, blocking=False)` API |
| `SendMessage(to=session_id, message=...)` for resuming a sub-agent | TPM pushes follow-up message into existing subagent session (same shape) |
| `description`-driven dispatch (selector reads each subagent's description) | TPM picks Profile to spawn by reading every Profile's `description` field |
| `.claude/agents/<name>.md` Profile definition format | Adopted directly (frontmatter + system prompt) |
| Foreground / background spawn + completion notification | Foreground = TPM blocks awaiting return; background = TPM continues, gets `session_completed` event |

### Reject

| Claude Teams assumption | Our design |
|---|---|
| Team lead's session is a long-lived process; team dies when lead dies | TPM session is stateless; restart-safe; survives daemon crash via DB-persisted history |
| State lives in lead's in-memory conversation | State lives in ticket comments + session history (DB) |
| Sub-agents communicate via lead's return value | Sub-agents communicate via ticket comments (orchestration bus) |
| Single LLM provider (Anthropic) | Adapter layer abstracts the provider per Profile |
| No external Human drop-in | Human can drop into any session via Web UI / Telegram / Slack |
| Self-cleanup tied to parent death | Sessions independent; cleanup on explicit close, ticket close, or long inactivity reaper |

---

## Migration Roadmap

Incremental. Each phase is independently deployable; we don't need a flag day.

### Phase 0 — Foundations (already underway)

- [x] Soft-dep DAG schema + APIs (`feat/ticket-dag-soft-deps` — needs review + merge)
- [x] Pub/sub event infra in store.py (partial; see giggly-stirring-dijkstra plan for the rest)
- [ ] Profile definition format spec finalized
- [ ] Adapter interface defined

### Phase 1 — Stateless Session + SDK Runner (the core enabler)

- New tables: `session`, `session_message`, `profile_registry`
- New daemon module: `session_manager` — spawn / append-message / close
- First Adapter: Claude (`claude_adapter.py`)
- First Profile loaded: `tpm` (basic instructions, can spawn but doesn't yet)
- Existing tmux-based dispatch left running in parallel; new system gates on a feature flag
- Smoke test: hand-craft a ticket session, message it, verify history persists

### Phase 2 — TPM Coordinator + Comment-driven dispatch

- TPM Profile fully wired up: spawns Developer / Housekeeper (Phase 1 set)
- **TPM auto-spawn doctrine** (system knowledge — visible in API docs + Profile prompts):
  - `status=3` (New) — ticket sits in backlog. Not walked down. No TPM spawned.
  - `status=3 → status=4` transition — daemon emits `ticket_status_changed`, listener spawns a fresh TPM session bound to that ticket.
  - `status=4` (WIP) — TPM is alive, listening for `comment_created` events on its ticket.
  - `status=4 → status=0 / -1` transition — TPM session closed.
- Subagent Profile definitions for Developer, Housekeeper, Secretary (fresh-written, with the existing `templates/v2/{development,assistant}.md` system prompts as reference inspiration only — not copied verbatim)
- One ticket migrated end-to-end: Human creates ticket (status=3) → manually transitions to status=4 → TPM spawned → TPM spawns subagent → subagent works → comment posted → TPM evaluates → ticket closed
- Old tmux dispatcher still running for fallback (other tickets still routed to legacy)

### Phase 3 — Web UI Phase 2 (interactive)

- Session view with live streaming (SSE / WebSocket from daemon)
- Drop-in: Human types in session input, message appended, LLM called, response streamed
- Profile registry UI (CRUD on Profile definitions)
- "Post summary back to ticket" action wired up
- Read-only Web Console (current state from PR #22) extended with these interactive panels

### Phase 4 — Channel Adapters

- Telegram bot rewired to new session model (spawn `human-channel` sessions, default Profile = `secretary`)
- `/profile`, `/new`, `/list`, `/session` commands
- Slack adapter (mirror of Telegram)
- Standalone session API (cron / webhook trigger)

### Phase 5 — Multi-SDK + Deprecation

- OpenAI Adapter
- Gemini Adapter
- Cost tracking dashboard (which Profile / session / ticket spends what)
- Old tmux dispatcher disabled; old `dev-alex` / `qa-lucy` definitions retired (their data preserved for audit)
- v1 setup-agents.py legacy paths removed
- claude.md updated to drop pitfall #5 (setup-agents.py overwrite warning becomes obsolete) and pitfall #11 (admin supervisor still relevant but subject to redesign)

### Phase 6 — Cleanup + observability

- Long-tail: stale-session reaper, cost alerts, Profile version pinning UI, Human drop-in audit log
- Deprecate `microsoft` MCP top-level leak (pitfall #13 cleanup) — make all per-agent
- Document the full architecture in claude.md as the new reality

---

## Open Questions

Of the 8 originally raised, 7 are resolved as of 2026-05-02. One stays open pending the Claude SDK research subagent.

### Resolved

| # | Question | Decision |
|---|---|---|
| 1 | Profile definition file location | **Top-level**: `profiles/<name>/profile.md`. Profiles are first-class artifacts. |
| 2 | Profile versioning | **No versioning.** Latest-wins, edits overwrite. Re-running an old session uses the current Profile definition; if behavior diverges, that's expected. |
| 3 | `microsoft` MCP top-level leak | **Fold to per-agent.** Same treatment as `google_personal` / `imessage_personal` / `wechat_personal` — declare under `agents.<owner>.extra_mcp_servers:`. Owner TBD when we figure out which Profile actually needs Outlook. |
| 4 | TPM cost guardrails | **Skip for v1.** Web UI will surface a cost dashboard (per session / Profile / ticket / day). We'll observe real numbers and revisit if/when there's evidence of pathological burn. No debounce / batch logic up front. |
| 6 | Daemon HA | **No HA.** Single process is fine. Crash = all sessions pause until restart; durable state in DB means no data loss. Multi-process complexity not justified. |
| 7 | Web UI authentication | **No auth in v1.** Local-network use only. Auth design deferred until external exposure is a real requirement. |
| 8 | Multi-Profile in one Telegram chat | **One chat = one Profile.** `/profile <name>` switches by closing the current session and opening a new one. If a Profile needs help from another Profile, it spawns a subagent itself — the human doesn't manage multiple Profiles in the same chat. |

### Resolved by SDK research (2026-05-02)

| # | Question | Decision |
|---|---|---|
| 5 | Session history truncation / compression | **Resolved.** Claude Agent SDK does automatic compaction via `compact_boundary` events, configurable via CLAUDE.md / `PreCompact` hook / manual `/compact`. We rely on the SDK's compaction; no application-side summarization in v1. If a Profile needs custom compaction (e.g. TPM has different priorities than Architect), it implements a `PreCompact` hook in its definition. |

### Implications of SDK research that changed the design

The SDK research showed (a) sessions are **JSONL files on disk, not in-memory objects**; (b) the SDK loads history itself when given a session_id; (c) compaction is built-in; (d) idle sessions cost only disk. Two design simplifications fell out:

- **Dropped the `session_message` table** — original schema mirrored every message into our DB. Now we trust each Adapter's native storage (Claude SDK's JSONL files for Claude sessions; future Adapters define their own). Application code asks the Adapter `render_history(session_id)` rather than reading our table directly.
- **The "stateless" model becomes thinner** — we don't manually load history before each Adapter call; the Adapter does it. Our daemon just holds session metadata + `native_handle` and passes calls through.

### Still open (none for Phase 1)

All Phase 1 design decisions are now ratified.

---

## Decision Log (already ratified in conversation)

| Decision | Rationale |
|---|---|
| Three-pillar split (Memory / Orchestration / Tooling) | Decoupling lets each layer evolve independently. |
| Profile = Role (no separate concept) | Worker abstraction was empty content — no per-instance memory or behavior. |
| TPM is just a Profile | Architectural symmetry; no special class. |
| Sessions are stateless | Restart-safe, cheap, aligns memory with Tickets pillar. |
| Two states: active / closed | No idle / hibernate complexity (because stateless). |
| Comments are the only inter-session bus | Subagents never peer-to-peer. TPM is the bus. |
| Soft-dep DAG only | Dispatcher doesn't auto-block; agents decide. |
| Adapter layer in Orchestration (not Tooling) | Adapters are how sessions land on LLM APIs, not a tool agents call. |
| Human drop-in inserts into existing session | Insert pattern, not fork. |
| Drop-in content is private to session | TPM only sees ticket comments. |
| Telegram + Web UI default Profile = `secretary` | Generalist front door; spawns `housekeeper` etc. as subagents. |
| `/new` closes current session | Sessions = single conversation unit. |
| Personal-life Profile is named `housekeeper` | Renamed from `personal_assistant` per Human's preference. |
| Front-door Profile is named `secretary` | Replaces the conceptual role admin used to play; generalist routing + spawning. |
| TPM auto-spawn fires on `status=3 → 4` transition (NOT on ticket creation) | Explicit doctrine: status=3 (New) is backlog, NOT walked-down. Status=4 (WIP) is when TPM materializes. Status=0/-1 closes TPM. This prevents "create ticket = burn LLM" surprise. |
| Phase 1 starting Profile set: tpm / developer / housekeeper / secretary | Architect / QA later when needed; data_scientist / ops further out. |
| Adapter Phase 1: Claude only (`claude-agent-sdk-python`) | OpenAI / Gemini in Phase 5. |
| No stub adapter for tests; use real Claude tokens | Token budget is fine; complexity of stub doesn't justify itself. |
| Web UI design language borrows from paperclip's UI patterns | UI design is paperclip's actual strength; we lift visual / interaction conventions but not the broken state model. |
| No Slack adapter in v1 | Telegram + Web UI cover current need. |
| No CLI / SSH access in v1 | Web UI is the only operator surface. |
| Profiles live at `profiles/<name>/profile.md` (top-level) | First-class artifact location. |
| No Profile versioning (latest-wins) | Simpler; reproducibility deferred. |
| `microsoft` MCP folded into per-agent isolation | Same treatment as other personal MCPs. |
| No TPM cost guardrails in v1 | Web UI cost dashboard will surface real numbers; revisit if pathological. |
| No daemon HA | Single process; crash = pause; data durable in DB. |
| No Web UI auth in v1 | Local-network only; auth deferred. |
| One Telegram chat = one Profile | Switch via `/profile <name>` (closes + reopens session); multi-Profile-in-chat is profile-spawns-subagent, not human juggling. |
| No `session_message` table — Adapter native storage is truth | Claude Agent SDK already persists history (JSONL); duplicating it would be redundant + bug-prone. Future Adapters define their own native store. Web UI reads via Adapter API. |
| No application-side history compression in v1 | Claude SDK auto-compacts via `compact_boundary`. Custom policies via `PreCompact` hook if a Profile needs it. |

---

## References

- Soft-dep DAG implementation: `feat/ticket-dag-soft-deps` (commits `021301b` + `ffd226d`, on local repo, not pushed)
- Paperclip architectural review: `projects/agent-hub/research/paperclip-review-2026-05-02.md`
- Pub/sub plan (partial implementation already in store.py): the giggly-stirring-dijkstra plan
- Personal MCP toolkit (per-agent isolation pattern reference): `projects/agent-hub/skills/personal-mcp-toolkit/SKILL.md`
- Pitfalls #13 (top-level `mcp_servers:` leak), #14 (action-vs-effect verification), #15 (FDA on terminal host) — claude.md
- Existing Workspace + DAG hierarchy: `services/agents-mcp/src/agents_mcp/store.py`
- Current Profile-equivalent definitions (templates): `templates/v2/{development,operations,assistant}.md`
