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

### Auto-close on PR merge

The daemon runs a `pr_monitor` background loop (see `services/agents-mcp/src/agents_mcp/pr_monitor.py`, ticket #487). Every 10 minutes it polls `gh pr list --state merged` for configured repos (`pr_monitor.repos` in `agents.yaml`) and:

- Parses `#NNN` refs from merged PR title + body (excludes the PR's own number).
- For each referenced ticket: if status != 0 and no open children → transitions to status=0 with an auto-close comment.
- If the ticket has open children, posts a "flagged" comment instead (admin must decide).
- State lives in `.agents-pr-monitor.json` at the repo root; first-boot seeds all existing merged PRs as "already reconciled" so we never retroactively close old tickets.

So when you merge a PR that says "Closes #487", you do NOT need to manually close ticket #487 — the monitor will do it within 10 minutes.

## Known Pitfalls

1. **Don't kill admin's tmux window** — admin is the running COO session
2. **SQLite single-writer** — daemon serializes; never write directly
3. **Rate limits** — Claude API shared across all sessions
4. **Ephemeral sessions** — all knowledge must be written to tickets/docs/skills
5. **setup-agents.py can overwrite templates/v2/*.md** — be aware after running restart
6. **Telegram outbound** — use POST /api/v1/human/send (not /human/messages which is inbound)
7. **`crontab` on macOS hangs on Full Disk Access** — if modifying the user crontab from a shell that doesn't have TCC permission, `crontab <file>` blocks forever waiting on a system dialog that never comes. Use `~/Library/LaunchAgents/*.plist` + `launchctl load` instead; launchd has no such restriction.
8. **Silent-failure bugs in scheduled scrapers** — if a scraper returns `[]` when the target dataset is missing, the filter downstream reports "nothing open" and Human never learns the job broke. Always distinguish "loaded the target, nothing matched" from "never loaded the target" and make the latter raise loudly (see `projects/pickleball/daily_check.py` `TargetNotReached`).
9. **Don't modify the main repo directly when deploying launchd/cron changes from a worktree** — it's tempting to copy the worktree's install script to the main repo to reload a schedule immediately, but this leaves the main-repo working tree dirty and bypasses PR review. The plist file lives in `~/Library/LaunchAgents/` (outside the repo) and survives after you revert main. If you need to hot-load a schedule change, either (a) run the install script from the worktree path and revert main cleanly, or (b) wait for PR merge and reinstall from freshly-pulled main.
10. **tsx main()-on-import gotcha** — scripts written as `main().catch(...)` at the bottom auto-execute when imported by a test file. Guard with `const isEntryPoint = path.resolve(process.argv[1]) === new URL(import.meta.url).pathname` (handle `.ts` vs `.js` extension under tsx) and wrap the main call. Otherwise tests will trigger real API calls.
11. **Admin has its own launchd supervisor** — `admin-supervisor.sh` (loaded via `com.agents.admin.supervisor.plist`) checks the `agents:admin` tmux window every 60s and auto-restarts it via `./restart_all_agents.sh admin --force` if stalled > 4h AND there is pending work (unread inbox or unsent morning brief). If admin ever "mysteriously reappears" after a long silence, check `.admin-supervisor.log` and `.daemon.log` for `ADMIN-SUPERVISOR:` lines — that's not a glitch, that's recovery. The supervisor is intentionally out-of-process so it survives daemon death. Daemon death itself is handled by `daemon-watchdog.sh` (its own separate launchd job).
12. **`gh pr merge --squash` does not auto-update local main** — after a self-merge via `gh`, you MUST `git fetch && git pull --rebase` on your local main, otherwise launchd jobs and anything reading files from the working tree will run the OLD pre-merge code. Symptom: PR shows "merged" on GitHub, `gh pr view` confirms `mergedAt`, but running the affected script reproduces the original bug. Fix: always follow `gh pr merge` with `git pull --rebase origin main`. Discovered when the 4/23 Pickleball click-fix "merged" but the 12:00 noon launchd run used the old code and failed the same way. See the 2026-04-24 log entry.

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
