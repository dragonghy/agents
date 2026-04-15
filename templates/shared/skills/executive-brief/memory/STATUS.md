# Executive Status — Agent Harness

> Last updated: 2026-04-14
> Updated by: admin

## What We're Building

**Agent Harness** — A self-running multi-agent platform. Admin (COO) manages execution, Human (Chairman) sets direction.

Long-term vision: Productize into a platform enabling anyone to build a one-person company through AI-guided decision-making.

## Current Phase

**Operational — Running 3 parallel tracks**

V2 infrastructure complete. System operational with ephemeral agents, Telegram communication, executive brief. Now executing on strategic directions.

## Track 1: Agent Capabilities

**North Star**: Prove agents can handle real-world tasks autonomously.

**Pickleball POC** ✅ Complete
- Agent successfully logged into CourtReserve, extracted 7-day availability
- **Next**: Set up daily scheduled job (noon, check day+8 for 7-9PM slots, SMS notify Human)
- Ticket needed for scheduled job implementation

**Personal Assistant** — template exists (`templates/v2/assistant.md`) but no registered instance. Paused until needed.

## Track 2: Trading (URGENT — real money)

**North Star**: Agent actively manages live trading portfolio on Alpaca Markets.

**Status**: 
- Evaluation complete: $100k paper account broke even over 4 months after 15% drawdown
- Core issues identified: no portfolio-level risk control, no market regime filter
- Alpaca Live API key now in 1Password ✅
- Strategy document in progress (#467)

**Open tickets**:
- #460: Trading evaluation (done, needs closure after live deployment)
- #467: TRADING_STRATEGY.md — agent writing formal strategy document

**Next steps**:
- Deploy live trading with improved risk controls
- Set up hourly market monitoring during trading hours
- Human approved: "让 Agent 去操作，全权操盘 Live"

## Track 3: One-Person Company Platform

**North Star**: Build a platform where anyone creates a company by making choices, AI does the rest.

**Completed**:
- Deep research report: `projects/business-research/solo-founder-platform/research-report.md`
  - Market signal strong (Base44 → Wix $80M, Lovable $100M ARR in 8 months)
  - Our differentiator: "choice-making game" UX
- Landing page live: https://solo-platform.vercel.app

**Next steps**:
- Human wants deeper research on Lovable/Replit business models
- Define MVP feature set
- Build prototype of the "choice-making" flow

## Blocked

- #461: VM network issue — needs Human to run `sudo vmnet-cli --stop && --start`

## Open Questions for Human

None currently. All 3 tracks have clear direction.

## Key Decisions Log

| Date | Decision | By |
|------|----------|-----|
| 2026-04-12 | Focus on Agent Harness, freeze other projects | Human |
| 2026-04-12 | Admin = COO, Human = Chairman | Human |
| 2026-04-13 | Three tracks: capabilities, trading, platform | Human |
| 2026-04-13 | Executive Brief format (not ticket dumps) | Human |
| 2026-04-14 | Trading: Agent full authority on live trading | Human |
| 2026-04-14 | Pickleball: daily noon job, check day+8 for 7-9PM | Human |
| 2026-04-14 | Telegram messages route to admin, not auto-ticket | Human |
