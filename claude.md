# Agent Harness

## Purpose

Multi-agent development platform that orchestrates multiple Claude Code agents as a team. Agents communicate through a shared MCP server, pick up tasks from a project management system (Leantime), and collaborate through structured message passing and ticket workflows.

## Tech Stack

- **Runtime**: Python 3.12, FastMCP, SQLite
- **Agent shell**: Claude Code CLI (`claude` command), tmux sessions
- **Task management**: Leantime (self-hosted), accessed via JSON-RPC API
- **Communication**: agents-mcp daemon (FastMCP SSE server on :8765)
- **Proxy**: Per-agent MCP proxy (stdio-to-SSE bridge)

## Architecture

```
tmux sessions (one per agent)
  -> claude CLI with MCP proxy (stdio)
    -> agents-mcp daemon (SSE on :8765)
      -> SQLite stores (.agents-mcp.db, .agents-tasks.db)
      -> Leantime JSON-RPC API (:9090)
```

- **Daemon** (`services/agents-mcp/`): Central MCP server. Handles messaging, profiles, dispatch, ticket operations.
- **Proxy** (`services/agents-mcp/src/agents_mcp/proxy.py`): Per-agent stdio-to-SSE bridge with auto-reconnect.
- **Dispatcher** (`dispatcher.py`): Runs every 30s. Checks messages first, then tasks. Wakes idle agents.
- **SQLite**: Single-writer. `.agents-mcp.db` for profiles/messages/notifications. `.agents-tasks.db` for task cache.

## Key Directories

- `services/agents-mcp/` -- Daemon source code
- `templates/` -- Agent role configs (admin/, dev/, qa/, product/, ops/, shared/)
- `templates/shared/skills/` -- Skills available to all agents
- `projects/` -- Sub-project working directories
- `agents/` -- Per-agent working directories and logs
- `tests/` -- E2E and integration tests
- `.claude/agents/` -- Claude Code agent definitions (role prompts)

## Conventions

- Agent IDs use `<role>-<name>` format (e.g., `dev-alex`, `qa-lucy`, `product-kevin`)
- All inter-agent communication through MCP tools (send_message, reassign_ticket, etc.)
- Ticket tags: `agent:<name>` for assignment targeting
- Status codes: 0=done, 1=locked, 3=new, 4=in-progress, -1=archived. Never use status=2.
- Skills are SKILL.md files in a named directory under `templates/<role>/skills/`
- Pub/Sub: `ticket_subscribers` + `notifications` tables for ticket update notifications

## Known Pitfalls

1. **Don't kill admin's tmux window** -- admin manages dispatch; killing it stops all agent coordination.
2. **SQLite single-writer** -- No concurrent writes. The daemon serializes access, but direct DB writes will conflict.
3. **Claude API rate limits** -- Shared across all agent sessions. Bursts of agent activity can cause 429s.
4. **Context loss on restart** -- Agent memory is ephemeral. Use ticket comments and docs for persistence.
5. **Leantime API quirks** -- `Tickets.patch` returns false even on success (verify with getTicket). Comment API uses plugin endpoint. See MEMORY.md for details.
6. **MCP proxy disconnect** -- SSE connections drop. Proxy has auto-reconnect, but long outages can stall agents.
7. **Don't use status=2** -- Reserved/broken. Use DEPENDS_ON pattern (status=1 + linked ticket) for blocking.
8. **429 rate limiting on Leantime** -- Space API calls 15-30s apart when doing bulk operations.

## Current Status

v2 migration in progress. See `RETROSPECTIVE.md` for lessons from v1 and `V2-PROGRESS.md` for migration status.

## References

- Agent role prompts: `.claude/agents/*.md`
- Shared context and permissions: `templates/shared/context.md`
- Team roster: `agents/shared/team-roster.md`
- Task management skill: `templates/shared/skills/tasks/SKILL.md`
- Development workflow: `templates/shared/skills/development-workflow/SKILL.md`
- Dispatch system: `services/agents-mcp/src/agents_mcp/dispatcher.py`
