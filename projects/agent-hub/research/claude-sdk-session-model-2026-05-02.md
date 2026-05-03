# Claude Agent SDK Session Model — Research Notes (2026-05-02)

## TL;DR (3 lines max)

The Agent SDK is **stateless on the client object** but **stateful on disk**: every `query()` writes a JSONL transcript to `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`, and `resume`/`continue` reload it from there — there is no long-lived in-memory session. The SDK does provide automatic conversation **compaction** (summarizes older history when the context window fills) and there is **no TTL or auto-cleanup** of session files. Idle sessions cost nothing in process memory; they are just files on disk that grow until you delete them.

## Q1: Long-lived in-memory session object?

**Answer: No (mostly). The session is a JSONL file, not a process object.**

- The standalone `query()` function is one-shot: it spawns a Claude Code child process, runs the agent loop, writes the transcript, and exits. There is no client object that survives between calls. To get history on a follow-up call you must pass `resume: <id>` or `continue: true`, which causes the SDK to **reload the JSONL transcript from disk**.
- Two narrow exceptions:
  1. **Python `ClaudeSDKClient`** — an async context manager that holds a single child process across multiple `client.query()` calls. The docs describe it as "handles session IDs internally" and "must be used as an async context manager." So the *child process* is long-lived during the `async with` block, but state still lives in the JSONL on disk.
  2. **TypeScript V2 preview** (`createSession()` with `send`/`stream`) — explicitly marked unstable.
- Stateless-only mode exists in TypeScript: `persistSession: false` — "The session exists only in memory for the duration of the call. Python always persists to disk."
- Confirmed locally: `~/.claude/projects/-Users-huayang-code-agents/` contains hundreds of `<uuid>.jsonl` files, matching the docs' described layout exactly.

Sources:
- https://code.claude.com/docs/en/agent-sdk/sessions ("The SDK writes it to disk automatically...")
- https://code.claude.com/docs/en/agent-sdk/sessions ("`persistSession: false` ... The session exists only in memory for the duration of the call. Python always persists to disk.")
- https://code.claude.com/docs/en/agent-sdk/overview (Agent SDK vs Managed Agents table: "Session state | JSONL on your filesystem | Anthropic-hosted event log")

## Q2: SDK or caller maintains history?

**Answer: SDK maintains history (via the JSONL on local disk), not the caller.**

- You pass a **session ID**, not a message list. The SDK reads `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` to reconstruct context. Quote: "Sessions are stored under `~/.claude/projects/<encoded-cwd>/*.jsonl`, where `<encoded-cwd>` is the absolute working directory with every non-alphanumeric character replaced by `-`."
- The agent-loop doc is explicit on accumulation: "The context window... does not reset between turns within a session. Everything accumulates: the system prompt, tool definitions, conversation history, tool inputs, and tool outputs."
- Important caveat for our orchestration design: **the JSONL is local to the host that ran the session**. "Session files are local to the machine that created them. To resume a session on a different host... Move the session file... or don't rely on session resume." Anthropic also offers a `SessionStore` adapter for mirroring transcripts to shared storage.
- Read APIs exist for inspection: `listSessions()`, `getSessionMessages()`, `getSessionInfo()`, plus mutate APIs `renameSession()` and `tagSession()`.

Sources:
- https://code.claude.com/docs/en/agent-sdk/sessions (Tip box on `cwd` mismatch and JSONL path)
- https://code.claude.com/docs/en/agent-sdk/sessions ("Resume across hosts" section)
- https://code.claude.com/docs/en/agent-sdk/agent-loop ("The context window" section)

## Q3: Auto compression / summarization?

**Answer: Yes — the SDK does automatic compaction. 100% built-in, with hooks for customization.**

Direct quote from agent-loop.md, "Automatic compaction":

> "When the context window approaches its limit, the SDK automatically compacts the conversation: it summarizes older history to free space, keeping your most recent exchanges and key decisions intact. The SDK emits a message with `type: "system"` and `subtype: "compact_boundary"` in the stream when this happens (in Python this is a `SystemMessage`; in TypeScript it is a separate `SDKCompactBoundaryMessage` type)."

