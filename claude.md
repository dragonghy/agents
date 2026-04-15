# Agent Harness

## Purpose

Self-running multi-agent platform. Admin (COO) manages execution, Human (Chairman) sets direction. Agents are ephemeral — spawned per task, released when done. All state is externalized into tickets, docs, and skills.

Long-term vision: Productize into a platform enabling anyone to build a one-person company through AI-guided decision-making.

## Architecture (v2)

```
Human (Telegram / direct session)
  → Daemon (port 8765)
    → v2 Dispatcher (task-selection, 30s cycle)
      → Session Manager (spawn/monitor/release ephemeral agents)
        → tmux windows: ticket-{id}-{type}
          → Claude Code --agent {development|operations|assistant}

Data: SQLite (.agents-mcp.db, .agents-tasks.db)
Communication: Telegram bot ↔ Daemon ↔ Agent sessions
```

## Agent Types

Templates live in `templates/v2/` (development.md, operations.md, assistant.md) but **not every template has a registered instance**. Always check `list_agents` for what's actually dispatchable before assigning a ticket.

Currently registered (as of 2026-04-14):
- **admin** — COO / global config / restarts (this session)
- **ops** — infra, domains, servers, cloud
- **dev-alex** — development lifecycle (plan → PR → CI)
- **qa-lucy** — E2E + requirement verification

No `assistant` instance is currently registered. If you need a personal-assistant style task, either route to `admin` or register an instance first.

## Key Directories

- `services/agents-mcp/` — Daemon source (server.py, dispatcher_v2.py, session_manager.py)
- `services/telegram-bot/` — Telegram transport bridge
- `templates/v2/` — Agent type system prompts
- `templates/shared/skills/` — Global skills (executive-brief, development-lifecycle, etc.)
- `.claude/agents/` — Agent definitions loaded by Claude Code

## Ticket Status Codes

0=Done, 1=Blocked, 3=New, 4=In Progress, -1=Archived. **Never use 2.**

## Workflow

Tickets drive everything. Development agents follow 8 stages:
Pickup → Plan → Research → Implement (worktree) → Test → PR → CI → Awaiting Review

Ticket stays status=4 until PR is merged. Agent comments at each stage.

## Known Pitfalls

1. **Don't kill admin's tmux window** — admin is the running COO session
2. **SQLite single-writer** — daemon serializes; never write directly
3. **Rate limits** — Claude API shared across all sessions
4. **Ephemeral sessions** — all knowledge must be written to tickets/docs/skills
5. **setup-agents.py can overwrite templates/v2/*.md** — be aware after running restart
6. **Telegram outbound** — use POST /api/v1/human/send (not /human/messages which is inbound)

## Active Projects

- **Agent Harness** (this repo): Platform itself
- **Trading** (~/code/trading): Stock trading strategies, Alpaca Markets
- **Solo Platform** (planned): One-person company builder product

## Admin Self-Reminders

- **After EVERY conversation with Human**: Update STATUS.md + write/append daily log with discussion details (reasoning, not just conclusions)
- **Update this file** whenever project direction, architecture, or conventions change
- **Update STATUS.md** after every significant event (Human decision, phase change, new project)
- **Write daily log** before generating Executive Brief
- **Executive Brief at 7:00 AM daily** — read STATUS.md + log, pull live data, write with judgment, send via Telegram
- **Don't do everything yourself** — create tickets, let ephemeral agents execute, you orchestrate

## References

- Strategic direction: `templates/shared/skills/executive-brief/memory/STATUS.md`
- Daily logs: `templates/shared/skills/executive-brief/log/`
- Executive Brief format: `templates/shared/skills/executive-brief/SKILL.md`
- Design doc: `RETROSPECTIVE.md`
- Progress: `V2-PROGRESS.md`
