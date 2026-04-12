# Agent Platform Restructuring: Pub/Sub and Role Consolidation

> Status: Design approved, implementation planning
> Date: 2026-04-05
> Source: Architecture design document (photos IMG_0951-0959)

## 1. Problem Statement

### Before: Rigid Workflow Model
- Tickets assigned to one agent at a time, and only the assignee was notified
- Agents followed hardcoded workflow (e.g. Product → Dev → QA → Product), which broke down when a task required a different coordination pattern
- The only way to involve another agent was reassign_ticket, which was disconnected from ticket context
- Singleton services could conflict when multiple agents tried to use them simultaneously (e.g. git push)
- Agent roles were duplicated unnecessarily (3 QA agents, 3 Dev agents), with unclear scope

### After: Flexible Pub/Sub Model
- There is a ticket notification channel. Multiple agents subscribe to a ticket and all receive notifications when it's updated
- A Coordinator agent manages which agents are subscribed to which tickets, adding/removing agents as needed
- Singleton service locks prevent resource conflicts

## 2. Changes Overview

### 2.1 Database Schema Changes (on task DB)

```sql
-- New table: ticket_subscribers
-- Tracks which agents are subscribed to which tickets.
-- An agent being subscribed means they receive notifications for all updates on the ticket.
CREATE TABLE IF NOT EXISTS ticket_subscribers (
    ticket_id   INTEGER NOT NULL,
    agent_id    TEXT NOT NULL,
    PRIMARY KEY (ticket_id, agent_id),
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);
CREATE INDEX IF NOT EXISTS idx_ticket_subscribers
    ON ticket_subscribers(agent_id, ticket_id);

-- New table: notifications
-- Tracks which agents have pending notifications. All event types flow through one table.
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    ticket_id   INTEGER,
    type        TEXT NOT NULL,  -- 'ticket_assigned', 'ticket_comment', 'ticket_subscribed', 'message'
    source_agent_id  TEXT,
    title       TEXT,
    body        TEXT DEFAULT '',
    state       TEXT DEFAULT 'unread',  -- 'unread' | 'read'
    created_at  TEXT DEFAULT (datetime('now')),
    read_at     TEXT DEFAULT NULL,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);
CREATE INDEX IF NOT EXISTS idx_notifications_agent
    ON notifications(agent_id, state, created_at DESC);

-- New table: service_locks
-- Advisory locks for singleton services. All event types flow through one table.
CREATE TABLE IF NOT EXISTS service_locks (
    service_id  TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    acquired_at TEXT DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);
```

### 2.2 New MCP Tools

| Tool | Purpose | Trigger Point |
|------|---------|---------------|
| `subscribe_to_ticket(ticket_id, agent_id)` | Add an agent as a subscriber to a ticket | Coordinator assigns |
| `unsubscribe_from_ticket(ticket_id, agent_id)` | Remove a subscriber | Task complete |
| `get_subscribers(ticket_id)` | List all subscribers on a ticket | Info query |
| `get_notifications(agent_id, ticket_id, unread_only)` | Get unseen notifications (replaces get_inbox partially) | Agent wake-up |
| `mark_notifications_read(agent_id, notification_ids)` | Mark notifications as processed | After processing |
| `acquire_service_lock(service_id, agent_id, ttl_seconds)` | Acquire exclusive lock on a singleton service | Before git push |
| `release_service_lock(service_id, agent_id)` | Release a service lock | After operation |
| `list_service_locks()` | List currently held locks | Diagnostics |

### 2.3 Notification Triggers

Notifications are created automatically by the server when these events occur:

| Event | Notification Type | Recipients |
|-------|-------------------|------------|
| Ticket created and/or assigned | `ticket_assigned` | All subscribers + assignee |
| Ticket status changed | `status_change` | All subscribers (except the comment author) |
| Comment added to ticket | `ticket_comment` | All subscribers (except author) |
| Direct message sent | `message` | The newly subscribed agent |
| Subscriber added | `ticket_subscribed` | The key action: when a coordinator subscribes a dev agent to a task, the dev agent gets notified. |

### 2.4 Dispatcher Changes

The dispatch cycle priority is:
1. **Notifications** → `dispatch_agent_notifications(agent)` (tells agent to call `get_notifications()`)
2. **Pending tasks** → `dispatch_agent(agent)` (for assigned but unnotified tasks)
3. **Scheduled prompts** → as before (custom prompt from schedule DB)

