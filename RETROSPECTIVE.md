# Agent Harness — Retrospective, Redesign & Product Requirements

> Author: Human + Claude
> Date: 2026-04-12
> Status: Living document

---

## Part 1: Retrospective

### What We Built

From scratch, in roughly 4 weeks, we built a fully operational multi-agent platform:

- **18 agents** running autonomously in tmux sessions
- **SQLite-backed task system** with Pub/Sub notifications, service locks, dependency management
- **Auto-dispatch loop** (30s cycle) with priority: notifications > messages > stale tasks > new tasks > schedules
- **P2P messaging**, agent profiles, expertise-based routing
- **Web dashboard** (Display UI) for monitoring
- **VM MCP** (49 tools) — agents can control a full desktop VM
- **Cloud SaaS design** — 7 milestones code-complete (Docker isolation, billing, domain routing)
- **Multiple product prototypes**: SEOPilot (Shopify app + Chrome extension), DevToolBox, Wedding Website, Pomodoro Timer

### What Went Well

1. **Core platform velocity**: The agent harness evolved fast — from basic tmux dispatch to Pub/Sub with notifications in weeks.
2. **Agent autonomy**: Agents genuinely self-organize. Dev writes code, creates PR, reassigns to QA. QA tests, files bugs or approves. Product plans and creates tickets.
3. **Dogfooding**: We use the system to build the system. Every bug found is a real bug because agents hit it while doing real work.
4. **Infrastructure tooling**: Daemon watchdog, auto-restart, rate limit detection, idle detection — these keep the system running without Human intervention.

### What Went Wrong

1. **Project sprawl**: 13 projects across 4 work streams. Human cannot context-switch across all of them. Tickets sit for days, deployments stall, agents block on Human approvals.
2. **Human as bottleneck**: Too many things require Human action — sudo commands, Shopify uploads, Vercel env vars, Chrome Web Store submissions, AWS procurement. The system generates work faster than Human can process it.
3. **Agent quantity over quality**: 18 agents is too many to monitor. Multiple agents compete for the same work. The multiplicity was meant to preserve context, but didn't actually solve the memory problem.
4. **Lack of focus**: Energy split across too many projects. None reached production. Code-complete ≠ shipped.
5. **No daily digest**: Human has no single place to see "what happened today, what needs my attention."
6. **Memory is broken**: Agent context is lost on session restart. Multiple instances of the same role (dev-alex, dev-emma) was a workaround for context preservation, but it didn't work — summarization still drops critical information, and Human fixes get forgotten.

### Key Insight

The original design assumed that **agent identity and persistent sessions** would preserve context. This was wrong. Memory must be **externalized into the system** — into tickets, project docs, and skills — not held in agent session context. This single insight drives the entire redesign.

---

## Part 2: System Design Principles

### 2.1 Core Architecture Shift

The system moves from **agent-centric** to **task-centric** orchestration:

| Dimension | v1 (Current) | v2 (Redesign) |
|-----------|--------------|----------------|
| Scheduling unit | Agent (poll each agent for work) | Task (find work, spawn agent for it) |
| Agent lifecycle | Persistent (always-on tmux sessions) | Ephemeral (start per task, stop when done) |
| Agent state | Stateful (relies on session context) | Stateless (all state externalized) |
| Memory | In agent's context window | In ticket comments, project docs, skills |
| Role assignment | Static (dev-alex is always dev on project X) | Dynamic (any dev-type agent can pick up any dev task) |
| Agent count | 18 fixed instances | 2-5 concurrent sessions, spawned on demand |

### 2.2 Foundational Principles

1. **Agent is a template, not an entity.** An agent type = system prompt (thinking mode + workflow) + tool set + permission config. No persistent identity needed.

2. **Task is the core scheduling unit.** The system dispatches tasks, not agents. When a task needs processing, the system instantiates an agent session from the appropriate template.

3. **Memory is externalized.** Task-level memory lives in ticket comments. Project-level memory lives in claude.md and skills. Global memory lives in the agent repo's shared skills. Agent sessions are disposable.

