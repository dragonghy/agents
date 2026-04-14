# Executive Status — Agent Harness

> Last updated: 2026-04-13
> Updated by: admin (after strategic direction session with Human)

## Project

**Agent Harness** — A self-running multi-agent development platform. Long-term vision: productize into a platform that enables anyone to build a one-person company through AI-guided decision-making.

## Strategic Direction (from Human, 2026-04-13)

Three parallel tracks:

### Track 1: Agent Capability Expansion
Prove that agents can handle real-world tasks autonomously:
- **Personal assistant tasks**: Pickleball court booking (browser automation), travel research with evaluation criteria
- **Development tasks**: Full lifecycle — plan, code, test, deploy, ship to production
- **Goal**: Demonstrate the agent can be a genuine personal assistant + developer, not just a ticket processor

### Track 2: Trading Project (URGENT)
- Existing stock trading project has been losing money — Human is anxious
- Needs agent to either: (a) optimize existing strategies, or (b) actively manage trades
- Constraint: agent must not buy Human's prohibited stock list
- This is a real, live project with financial consequences — high priority

### Track 3: Startup Product — "One-Person Company Platform"
Core insight: In the AI era, one person can build what used to require a team. But most people don't know where to start.

Product concept:
- User comes in not knowing what to do
- Platform does research, generates ideas, presents options
- User makes choices (A/B/C/D) — like a "choose your adventure" game
- AI executes: registers domain, builds product, deploys, sets up payment
- Platform capabilities: domain registration, deployment, payment, identity — all shared infrastructure
- Each choice narrows the funnel until a real product exists

Key challenges:
- User still needs to provide: money, basic info, final decisions
- Some steps can't be fully automated (but minimize these)
- The "choice-making" UX is the product differentiator

Revenue model: Platform fee + potentially rev share on products built

## Current Phase

**V2 Stabilization Complete** → transitioning to **Capability Expansion + Product Exploration**

V2 infrastructure is done:
- Ephemeral agent sessions ✅
- Task-driven dispatch ✅
- Telegram communication ✅
- Executive Brief ✅
- V1 cleanup (9 PRs merged) ✅

## Next Actions (COO priorities)

1. **Immediate**: Set up agent capability demos
   - Pickleball booking (browser automation proof of concept)
   - Resume trading project (find existing code, assess state)
2. **This week**: Research the "one-person company platform" idea
   - Market analysis: competitors, TAM, existing solutions
   - Technical feasibility: what platform capabilities do we already have vs need to build
3. **Ongoing**: Continue harness improvements as needed (bugs, performance)

## Open Questions (for Human)

1. Trading project: Where is the existing code? What broker/API is being used? What's the current strategy?
2. One-person company platform: Do you want to start with a landing page / MVP to test interest, or go deeper on research first?
3. Priority ranking: If you had to pick ONE track to focus on first, which one?

## Key Decisions Log

| Date | Decision | By |
|------|----------|-----|
| 2026-04-12 | Focus 100% on Agent Harness, freeze all other projects | Human |
| 2026-04-12 | V2 architecture: ephemeral agents, 3 agent types | Human + Admin |
| 2026-04-12 | Admin = COO, Human = Chairman | Human |
| 2026-04-13 | Executive Brief format with working memory | Human |
| 2026-04-13 | Three strategic tracks: capabilities, trading, startup platform | Human |