Stale tasks and message checks are replaced by the notification system.
Service lock detection → if `expires_at` has passed, auto-release the lock.

### 2.5 Ticket Migration (Existing Data)

An idempotent migration function to backfill:

```python
async def migrate_to_pubsub(client, store, current_agents):
    """Run once on daemon startup when the restructuring is deployed."""
    for agent_id in current_agents:
        # For all assigned tickets, ensure the assignee is a subscriber
        tickets = client.list_tickets(assignee=agent_id, status="all")
        for ticket in tickets:
            if not client.is_subscriber(ticket["id"], agent_id):
                client.subscribe(ticket["id"], agent_id)
        # Always add 'coordinator' as subscriber, and then
        # add the ticket creator if known
    # Leave a migration comment on the first ticket: "message to coordinator"
```

This ensures a smooth transition when the restructuring is deployed.

### 2.6 Web UI Changes

The ticket detail page was updated to show **Subscribers** instead of the old Participants section:
- Added a field to show list of subscribers/agents subscribed
- New UI section for managing subscriber buttons
- API endpoint for managing subscriber list with subscribe UI

## 3. Agent Roster Consolidation

### Before (11+ agents with overlap)
Multiple dev agents per stream, clearly scoped

### After (11 agents, clearly scoped)

| Agent | Role | Scope | Purpose |
|-------|------|-------|---------|
| 协调员 | Coordinator | Daily/hourly coordination | Agent config, restarts, system management |
| 管理员 | Admin | Agent config, restarts, system management | Agent config, restarts |
| 巡检员 | Inspector | Cross-repo technical checks, anomaly detection | Health checking, CI monitoring |
| 架构师 | Architect (NEW) | Requirements verification, triage, design docs | Requirements verification, project tracking, design docs |
| 产品 | Product | All repos except Cortex | PR-based technical scope analysis, always |
| 开发(GS) | Dev (Cortex) | Cortex repo only | Cortex repo only |
| 开发(其他) | Dev (GS) | GlobalServices repo and Cortex | GlobalServices and Cortex |
| QA | QA | E2E / Integration testing | E2E / Integration testing |
| 代码审查 | Code Review | PR-based code review via gh CLI | Schoolhouse code review via gh CLI |
| 数据 | Data Scientist | Schoolhouse queries, data analysis | Schoolhouse queries, data analysis |

Key changes:
- Dev agents scoped by repository, not by project
- One QA, one DS → reduced from 3 each, concurrency won't be an issue (do at the same time)
- Architect is new: Requirements ownership → they receive design that wasn't tracked before
- Code Review is new: every dev creates PR → code review agent checks before merge, design review

## 4. Agent Profile Restructuring

### Profile Assembly

Each agent's system prompt (`PROFILE.md`) is assembled from multiple files by `setup-agents.py`:

| Layer | Source | Purpose |
|-------|--------|---------|
| PROFILE.md | `role_template` | Role-specific instructions (e.g. dev-al, qa-lucy, coordinator) |
| PROFILE.local.md | `templates/<agent>/PROFILE.local.md` | Instance-specific overrides (e.g. which repos dev-alex owns) |
| CONTEXT.local.md | `templates/shared/CONTEXT.local.md` | Common instructions shared by ALL agents |

### Profile Design Principles

1. **Concise** — Every byte costs tokens on every request. Remove verbose explanations; they waste context
2. **No hardcoded workflows** — Agents don't know "after I finish, send to QA." They subscribe/publish.
3. **Autonomy-first** — Agents decide autonomously based on context; explicit instruction leads to QA or debugging
4. **Auto-notify** — a CONTEXT.md → Notifications, profile maintenance, team info, journal updates, and ticket hygiene are automated
5. **Common instructions in CONTEXT.md** — Common instructions shared by ALL agents

### Sections Removed From Individual Templates

These were removed to centralize in `CONTEXT.md` to avoid duplication:

- Key Sections Removed:
  - `Coordinator` → `RequestRestart` reference
  - `currentContext` format and `StatusUpdates`

## 5. Coordinator Role Definition

The Coordinator is the linchpin of this pub/sub model. Its responsibilities:

### Triage Guidelines

