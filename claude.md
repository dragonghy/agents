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

Currently registered (as of 2026-04-26):
- **admin** — COO / global config / restarts (this session)
- **ops** — infra, domains, servers, cloud
- **dev-alex** — development lifecycle (plan → PR → CI)
- **qa-lucy** — E2E + requirement verification
- **assistant-aria** — Personal workspace assistant (Gmail / Calendar / Drive / iMessage). Handles **only `workspace_id=2`** tickets (soft-isolation via prompt; see `templates/v2/assistant.md` "Workspace Scope" section). Personal MCPs (`google_personal`, `imessage_personal`) are scoped via `agents.assistant-aria.extra_mcp_servers` so work agents never auto-load them (pitfall #13 prevention).

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

> Numbering preserved for cross-reference. Some entries (#5, #11) are retired but kept as history; they reference v1 infrastructure that was removed in the 2026-05-03 cleanup.

1. ~~**Don't kill admin's tmux window**~~ **(retired 2026-05-03)** — admin no longer runs in a managed tmux window. Forks of admin are independent claude processes with their own session_ids; killing tmux has no effect on them. The daemon still runs in tmux for convenience but can be moved out (`nohup`).
2. **SQLite single-writer** — daemon serializes; never write directly
3. **Rate limits** — Claude API shared across all sessions
4. **Ephemeral sessions** — all knowledge must be written to tickets/docs/skills
5. ~~**setup-agents.py can overwrite templates/v2/*.md**~~ **(retired 2026-05-03)** — `templates/v2/` and `setup-agents.py` were both deleted in the v1 infrastructure cleanup. New model: Profiles live at `profiles/<name>/profile.md` and are loaded by `agents_mcp.profile_loader.ProfileLoader.scan()` on daemon boot.
6. **Telegram outbound** — historically `POST /api/v1/human/send`. Phase 4 (Telegram channel adapter) reroutes outbound through SSE + secretary profile session — once that lands, this entry updates again. Until then: legacy bridge route still works.
7. **`crontab` on macOS hangs on Full Disk Access** — if modifying the user crontab from a shell that doesn't have TCC permission, `crontab <file>` blocks forever waiting on a system dialog that never comes. Use `~/Library/LaunchAgents/*.plist` + `launchctl load` instead; launchd has no such restriction.
8. **Silent-failure bugs in scheduled scrapers** — if a scraper returns `[]` when the target dataset is missing, the filter downstream reports "nothing open" and Human never learns the job broke. Always distinguish "loaded the target, nothing matched" from "never loaded the target" and make the latter raise loudly (see `projects/pickleball/daily_check.py` `TargetNotReached`).
9. **Don't modify the main repo directly when deploying launchd/cron changes from a worktree** — it's tempting to copy the worktree's install script to the main repo to reload a schedule immediately, but this leaves the main-repo working tree dirty and bypasses PR review. The plist file lives in `~/Library/LaunchAgents/` (outside the repo) and survives after you revert main. If you need to hot-load a schedule change, either (a) run the install script from the worktree path and revert main cleanly, or (b) wait for PR merge and reinstall from freshly-pulled main.
10. **tsx main()-on-import gotcha** — scripts written as `main().catch(...)` at the bottom auto-execute when imported by a test file. Guard with `const isEntryPoint = path.resolve(process.argv[1]) === new URL(import.meta.url).pathname` (handle `.ts` vs `.js` extension under tsx) and wrap the main call. Otherwise tests will trigger real API calls.
11. ~~**Admin has its own launchd supervisor**~~ **(retired 2026-05-03)** — both `admin-supervisor.sh` and `daemon-watchdog.sh` (with their `com.agents.*.plist` files) were uninstalled and the scripts deleted as part of the v1 infrastructure cleanup. They were artifacts of the v2 ephemeral-agent + named-tmux-window model, which has no parallel in the new orchestration model (Profile + Session + TPM). The new model runs sessions inside the daemon process (no per-agent tmux windows), so there's nothing for those watchdogs to babysit. **For dev**: if the daemon dies, restart manually via `pkill -f 'agents-mcp.*--daemon' && nohup uv run --directory services/agents-mcp agents-mcp --daemon --host 127.0.0.1 --port 8765 >> .daemon.log 2>&1 &`. Don't use `./restart_all_agents.sh` without `--daemon` — it has historical paths that re-spawn dead v1 agent windows.
12. **`gh pr merge --squash` does not auto-update local main** — after a self-merge via `gh`, you MUST `git fetch && git pull --rebase` on your local main, otherwise launchd jobs and anything reading files from the working tree will run the OLD pre-merge code. Symptom: PR shows "merged" on GitHub, `gh pr view` confirms `mergedAt`, but running the affected script reproduces the original bug. Fix: always follow `gh pr merge` with `git pull --rebase origin main`. Discovered when the 4/23 Pickleball click-fix "merged" but the 12:00 noon launchd run used the old code and failed the same way. See the 2026-04-24 log entry.
13. **MCP servers under top-level `mcp_servers:` auto-load to ALL v1 agents** — `setup-agents.py:63` reads `cfg.get("mcp_servers", {})` and merges every entry into each v1 agent's `.mcp.json`. There is **no per-server scoping** at the top level. So putting a sensitive MCP (personal credentials, single-tenant tools) under `mcp_servers:` leaks it to admin / ops / dev-alex / qa-lucy — even if you only intended it for one agent. v2 `agent_types.<type>.mcp_servers: [list]` *does* scope, but v1 ignores that list. **For per-agent isolation, define the MCP under `agents.<name>.extra_mcp_servers:` instead** — those are merged in only for that one agent. Discovered while planning #494 (Google Personal MCP). The existing `microsoft` entry has the same leakage today (pre-existing). See `projects/agent-hub/skills/google-personal-mcp/SKILL.md` for the recommended per-agent isolation pattern.
14. **"DOM `.click()` returned" ≠ "modal opened"** — when scripting a Kendo scheduler (or any custom widget) you can dispatch a click on `.k-event[data-uid]` and have it succeed silently while the actual handler is bound to a child anchor (e.g. CourtReserve's "Reserve" link in agenda view). PR #13's strategyA reported `success: true` for the entire 4/24 cron, but the booking modal never appeared. **Always gate "click succeeded" on a post-condition you actually care about** (e.g. modal visible, network call fired). Iterate strategies and verify, don't trust the first one to dispatch. See `projects/pickleball/daily_check.py` `_CLICK_STRATEGIES` for the pattern.
15. **iMessage / chat.db needs FDA on the host process, not on Claude Code** — `~/Library/Messages/chat.db` is gated by macOS Full Disk Access. The grant has to go to whatever process spawns the MCP server: Terminal.app or iTerm2.app for tmux-based agents, Claude Desktop for desktop-launched agents. Granting FDA to "Claude Code" itself does nothing — Claude Code is just a CLI inside the terminal. After granting FDA, you MUST quit and reopen the terminal app — TCC permissions are read at process spawn. Self-check: `uv run --directory services/imessage-mcp python -m imessage_mcp --check` prints OK or the exact missing-permission error. The MCP itself opens chat.db with `mode=ro` so it can never mutate it.
16. **iMessage `attributedBody` is best-effort, not lossless** — iOS 14+ stores rich-text message bodies in `message.attributedBody` (NSKeyedArchiver blob) and leaves `message.text` NULL. We extract plaintext with an in-process byte-scan, but ~1-2% of edge cases (custom attributes only, URL-only previews) yield no readable substring. Those rows surface as `text="(unable to decode message body)"` with `decode_failed: true`. Don't treat that as a parser bug — it's expected. The plutil-based fallback (`decode_attributed_body_via_plutil`) is available for one-off diagnostics.

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
