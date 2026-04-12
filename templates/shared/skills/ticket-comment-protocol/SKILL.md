---
name: ticket-comment-protocol
description: How to write structured ticket comments that serve as episodic memory for agent context recovery.
---

# Ticket Comment Protocol

## Purpose

Ticket comments are **episodic memory**. When an agent picks up a ticket, the description and comments are the only record of what has happened. Well-structured comments allow any future agent -- or the same agent after a restart -- to recover full context and continue work without guessing.

## On Pickup: Read Everything First

Before starting any work on a ticket:

1. Read the ticket description completely.
2. Read ALL comments from oldest to newest.
3. Look for: human feedback, QA rejection reasons, prior decisions, blockers, and partial progress.
4. Only then begin work.

Skipping comments is the #1 cause of agents repeating failed approaches or ignoring human instructions.

## During Work: Comment at Milestones

Add a structured comment whenever you reach a meaningful milestone. Use these formats:

### Branch or PR Created

```
## Branch Created
Branch: `feature/xyz`
PR: #123 (if applicable)
Base: main
```

### Key Decision Made

```
## Decision
**Choice**: Using approach A (Redis pub/sub) over approach B (polling)
**Reason**: Lower latency, existing Redis dependency, simpler error handling
**Trade-off**: Adds Redis as a hard runtime dependency
```

### Error Encountered and Fixed

```
## Issue Resolved
**Problem**: Server crashes on startup with "address already in use"
**Root cause**: Previous instance not cleaned up, PID file stale
**Fix**: Added graceful shutdown handler + stale PID detection
**Files changed**: server.py, utils/process.py
```

### Human Feedback Received

```
## Human Input
**Summary**: Human prefers the modal approach over inline editing
**Impact**: Reverting inline-edit component, building modal instead
**Source**: Comment on ticket / direct message / verbal
```

### Progress Update

```
## Progress
**Completed**: API endpoints for user CRUD, input validation
**Next**: Frontend integration, error handling for edge cases
**Blockers**: None currently
```

### Blocked / Waiting

```
## Blocked
**Waiting on**: ops to provision the staging database
**Ticket**: #456
**Impact**: Cannot run integration tests until resolved
```

## On Completion: Final Summary

When finishing a ticket, add a completion comment before handoff:

```
## Development Complete

### What was done
- Implemented user authentication with JWT tokens
- Added rate limiting middleware (100 req/min per user)
- Created migration script for new `sessions` table

### Files changed
- src/auth/jwt.py (new)
- src/middleware/rate_limit.py (new)
- src/models/session.py (new)
- src/routes/auth.py (modified)
- tests/test_auth.py (new)

### How to test
1. Start server with `python -m src.server`
2. POST /auth/login with valid credentials -> should return JWT
3. Use JWT in Authorization header for subsequent requests
4. Send 101 requests in 1 minute -> should get 429

### Follow-ups
- [ ] Add refresh token support (out of scope for this ticket)
- [ ] Monitor rate limit thresholds in production

### Commit
abc1234
```

## After Completion: Knowledge Evaluation

After closing a ticket, ask yourself:

1. **Did I learn something that applies to all future tasks?** -> Update claude.md (if important enough) or add to docs/.
2. **Did I develop a repeatable procedure?** -> Create or update a skill.
3. **Did I hit a pitfall others will hit?** -> Add to claude.md's "Known Pitfalls" section.
4. **Is this a one-off fix with no broader lesson?** -> The ticket comments are sufficient. No further action needed.

## Anti-Patterns

- **No comments at all** -- The next agent starts from zero. Unacceptable.
- **"Done" as the only completion comment** -- Says nothing about what was done or how to verify.
- **Commenting every 5 minutes** -- Comment at milestones, not at every line of code. Noise buries signal.
- **Unstructured walls of text** -- Use the formats above. Scannable structure saves time.
- **Pasting full stack traces** -- Summarize the error. Include the trace only if the exact text matters for reproduction.