4. **Roles are thinking modes, not permanent assignments.** Product, dev, QA represent different cognitive approaches. A single task may pass through multiple thinking modes (plan → implement → test) without requiring separate agents.

5. **Human intervenes only at trust boundaries.** Spending money, publishing externally, irreversible operations. Everything else is autonomous.

---

## Part 3: Human Role & Interaction Model

### 3.1 Human's Four Roles

Human interacts with the system in four distinct capacities:

**Decision-maker** — Sets direction, priorities, and makes judgment calls at key milestones. This is irreplaceable.

**Resource provider** — Supplies credentials, physical-world resources (mailing addresses, etc.), and funding. This should be minimized through automation but cannot be fully eliminated.

**Observer** — Understands system state, project progress, costs, and timeline. Should be effortless and proactive (system pushes info to Human, not Human pulling).

**Direct participant** — Occasionally dives deep into a specific problem, collaborates with agents via direct conversation (tmux attach + Claude Code), inspects work, and provides hands-on guidance.

### 3.2 Daily Routine: The Morning Brief Protocol

The primary Human interaction is an **asynchronous message protocol** designed for minimal friction — completable in 5 minutes, even via voice input while commuting.

#### Morning Brief (Agent → Human, daily at 7:00 AM)

Delivered via email or messaging. Contains three sections:

**Section 1: Status Snapshot**
Two to three sentences summarizing overall progress. Example: "Wedding-website completed 3 tickets this week, 8 remaining. At current velocity, deliverable by May 15. Agent-hub had 2 blocked tickets resolved yesterday."

**Section 2: Decisions Needed**
Actionable, structured choices — not open-ended questions. Each decision item includes context, a recommendation, and options.

Example format:
```
Decision: Homepage layout for wedding-website
Context: Two design approaches evaluated. A = single-page scroll, B = multi-page nav.
Recommendation: A (saves 2 days of dev time, better mobile experience)
→ Choose: [A] [B] [Other — reply with details]
```

**Section 3: Resources Needed**
Explicit list of blocked items requiring Human action. Each item states what is needed and why.

Example: "Blocked: Need Stripe API key to implement payment module for wedding-website. Agent cannot proceed with checkout flow without this."

#### Human Response (Human → Agent)

Can be any format — voice-to-text, short typed message, or structured choices. The receiving agent must be capable of parsing natural language into actionable directives.

Example input: "A 方案吧，Stripe 的事下周再说，先做不需要支付的部分。"

Expected agent interpretation: Decision 1 → choose A; Stripe resource request → deferred; Implicit priority → restructure task dependencies to unblock non-payment work first.

#### Execution Confirmation (Agent → Human, optional)

For significant decisions only: "已按方案 A 开始开发首页，预计 3 天完成。支付模块移到下周，已调整 ticket 依赖。"

### 3.3 Deep Dive Mode

When Human needs to go deeper (weekly or ad-hoc):

- **Entry point**: tmux attach to an active agent session, or start a new session targeting a specific project/task.
- **Capabilities**: Review code, inspect agent's recent work, provide direct instructions, co-debug issues, inject code or design decisions.
- **Context**: Agent should auto-load relevant ticket history, recent commits, and project docs when Human enters a deep dive session.
- **Exit**: Human's inputs and decisions are captured in ticket comments or project docs, so nothing is lost when the session ends.

### 3.4 What Human Should Never Need to Do

- Manually dispatch or monitor individual agents
- Context-switch between multiple projects in a single session
- Make granular technical decisions that agents can handle
- Provide sudo access or system-level permissions (solved by infrastructure design)
- Manually update project documentation (agents maintain this)

---

## Part 4: Agent Definition & Architecture

### 4.1 What Is an Agent?

An agent is defined by three components:

**Thinking Mode (System Prompt)**
The cognitive approach and workflow — how this agent thinks about problems, what it prioritizes, and what process it follows. This is kept concise (under 200 lines) and loaded into the system prompt / claude.md. Examples: product thinking (user needs, ROI, prioritization), engineering thinking (feasibility, code quality, maintainability), QA thinking (edge cases, regression, user experience).

