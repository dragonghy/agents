---
name: deep-dive
description: Context auto-loading when Human enters a direct conversation session for hands-on collaboration.
---

# Deep Dive Mode

## When This Activates

When Human starts a direct conversation (tmux attach + typing), or when you are explicitly told "let's deep dive into X."

## Auto-Load Context

Before responding to Human's first message, proactively load:

1. **Recent tickets**: `list_tickets(status="3,4", limit=10)` — what's active right now
2. **Recent completions**: `list_tickets(status="0", limit=5)` — what just finished
3. **Project claude.md**: Read the current directory's `claude.md` for project context
4. **Recent git activity**: Run `git log --oneline -10` to see recent commits
5. **Blocked items**: `list_tickets(status="1", limit=5)` — what's waiting

Present a brief status summary to Human before asking what they want to focus on.

## During Deep Dive

- **Capture everything**: Human's decisions, design choices, and instructions MUST be written to ticket comments or docs before the session ends.
- **Never rely on session memory**: If Human makes a decision, write it down immediately — don't wait until the end.
- **Propose, don't wait**: If you see related issues while working on Human's topic, mention them proactively.

## On Exit

Before the session ends:
1. Summarize what was decided and changed
2. Update relevant ticket comments with Human's decisions
3. Update claude.md if any conventions or architecture changed
4. Create follow-up tickets for any unfinished items discussed
