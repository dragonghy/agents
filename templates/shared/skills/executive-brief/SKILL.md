---
name: executive-brief
description: How to write the daily Executive Brief for Human (Chairman). Designed for a time-constrained executive who needs to give high-leverage feedback in 2 minutes.
---

# Executive Brief

## Purpose

Human is the Chairman. You are the COO. This brief is your daily board report — it must enable Human to:
1. Recover context in 10 seconds (what are we building, where are we)
2. Make 0-3 critical decisions in 60 seconds
3. Skim engineering updates in 30 seconds
4. Take no action if everything is on track

## Format

### Header: Context Reset (ALWAYS include)

Every brief starts with a 2-sentence context reset. Assume Human hasn't thought about this project since yesterday.

```
We're building [project description]. Currently in [phase]: [what's happening this week].
```

Example: "We're building Agent Harness — a self-running multi-agent dev platform. Currently in v2 cleanup phase: removing v1 artifacts and stabilizing the ephemeral agent system."

### Section 1: Decisions Needed (CEO-level)

Only items that REQUIRE Human's judgment. Not FYI, not rubber-stamps.

Each decision:
- **One-line summary** of what needs deciding
- **Context**: Why this matters (2 sentences max)
- **Recommendation**: Your suggested choice
- **Options**: [A] [B] [Other] — each as a tappable action
- **Link**: If there's a doc/PR/design to review → clickable URL

If no decisions needed: "No decisions needed today. ✅"

### Section 2: FYI — Auto-proceeding Unless You Object

Items that are proceeding on your (COO) judgment. Human can override but doesn't need to.

Format: bullet list with links.
```
- Merging PR: [title](https://github.com/...) — [1-sentence why]
- Archiving 5 stale tickets from wedding-website project
- Deploying config change to daemon
```

If Human says nothing, these proceed. If Human objects, they reply inline.

### Section 3: Engineering Update (CTO-level)

For when Human wants to go deeper. Brief, linkable.

- **Architecture changes**: Any structural decisions made or proposed
- **Open PRs**: Link + 1-line summary + status (ready/needs-work/blocked)
- **Test results**: Pass/fail summary, link to details
- **Technical debt**: Anything accumulating that needs attention

### Section 4: Project Health

Per-project snapshot (only active projects):
```
**Agent Harness**: 12 tickets open, 3 in progress, velocity 2/day
  Phase: v2 cleanup → next: re-enable Wedding Website project
```

Stale/orphan tickets: call out explicitly.
```
⚠️ 3 tickets stale (>7 days no activity): #xxx, #yyy, #zzz — recommend archive
```

### Footer

```
Reply with decisions or instructions. Links are tappable.
Next brief: tomorrow 7:00 AM
```

## Anti-Patterns

- **Ticket dump**: Listing every ticket is useless. Summarize by project.
- **No context reset**: Human opens Telegram cold. They don't remember yesterday.
- **No links**: "PR #5 looks good" is not actionable. "PR #5: [title](url)" is.
- **Too long**: If the brief is >30 lines, you're including too much detail. Move it to a linked doc.
- **No recommendation**: "Should we do A or B?" is lazy. "Recommend A because X. [A] [B]" is helpful.
- **FYI as decision**: Don't make Human decide things you can decide yourself.

## Generating the Brief

The brief is generated daily by the Morning Brief system (morning_brief.py).
It can also be triggered on-demand via `/brief` in Telegram or the MCP tool.

The generation code should query:
1. Ticket system for project health and stale items
2. GitHub for open PRs and their status
3. Human conversation history for pending decisions
4. Token usage for cost summary (only if notable)

## Links

All references should be clickable URLs:
- PRs: `https://github.com/dragonghy/agents/pull/{number}`
- Tickets: Include ticket # and headline (no link needed, Human uses Telegram)
- Docs: If a document exists in the repo, link to GitHub blob view
- External: Full URL

## Working Memory

The Executive Brief is NOT a stateless report. It requires continuity across sessions.

### File Structure

```
templates/shared/skills/executive-brief/
├── SKILL.md          ← This file (format + process)
├── memory/
│   └── STATUS.md     ← Current project state, phase, open questions, key metrics
└── log/
    ├── 2026-04-13.md ← Daily log entries
    ├── 2026-04-14.md
    └── ...
```

### STATUS.md (Current State)

Read this FIRST before writing any brief. It contains:
- What project we're building and current phase
- What's next
- Open questions for Human
- Key metrics
- Last Human decisions

Update STATUS.md after every significant event (phase change, Human decision, architecture shift).

### Daily Log (log/YYYY-MM-DD.md)

Write a log entry at the end of each day (or when generating the brief). Contains:
- Summary of the day
- Key events with timestamps
- PRs merged / tickets completed
- Bugs found and fixed
- Human feedback received
- Tomorrow's priorities

Use log entries to look back when writing the brief — "what changed since last brief?"

### Brief Generation Process

1. Read `memory/STATUS.md` for current context
2. Read recent `log/` entries for what happened
3. Pull live data: tickets, PRs, sessions, health
4. **Think**: What matters? What needs Human's attention? What can I handle?
5. Write the brief using the format above
6. Send via Telegram
7. Update STATUS.md if anything changed

## Delivery

Primary: Telegram (@agents_daemon_bot)
Secondary: Email (huayang.guo@outlook.com)
Schedule: Daily 7:00 AM local time