**Tool Set (MCP + Permissions)**
What the agent can access and operate. This includes MCP servers (agents-mcp daemon, 1Password, VM MCP), platform APIs (git, Vercel, deployment pipelines), and external services. Different agent types have different tool access — an ops agent can access 1Password vaults that a dev agent cannot.

**Skills (On-Demand Knowledge)**
Detailed procedural knowledge loaded when needed, not permanently in context. Examples: "how to write and maintain claude.md", "how to deploy to Vercel", "how to run QA on this project's test suite." Skills live as files in the agent repo (global) or project repo (project-specific).

### 4.2 Agent Types

Three agent types replace the previous 18 instances:

#### Development Agent

Covers the full product development lifecycle: planning, design, implementation, testing, and delivery. During different task phases, loads different thinking modes:

- **Planning phase**: Product thinking — analyze requirements, define scope, create tickets
- **Implementation phase**: Engineering thinking — write code, create PRs, handle technical decisions
- **Testing phase**: QA thinking — write and run tests, verify edge cases, validate acceptance criteria
- **Delivery phase**: Ops thinking — deploy, verify production, monitor for issues

The phase transition is driven by the task's workflow definition, not by reassigning to a different agent. One agent, multiple hats.

#### Operations Agent

Handles platform health, infrastructure, and system administration. Replaces the previous admin, ops, and inspector agents. Responsibilities:

- System health monitoring (previously inspector's scheduled checks)
- Agent session management (start, stop, restart)
- Infrastructure operations (Docker, deployment pipelines, networking)
- Configuration management (agents.yaml, environment, credentials)
- Periodic maintenance (log rotation, database cleanup, stale ticket detection)

Inspector functionality becomes a scheduled task for the ops agent — same system prompt, with an additional task-specific instruction: "check system health and report anomalies."

#### Assistant Agent

Handles personal and lifestyle tasks that are fundamentally different from development work. Responsibilities:

- Travel research and booking
- Event registration (sports, tickets, etc.)
- Personal errands requiring web interaction
- Research tasks unrelated to software development

This agent type has a different tool set (heavier Chrome/browser usage, email, calendar) and a different thinking mode (service-oriented, time-sensitive, real-world interaction).

### 4.3 Agent Lifecycle: Stateless & Task-Driven

Agents do not run persistently. The lifecycle is:

```
1. Task needs processing (new ticket, Human request, scheduled check)
2. Dispatcher selects appropriate agent type based on task requirements
3. System spawns agent session with:
   - Agent type's system prompt (from agent repo)
   - Global skills (from agent repo)
   - Project claude.md (from project repo)
   - Project skills (from project repo)
   - Task context (ticket description + comments + history)
4. Agent works on the task
5. Agent writes results back:
   - Code changes → git commits / PRs
   - Decisions & progress → ticket comments
   - Project knowledge → project claude.md or docs/
   - Reusable procedures → skills
6. Session ends (or suspends if awaiting input)
```

**Session persistence model**: While actively working on a task, the session stays alive for continuity (follow-up questions, iterative work). When idle beyond a threshold, the session is released. Next time the task needs attention, a fresh session is spawned and context is recovered from ticket history + project docs.

### 4.4 Agent Identity Layer

To reduce Human-as-bottleneck, agents need real-world identity:

**Email**: Each agent type gets an email address under the team's domain (e.g., dev@agents.example.com). Enables autonomous service registration, receiving verification codes, and external communication.

**Credentials**: Managed via 1Password. Agents access credentials through MCP integration. Different agent types have access to different vaults based on their permission level.

**Payment**: Virtual cards (via Stripe Issuing or similar) with per-project budget caps and per-transaction limits. Human sets budgets; agents spend autonomously within limits. Transactions above a threshold require Human approval via the Morning Brief protocol.

**Physical resources**: Pre-configured in an agent profile (mailing address, phone number for 2FA). Provided by Human once, reused by agents as needed.

**Design principle**: Human intervenes only at trust boundaries — setting up initial access and budgets. Day-to-day operations are fully autonomous.

---

## Part 5: Project-Level Organization

### 5.1 What Is a Project?

A project is an independent organizational unit that defines:

- **Goal and scope** — What this project aims to achieve and its boundaries
- **Deadline** — Hard or soft target date (if applicable)
- **Workflow** — The lifecycle stages a task goes through in this project
- **Resource budget** — Token budget, time allocation, spending limits
- **Context** — The knowledge base that any agent needs to work on this project

### 5.2 Project Context: The Three-Layer Memory System

Every project maintains a layered knowledge structure. This is the core memory architecture of the entire system.

#### Layer 1: claude.md (Always Loaded — Max 200-300 Lines)

This is the project's "working memory." It is loaded into every agent session that touches this project. Because it occupies system prompt space, it must be strictly size-capped.

Contents:
- Project purpose (2-3 sentences)
- Tech stack and key dependencies
- Core architecture (brief description, not full design docs)
- Key conventions (naming, branching strategy, deployment process)
- Critical constraints and known pitfalls (the top 5-10 things every developer must know)
- **Pointers to detailed docs and skills** ("Payment architecture: see docs/payment-architecture.md", "Deploy process: use skill deploy-to-vercel")

What does NOT belong in claude.md:
- Detailed API specifications (→ move to docs/)
- Step-by-step operational procedures (→ move to skills/)
- Historical decision logs (→ move to docs/decisions/)
- Full architectural diagrams (→ move to docs/)

#### Layer 2: docs/ and skills/ (Loaded On-Demand)

This is the project's "long-term memory." Agents read these files when they need detailed information for a specific task.

**docs/** — Reference documentation: architecture decisions, API designs, meeting notes, research findings. Organized by topic. Agents read relevant docs when starting a task that touches that area.

**skills/** — Procedural knowledge: how to deploy, how to run tests, how to set up the development environment, how to interact with specific APIs. Agents load relevant skills when executing specific operations.

#### Layer 3: Ticket History (Task-Specific Context)

This is "episodic memory" — the detailed record of what happened on a specific task. Stored as ticket descriptions, comments, and status transitions in the task system.

When an agent picks up a task, it reads the ticket's full history to recover context: which branch, which PR, what was tried, what failed, what decisions were made, and what Human feedback was given.

### 5.3 Memory Maintenance: Who Updates What

Agents are responsible for maintaining project memory as part of their workflow. This is not optional — it is a core delivery requirement.

**After completing a task**, the agent evaluates whether the task produced knowledge that should be persisted:

- New architectural decisions → update claude.md (if critical) or add to docs/decisions/
- New operational procedures discovered → create or update a skill
- Bug workarounds or pitfalls → add to claude.md's "known pitfalls" section or docs/
- API changes or dependency updates → update relevant docs

**claude.md maintenance skill**: A global skill that teaches agents how to maintain claude.md properly. Rules include: keep under 300 lines; when adding new content, evaluate if something can be moved to docs/; maintain the pointer structure (brief description + link to detailed doc); remove outdated information; never let it grow unbounded.

**Periodic review**: The ops agent runs a scheduled task to audit project claude.md files — checking size limits, structural compliance, and freshness.

### 5.4 Skill Organization: Global vs. Project

Skills are organized at two levels:

**Global skills** — Live in the agent repo (e.g., `agents/templates/shared/skills/`). Available to all agent sessions regardless of project. Examples: "how to write claude.md", "how to write good ticket comments", "how to do code review", "git workflow conventions".

**Project skills** — Live in the project repo (e.g., `projects/wedding-website/skills/`). Available only when working on that project. Examples: "how to deploy wedding-website to Vercel", "how to run the Shopify API integration tests", "wedding-website design system conventions".

**Loading mechanism**: When an agent session starts for a task, it loads:
1. The agent type's system prompt (from agent repo)
2. Global skills (from agent repo's shared skills directory)
3. The target project's claude.md (from project repo)
4. The target project's skills (from project repo's skills directory)
5. If the task spans multiple projects, load claude.md and skills from all relevant projects

### 5.5 Project as a Scheduling Unit

The dispatcher's logic changes from agent-centric to project/task-centric:

```
Old: For each agent → check if agent has pending work → dispatch
New: For each project (by priority) → find actionable tasks → spawn appropriate agent session
```

Project-level scheduling considerations:
- **Priority**: Which project needs attention most? (deadline proximity, blocked items, Human-assigned priority)
- **Concurrency**: How many agent sessions can run simultaneously for one project? (budget constraint, resource constraint)
- **Task selection**: Within a project, which task should be worked on next? (dependency order, priority, staleness)

---

## Part 6: Task System & Workflow

### 6.1 Task as the Atomic Unit of Work

A task (ticket) is the smallest schedulable unit. It contains:

- **Description**: What needs to be done
- **Acceptance criteria**: How to know it's done
- **Project**: Which project it belongs to
- **Phase**: Which workflow phase it's in (plan, implement, test, deliver)
- **Dependencies**: Which other tasks must complete first
- **Comments/History**: The full record of work done, decisions made, errors encountered

### 6.2 Task-Level Memory Protocol

Every agent working on a task MUST maintain the ticket as a living document:

**On pickup**: Read the full ticket (description + all comments) to recover context. This is how a stateless agent "remembers" previous work.

**During work**: Add structured comments at key milestones:
- Branch and PR created: `Branch: feature/xyz, PR: #123`
- Key decisions made: `Decision: Using approach A because [reason]`
- Errors encountered and resolved: `Issue: X happened. Fix: Y. Root cause: Z.`
- Human feedback received: `Human input: [summary of what Human said]`

**On completion**: Final comment summarizing what was done, what changed, and any follow-up items. Update project claude.md if the task produced reusable knowledge.

This protocol ensures that any future agent session can pick up where the previous one left off, without relying on session context.

### 6.3 Workflow Phases

A task's lifecycle can vary by project, but the general pattern is:

```
Planning → Implementation → Testing → Delivery → Done
```

Each phase may invoke a different thinking mode (product → dev → QA → ops) within the same or different agent sessions. The key constraint: phase transitions must be recorded in the ticket, so the next session knows which phase to resume from.

---

## Part 7: Observation & Monitoring

### 7.1 Metrics That Matter

The monitoring system must track and expose:

**Cost**: Token usage converted to dollars, broken down by project and agent type. Not just raw token counts — Human needs to know "wedding-website cost $47 this week, 60% of total spend."

**Progress**: Task completion rate and velocity per project. Burndown tracking against deadlines. "At current velocity, wedding-website will be done by May 15" is more useful than "3 tickets completed today."

**Time**: Agent effective work time vs. idle time vs. rate-limit wait time. Useful for scheduling optimization and cost control.

**Quality**: Ticket rejection rate (tasks sent back from QA to dev), bug reopen rate, and deployment rollback frequency. Quantity without quality is meaningless.

### 7.2 Dashboard (Web UI)

The existing web dashboard serves as the real-time observation layer. Key views:

- **Project-centric progress view** (not just agent-centric) — progress against milestones and deadlines
- **Cost breakdown** by project and time period
- **Blocked items** requiring Human attention
- **Agent session status** — what's running, what's idle, what's rate-limited
- **Token usage trends** — daily/weekly/monthly with cost projection

### 7.3 Relationship Between Digest and Dashboard

The Morning Brief is a compressed, push-based snapshot derived from the same data that powers the dashboard. The dashboard is for pull-based, real-time, detailed exploration. They are not separate systems — the digest is generated from dashboard data.

---

## Part 8: Action Plan

### Phase 0: Cleanup & Baseline (This Week)

**Goal**: Remove clutter, establish clean baseline for redesign.

- [ ] Freeze all non-harness projects (SEOPilot, DevToolBox, Pomodoro, Showcase, Wedding Website) — archive configs in agents.yaml
- [ ] Close stale tickets for frozen projects
- [ ] Commit and push all pending changes
- [ ] Document current system state as the v1 baseline

### Phase 1: Memory System & Project Context (Week 1-2)

**Goal**: Establish the externalized memory architecture before changing anything else.

- [ ] Define claude.md template and size guidelines (max 300 lines)
- [ ] Create the "how to maintain claude.md" global skill
- [ ] Create the "how to write ticket comments" global skill (structured comment protocol)
- [ ] Restructure existing projects to follow the three-layer memory model (claude.md → docs/ → ticket history)
- [ ] Audit and restructure global vs. project skills

### Phase 2: Agent Consolidation & Task-Driven Dispatch (Week 2-3)

**Goal**: Move from 18 persistent agents to 3 agent types with task-driven spawning.

- [ ] Define system prompts for three agent types (Development, Operations, Assistant)
- [ ] Redesign dispatcher: from agent-polling to task-selection + agent-spawning
- [ ] Implement session lifecycle management (spawn, suspend, resume, terminate)
- [ ] Migrate from static agent-project bindings to dynamic task-based assignment
- [ ] Implement multi-project claude.md loading for cross-project tasks

### Phase 3: Morning Brief & Human Interaction (Week 3-4)

**Goal**: Human gets actionable daily digest and can respond with minimal effort.

- [ ] Build digest generation: status snapshot, decisions needed, resources needed
- [ ] Implement structured decision format (context + recommendation + options)
- [ ] Build natural language response parsing (Human reply → actionable directives)
- [ ] Set up delivery mechanism (email or messaging, daily at 7:00 AM)
- [ ] Build execution confirmation flow for significant decisions

### Phase 4: Agent Identity & Autonomy (Week 4-5)

**Goal**: Agents can operate with minimal Human resource provision.

- [ ] Set up agent email addresses on team domain
- [ ] Configure 1Password vaults with appropriate access per agent type
- [ ] Evaluate virtual card / payment solution for agent spending (Stripe Issuing or similar)
- [ ] Define budget control mechanism (per-project caps, per-transaction limits, approval thresholds)
- [ ] Audit remaining Human-dependent operations and automate or eliminate

### Phase 5: Re-enable Projects (Week 5+)

**Goal**: Validate the redesigned system by running real projects autonomously.

- [ ] Define project autonomy checklist (can agents deploy, test, iterate, and report without Human?)
- [ ] Re-enable one project (e.g., Wedding Website — deadline May 23) as the first test
- [ ] Monitor and iterate on the memory system, dispatch, and digest based on real usage
- [ ] Gradually re-enable additional projects as the system proves stable

---

## Part 9: Success Criteria

| Metric | v1 (Current) | v2 (Target) |
|--------|-------------|-------------|
| Human time/day | 30-60 min (reactive, scattered) | 5-10 min (Morning Brief + response) |
| Human-blocked tickets | 5-10 at any time | 0-2 at any time |
| Days to resolve Human decision | 4-7 days | < 24 hours (via Morning Brief cycle) |
| Active agent instances | 18 persistent | 2-5 concurrent, spawned on demand |
| Agent types | 18 role-specific | 3 (Development, Operations, Assistant) |
| Memory loss on session restart | Total (context-dependent) | Zero (fully externalized) |
| Project context recovery time | 10-15 min (agent re-reads everything) | 2-3 min (structured claude.md + ticket) |
| Digest delivery | None | Daily, automated, actionable |
| Agent autonomous spending | None (Human provides everything) | Within budget, auto-approved under threshold |

---

## Part 10: Open Questions

1. **Project workflow definition**: How exactly should each project define its task lifecycle stages? Is a simple linear flow (plan → implement → test → deliver) enough, or do we need project-specific workflow configuration?

2. **Session persistence threshold**: How long should an agent session stay alive while idle before being released? Too short = frequent context recovery cost. Too long = wasted resources.

3. **Concurrent session limits**: How many agent sessions can run simultaneously? This is a budget question (token cost) and an infrastructure question (compute resources).

4. **Wedding website deadline**: May 23 is ~6 weeks away. When should we re-enable it as the first autonomous project test? After Phase 2 (dispatch redesign) or Phase 3 (Morning Brief)?

5. **Payment mechanism specifics**: Which virtual card provider to use? What are the right budget tiers and approval thresholds?

6. **Cloud deployment**: Still relevant as a future phase — running on cloud (AWS/GCP) for 24/7 operation vs. current Mac Mini. Estimated ~$50-100/month. Priority TBD after core redesign is validated.
