# V2 Migration Progress Tracker

> This file tracks implementation progress for the Agent Harness v2 redesign.
> Using MD instead of ticket system since we're migrating the ticket system itself.
> Updated by: admin agent

---

## Technical Analysis

### Key Technical Challenges Identified

1. **Session Lifecycle: Persistent → Ephemeral**
   - Current: `restart_all_agents.sh` creates 18 permanent tmux windows from agents.yaml
   - Needed: Dynamic spawning — create tmux window per task, tear down when done
   - Challenge: How to detect "task complete" vs "waiting for input" vs "stuck"
   - Solution approach: Reuse existing idle detection + new "session manager" module

2. **Dispatcher Rewrite: Agent-polling → Task-selection**
   - Current: `for agent in agents: check_work(agent) → dispatch`
   - Needed: `for project in projects: find_tasks() → select_agent_type() → spawn_session()`
   - Challenge: Backward compatibility during migration — can't break running system
   - Solution approach: Build v2 dispatcher alongside v1, switchable via config flag

3. **Agent Type System: 18 instances → 3 templates**
   - Current: 18 separate AGENT.md files in templates/<role>/
   - Needed: 3 agent type definitions (dev, ops, assistant) with dynamic thinking modes
   - Challenge: How does one "dev" agent handle product/dev/QA thinking?
   - Solution approach: Task phase field drives thinking mode; system prompt includes all modes with phase-based activation

4. **Project Configuration**
   - Current: Agents have `add_dirs` pointing to project paths
   - Needed: Projects define their own config (path, claude.md, skills, priority, deadline)
   - Solution: New `projects:` section in agents.yaml (or separate projects.yaml)

5. **Concurrency & Slot Management**
   - Current: 18 agents always running (most idle)
   - Needed: Pool of 2-5 concurrent session slots, priority-based allocation
   - Challenge: Rate limiting — Claude API limits shared across all sessions
   - Solution: Session pool manager with rate-limit awareness

6. **Task Phase Tracking**
   - Current: Tickets have status (new/in_progress/done) but no phase
   - Needed: phase field (plan/implement/test/deliver) to drive thinking mode selection
   - Solution: Add `phase` column to tickets table (same migration pattern as `assignee`)

7. **Self-Preservation**
   - Admin agent (me) runs in the same tmux session as all other agents
   - MUST NOT kill my own window during any restructuring
   - Safe operations: modify configs, create files, kill OTHER agent windows

### Migration Strategy

Build v2 components incrementally alongside v1. No big-bang cutover.

```
Week 1: Phase 0 (cleanup) + Phase 1 (memory system) — pure additions, no v1 changes
Week 2: Phase 2 (agent types + new dispatcher) — build alongside v1, test independently
Week 3: Phase 3 (morning brief) — independent feature, no v1 dependency
Week 4: Cutover — switch from v1 dispatcher to v2, decommission old agents
```

---

## Phase 0: Cleanup & Baseline