When a new ticket arrives:
- **New feature / Implementation work** → Subscribe 相关开发 + Subscribe 架构师 first
- **Data analysis request** → Subscribe 数据科学 directly
- **Bug fix with known scope** → Subscribe the relevant dev agent directly
- **Documentation / config change** → Subscribe + assign, no triage overhead
- When a coordinator subscribes agents to a ticket → Subscribe, add them to this ticket

### Reactive Rules
- When a dev agent creates a PR → Add `code-review` agent as subscriber to the ticket
- When a coordinator decides the work is ready → Subscribe, add them to this ticket

### What Coordinator Does NOT Do
- Does not dictate workflows
- Does not create PRs (devs do their own)
- Does not do development work

## 6. Singleton Service Locking

| Problem | Solution |
|---------|----------|
| Some services only run one instance at a time (e.g. local Git, local Orchestration). Multiple agents trying to use them simultaneously causes conflicts. | SQLite advisory locking |

```sql
-- A lock is EXPIRED if EXISTS (SELECT 1 FROM service_locks WHERE service_id = ? AND expires_at < datetime('now'))
-- Before acquiring:
--   IF a lock EXISTS for service_id AND NOT EXPIRED → REJECT ("Held by <agent>", "try again in Xs")
--   ELSE → INSERT or REPLACE lock row
-- After: agent calls release_service_lock() or lock auto-expires
--
-- Stale Lock Detection:
-- A task is a STALE_LOCK if EXISTS (SELECT ... lock_age > 30 minutes).
-- The coordinator may auto-release STALE_LOCKs.
```

## 7. Implementation Checklist

### Backend

For replicating this restructuring in another project:

- [ ] Add `ticket_subscribers` table to task DB schema
- [ ] Add `notifications` table to task DB schema
- [ ] Add `service_locks` table to task DB schema
- [ ] Implement subscriber CRUD in store (`subscribe_to_ticket`, `unsubscribe_from_ticket`, `get_subscribers`)
- [ ] Implement notification service in store (`create_notification`, `get_notifications`, `mark_notifications_read`)
- [ ] Register notification triggers for all event types (`create_ticket`, `reassign_ticket`, `add_comment`, etc.)
- [ ] Add notification triggers on `create_ticket`, `reassign_ticket`, `add_comment`, `update_ticket` (status change)
- [ ] Update coordinator detection to `create_ticket` (assignee), on `add_comment` (new subscriber), on `status` change (incident)
- [ ] Add state-based selections to store (new subscribers have SUBSCRIBED, on state change, instead of get_inbox)
- [ ] Write idempotent migration function for existing tickets → backfill subscribers
- [ ] Add stale lock detection to daemon function after task state creation

### Web UI

- [ ] Add subscriber detail section to ticket detail view
- [ ] Update ticket detail page to show Subscribers section
- [ ] Add subscriber controls (add/remove subscriber buttons)

### Agent Profiles

- [ ] Create agent-specific PROFILE.md files for each role
- [ ] Create base shared CONTEXT.md with common rules
- [ ] Create PROFILE.local.md overrides for instance-specific configuration
- [ ] Ensure expertise tags, repo ownership, and notification preferences are stored

### Dispatcher

- [ ] Add notification count check to dispatch cycle (priority over task-based dispatch)
- [ ] Add service lock expiration check to dispatch loop

## 8. Key Design Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| Coordinator always subscribed to every ticket | Enables reactive agent addition without polling |
| Notifications are created server-side, not by agents | Agents don't need to know who else is subscribed; the server handles fan-out |
| Deps remain scoped by repository, not by project | Prevents resource conflicts; aligns with reality that repo-specific knowledge matters |
| Agents decide autonomously based on context; explicit rules are for varied task types | Works for both single-checkout repos (GS) and multiline repos (Cortex); explicit accounting semantics |
| No hard workflows in agent prompts (not branch-based) | Separates concerns; role behavior (template) vs instance config (PROFILE.local.md) vs shared rules (CONTEXT.md) |
| Service locking via MCP (not file-based) | Enables zero-downtime development; safe to run repeatedly |
| Profile assembly from multiple layers | Lightweight check every 30s; only notifies coordinator when action is needed; avoiding unnecessary LLM cost |
| Transparent migration on startup | Stale lock detection in dispatcher (no LLM) |
