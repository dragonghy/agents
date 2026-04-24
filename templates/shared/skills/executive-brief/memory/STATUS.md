# Executive Status — Agent Harness

> Last updated: 2026-04-24
> Updated by: admin

## What We're Building

**Agent Harness** — A self-running multi-agent platform where admin (COO) manages execution and Human (Chairman) sets direction. Agents are ephemeral — spawned per task, released when done.

**Long-term product vision**: A "One-Person Company Platform" where anyone can build a business by making choices (like a game), while AI handles research, building, deployment, and infrastructure.

## Current Phase

**Post-v2 stabilization → Executing on 3 strategic tracks**

V2 infrastructure fully operational. V1 artifacts cleaned up (9 PRs merged). Now executing the real work.

---

## Track 1: Agent Capabilities

**North Star**: Prove agents can handle real-world tasks autonomously — not just code, but browser automation, research with judgment, and service registration.

### Pickleball Booking (POC complete ✅, scheduled job pending)
- Agent successfully logged into CourtReserve, extracted 7-day availability
- **Next**: Daily noon scheduled job. Check day+8 for 7:00-9:00 PM slots. SMS notify if found.
- Status: Needs implementation ticket for scheduled job

### What We've Proven So Far
- Browser login + data extraction ✅
- Ticket-based development lifecycle ✅
- PR creation + CI observation ✅
- Telegram communication ✅
- 1Password credential access ✅

### What We Haven't Proven Yet
- Agent making a purchase (using Privacy.com card)
- Agent registering for a new service end-to-end (email + phone verification)
- Agent deploying a project to production independently

---

## Track 2: Trading (URGENT — real money at risk)

**North Star**: Agent actively manages live stock trading portfolio on Alpaca Markets. Human reviews strategy but agent has execution authority.

### Current State
- **Paper account result**: $100k → broke even after 4 months. Max drawdown -14.9%. Core issues: no portfolio-level risk control, no market regime filter.
- **Live API key**: In 1Password ✅ (AKVLLDRN7FHLNNCXMG2PEMHMKC, live endpoint)
- **Strategy document**: #467 in progress
- **Repo**: ~/code/trading (TypeScript, Alpaca Markets, 35 strategies)

### Human's Direction (verbatim from Telegram 4/14)
- "Let the agent operate. Full authority on live trading."
- "I need it to push and update trading strategy"
- "During market hours, run about once per hour to monitor"
- "Paper is just for testing, Live is real money"
- "I can only help when I have time"

### Key Risks
- Real money exposure — wrong trade = real loss
- No portfolio-level stop-loss in current code
- Market regime filter missing (strategies run in all conditions)
- Need clear prohibited stock list from Human

### Next Steps
1. Complete TRADING_STRATEGY.md (#467)
2. Deploy live trading with improved risk controls
3. Set up hourly market monitoring during trading hours (9:30 AM - 4:00 PM ET)
4. Define prohibited stocks list

---

## Track 3: One-Person Company Platform

**North Star**: Build a platform where anyone creates a company by making choices. AI does research, building, and deployment. User only decides.

### The Core Idea (from Human's detailed description)

The insight: In the AI era, one person can build what used to need a team. But most people don't know where to start.

The product flow:
1. **Find direction**: AI researches trending areas, generates ideas, presents options
2. **Narrow down**: User picks ideas they like → AI shapes into 1-2 concrete directions
3. **Build**: Each step is a choice (A/B/C/D). AI handles implementation details.
4. **Platform capabilities**: Domain registration, deployment, payment — all shared infrastructure
5. **Result**: User makes choices like playing a game → a real product exists

### Human's Deeper Analysis (from Telegram 4/14)
- Lovable/Replit are "website builders", not "company builders"
- Building a website is a small part of running a one-person company
- The full journey: idea → validate → build → launch → monetize → scale
- Current competitors don't cover the full journey
- Our differentiator: the "choice-making game" covers EVERYTHING, not just the build step

### Key Challenges (from Human's thinking)
- Users still need to provide: money, basic info, final decisions
- Some steps can't be fully automated (minimize these)
- Platform capabilities (domain, deploy, payment) are the moat
- The UX of "making choices" is the product differentiator

### What Exists
- Market research report: `projects/business-research/solo-founder-platform/research-report.md`
- Landing page: https://solo-platform.vercel.app
- Reference companies: Base44 ($80M Wix acquisition), Lovable ($100M ARR), Replit ($100M ARR)

### Next Steps
1. Deeper research on Lovable/Replit — what exactly do they offer vs. what's missing?
2. Define the full "company creation journey" — every step from idea to revenue
3. Map which steps can be automated vs. need user input
4. Design the "choice-making" UX prototype
5. Build MVP of one slice (e.g., "find your idea" → "validate with landing page")

---

## System Health

- V2 dispatcher: running (10s cycle)
- Telegram bot: running
- Active sessions: 0 ephemeral (3 permanent: admin, mcp-daemon, telegram-bot)
- Open PRs: 0 (PR #13 merged 4/23)
- Open tickets: #479 (Human review, waiting 8d) — #485/#483 closed 4/23
- Admin wake-up: fixed (Telegram → admin inbox → tmux notify when idle)
- Brief responder: fixed (no longer auto-executes on bare #numbers)
- **Admin supervisor: deployed 4/24** (launchd job `com.agents.admin.supervisor`, 60s cycle, 4h+pending-work trigger, 1h cooldown). Fixes the 4/18–4/22 silent-death pattern.
- **PR auto-close monitor: deployed 4/24** (daemon-internal 10min cycle, closes tickets referenced in merged PRs). Fixes the stale-status-4 velocity-lie pattern.

## Human Communication Preferences

- Primary: Telegram (@agents_daemon_bot)
- Report format: Executive Brief (CEO-level, not ticket dumps)
- Response style: "I'm a Chairman. Give me decisions with recommendations."
- Don't spam: Only notify when there's real change
- Links must be clickable from phone
- Admin should find work independently, not wait for instructions

## Key Decisions Log

| Date | Decision | Source |
|------|----------|--------|
| 4/12 | Focus 100% on Agent Harness | Human (tmux session) |
| 4/12 | V2 architecture: ephemeral agents, 3 types | Human (RETROSPECTIVE.md) |
| 4/12 | Admin = COO, Human = Chairman | Human (tmux session) |
| 4/13 | Three tracks: capabilities, trading, platform | Human (tmux session) |
| 4/13 | Executive Brief format with working memory | Human (tmux session) |
| 4/14 | Trading: agent full authority on live | Human (Telegram) |
| 4/14 | Pickleball: daily noon, day+8, 7-9PM, SMS | Human (Telegram) |
| 4/14 | Reports must be CEO-level, not ticket dumps | Human (Telegram) |
| 4/14 | Lovable/Replit = website builders, not company builders | Human (Telegram) |
| 4/15 | Memory system must capture discussion details | Human (tmux session) |
| 4/17 | Self-merge PRs when Human can't review (low-risk) | Human (Telegram) |
| 4/23 | Same policy applied: PR #13 Pickleball fix self-merged | admin (applied rule) |
| 4/24 | Same policy applied: PR #14 (admin supervisor) + PR #15 (pr_monitor) self-merged | admin (applied rule) |