### Tasks
- [x] Freeze non-harness projects in agents.yaml (set dispatchable: false)
- [x] Close stale tickets for frozen projects (archived 9 tickets: #425,420,410,409,371,364,423,430,407,336,335)
- [x] Commit all pending changes → `62b1179` + `91edf5a`, pushed to main
- [x] Restart daemon with all changes → confirmed healthy, brief endpoint working

### Progress Log
- **2026-04-12 14:00**: Added v2 config section to agents.yaml (v2.enabled, agent_types, projects)
- **2026-04-12 14:00**: Archived 9 stale tickets for frozen projects (wedding, devtoolbox, seopilot, trading)
- **2026-04-12 14:00**: Remaining open: #442 (vmnet sudo), #440 (VM network), #429 (SSH key), #362 (Cloud infra)

---

## Phase 1: Memory System & Project Context

### Tasks
- [x] Create claude.md template and size guidelines
- [x] Create global skill: "how to maintain claude.md" → `templates/shared/skills/claude-md-guide/SKILL.md`
- [x] Create global skill: "how to write ticket comments" → `templates/shared/skills/ticket-comment-protocol/SKILL.md`
- [x] Create project claude.md for agent-hub → `/Users/huayang/code/agents/claude.md`
- [ ] Restructure other projects to 3-layer memory model (deferred — projects frozen)
- [ ] Audit and reorganize global vs project skills

### Progress Log
- **2026-04-12 14:01**: Created `claude-md-guide` skill (93 lines, covers 300-line cap, what belongs/doesn't, maintenance rules)
- **2026-04-12 14:01**: Created `ticket-comment-protocol` skill (131 lines, covers pickup/milestone/completion/knowledge eval protocols)
- **2026-04-12 14:02**: Created project `claude.md` (72 lines, covers arch, conventions, pitfalls, references)

---

## Phase 2: Agent Consolidation & Task-Driven Dispatch

### Tasks
- [x] Define Development agent type system prompt → `templates/v2/development.md` (72 lines)
- [x] Define Operations agent type system prompt → `templates/v2/operations.md` (72 lines)
- [x] Define Assistant agent type system prompt → `templates/v2/assistant.md` (63 lines)
- [x] Add `phase` column to tickets table (migration + schema + field sets)
- [x] Add project config schema → `agents.yaml` v2 section (agent_types + projects)
- [x] Build session manager → `services/agents-mcp/src/agents_mcp/session_manager.py`
- [x] Build v2 dispatcher → `services/agents-mcp/src/agents_mcp/dispatcher_v2.py`
- [x] Wire v2 dispatcher into daemon startup (behind v2.enabled flag)
- [ ] Integration test: spawn an ephemeral dev session for a test task
- [ ] Build concurrency/slot manager (integrated into session_manager)

### Progress Log
- **2026-04-12 14:01**: Created 3 agent type prompts in `templates/v2/` (development, operations, assistant)
- **2026-04-12 14:03**: Created `session_manager.py` — SessionManager class with spawn/release/monitor_loop
- **2026-04-12 14:04**: Created `dispatcher_v2.py` — task-selection dispatch with phase→agent_type mapping
- **2026-04-12 14:05**: Added v2 config to agents.yaml (v2.enabled flag, agent_types, projects)
- **2026-04-12 14:10**: Wired v2 dispatcher into daemon startup (server.py, behind v2.enabled flag)

---

## Phase 3: Morning Brief & Human Interaction

### Tasks
- [x] Build digest generation → `services/agents-mcp/src/agents_mcp/morning_brief.py`
- [x] Set up daily scheduled delivery (7:00 AM) → wired into daemon startup via `brief_loop`
- [x] Add MCP tool `generate_morning_brief` for on-demand trigger
- [x] Add REST endpoint `GET /api/v1/brief` for web access
- [ ] Implement email delivery via Outlook MCP (currently saves to `briefs/` dir)
- [ ] Build response parsing (natural language → directives)

### Progress Log
- **2026-04-12 14:15**: Created `morning_brief.py` — generate_brief(), save_brief(), brief_loop()
- **2026-04-12 14:17**: Added `generate_morning_brief` MCP tool + `GET /v1/brief` REST endpoint
- **2026-04-12 14:20**: Tested: brief generates correctly with health, work summary, decisions, cost sections
- **2026-04-12 14:23**: Fixed PlainTextResponse import in api.py, daemon restarted successfully
- **2026-04-12 14:25**: `GET /v1/brief` live and returning full digest (health, 3 human tickets, $0.63 today cost)
- **2026-04-12 14:25**: All changes committed (`62b1179`, `91edf5a`) and pushed to main

---

## Summary: What's Done vs What's Left

### Done (deployed, running in production)
- Pub/Sub system (subscribers, notifications, service locks) — ✅ live
- 3 v2 agent type prompts (development, operations, assistant) — ✅ created
- Session manager & v2 dispatcher — ✅ built, behind feature flag
- Memory system (claude.md, skills, ticket protocol) — ✅ created
- Morning Brief (generation, REST API, daily loop) — ✅ live
- Agent roster frozen (4 active, 14 frozen) — ✅ live
- Ticket cleanup (9 archived) — ✅ done

### Remaining (non-blocking, can be done incrementally)
- [ ] Flip `v2.enabled: true` and test ephemeral session spawning end-to-end
- [ ] Email delivery for Morning Brief (Outlook MCP integration)
- [ ] Natural language response parsing (Human reply → directives)
- [ ] Concurrency/slot manager refinement
- [ ] Re-enable frozen projects one at a time as autonomous tests