Customization knobs:
- **CLAUDE.md instructions** — the compactor reads CLAUDE.md, so you can include a "Summary instructions" section listing what to preserve. (Header name is not a magic string; matches on intent.)
- **`PreCompact` hook** — fires before compaction; receives a `trigger` field (`"manual"` or `"auto"`); useful for archiving the full transcript first.
- **Manual compaction** — send `/compact` as a prompt string.

Caveat called out by docs: "Compaction replaces older messages with a summary, so specific instructions from early in the conversation may not be preserved. Persistent rules belong in CLAUDE.md... rather than in the initial prompt, because CLAUDE.md content is re-injected on every request."

Sources:
- https://code.claude.com/docs/en/agent-sdk/agent-loop ("Automatic compaction" section)
- https://code.claude.com/docs/en/agent-sdk/hooks (PreCompact hook reference, linked from above)

## Q4: Idle session resource cost?

**Answer: Effectively zero process/server cost; only disk. No TTL, no hibernate, no auto-close.**

- Because there is no long-lived session object server-side (Anthropic is not holding state for you — the Agent SDK runs in *your* process), an idle session ID is just a `.jsonl` file on the host filesystem. Disk-only cost. No memory, no network, no timer.
- The docs describe **no TTL or auto-cleanup mechanism** anywhere on the sessions page or agent-loop page. Cleanup is the application's responsibility — they explicitly mention `listSessions()` is intended for "build custom session pickers, **cleanup logic**, or transcript viewers."
- When you `resume`, the cost shifts: the SDK re-reads the full JSONL into context on the first model call (which is then prompt-cached on subsequent turns). So a long-idle session that you eventually resume costs you tokens (history replay) plus disk I/O, not steady-state RAM.
- One contrast worth flagging for our design: **Managed Agents** (the *other* Anthropic product) does have server-hosted sessions with their own lifecycle. The Agent SDK does not. Quote: "Agent SDK | Session state: JSONL on your filesystem" vs "Managed Agents | Anthropic-hosted event log."

Sources:
- https://code.claude.com/docs/en/agent-sdk/sessions ("Resume across hosts" + cleanup mention)
- https://code.claude.com/docs/en/agent-sdk/overview (Agent SDK vs Managed Agents table)

## Implications for our orchestration design

Given the answers, **option (a) — trust the SDK as session keeper — is viable for single-host deployments**, but with caveats:

1. **The SDK already maintains a per-conversation transcript on disk and auto-compacts it.** We do *not* need our own `session_message` table just for context replay. Storing only `session_id` (+ host + cwd) is enough to resume.
2. **However**, our daemon spawns ephemeral agents in tmux on a single host (currently fine), but anything multi-host (CI workers, containers, future cloud deploy) breaks because JSONLs are host-local. If multi-host is on the roadmap, either (a) use the `SessionStore` adapter for shared storage, or (b) keep our own message log.
3. **No TTL means session files grow unbounded.** We need our own cleanup policy (cron or daemon task using `listSessions()` / file mtime).
4. **For audit / human-readable logs / Telegram cross-posting / search across all agents, we still want our own write-through log** — the JSONL is per-session and not designed for cross-cutting queries. Compaction also *summarizes away* old turns, so the JSONL is not a long-term record.
5. **Recommendation: hybrid.** Track `session_id` + `cwd` + `host` per ticket-agent; defer in-conversation context to the SDK. Keep a lightweight, write-only `agent_event` table (turn-level metadata: tool calls, costs, refusals, compact_boundary events) for orchestration/audit, not for context replay. Schema avoids the full `session_message` table.

## Sources I tried but couldn't extract from

- `https://code.claude.com/docs/en/agent-sdk/context-editing` — 404. The actual relevant content lives under `agent-loop.md` ("The context window" + "Automatic compaction" sections), which I did fetch.
- Did not deep-dive into `session-storage.md` (SessionStore adapter), `hooks.md` (PreCompact details), or `typescript-v2-preview.md` — none changed the answers to the 4 questions, and the user said keep it tight.
