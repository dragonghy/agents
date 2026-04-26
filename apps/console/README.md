# Agent Harness Console (Phase 1 — Read-Only)

Independent web console for the agent harness. Built as a parallel prototype to validate the SDK + GUI architecture before deciding whether to replace the existing daemon-bundled UI. Tracks ticket [#498](http://localhost:9090/dashboard/show/498).

## Independence guarantees

- **Read-only**: opens both SQLite databases in URI read-only mode (`?mode=ro`). No write operations exist in the codebase.
- **Doesn't talk to the running daemon over HTTP** — reads the underlying SQLite files directly. The console works even when the daemon is down.
- **Doesn't share its event loop or DB connections with the daemon** — no shared imports from `agents_mcp`.
- **Tmux access is read-only** (`tmux capture-pane -p`). Never creates or kills windows.
- **Bound to 127.0.0.1:3000** by default. Add SSO + Cloudflare Tunnel later.

## Layout

```
apps/console/
├── README.md                this file
├── Makefile                 dev / build / run / test
├── backend/                 Python FastAPI on port 3000
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py          FastAPI app + SPA mount
│   │   ├── db.py            read-only sqlite helpers
│   │   ├── pricing.py       Sonnet $/M constants (matches morning_brief.py)
│   │   ├── repo.py          path resolver (ROOT_DIR = repo root)
│   │   ├── routes/
│   │   │   ├── workspaces.py
│   │   │   ├── agents.py
│   │   │   ├── tickets.py
│   │   │   ├── briefs.py
│   │   │   ├── cost.py
│   │   │   └── tmux.py
│   │   └── static/          built frontend lands here (gitignored)
│   └── tests/
│       └── test_smoke.py    hits each endpoint; asserts shape
└── frontend/                Vite + React + TS, dev port 3001
    ├── package.json
    ├── vite.config.ts       proxies /api → :3000
    ├── tsconfig.json
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api.ts           fetch helpers
        ├── types.ts
        ├── styles.css
        └── components/
            ├── WorkspaceSwitcher.tsx
            ├── AgentPanel.tsx
            ├── TicketBoard.tsx
            ├── BriefHistory.tsx
            ├── CostDashboard.tsx
            ├── TmuxStream.tsx
            └── AgentDetail.tsx
```

## Quick start

```bash
# from apps/console/

# 1. Install backend deps + frontend deps
make install

# 2. Run dev (backend on :3000, frontend dev on :3001 with /api proxy)
make dev

# Open http://localhost:3001 — Vite dev server with HMR.

# Or build the frontend into backend/static and serve from a single port:
make build
make run        # http://localhost:3000
```

## Acceptance (per ticket #498)

1. `http://localhost:3000/` renders agent panel with admin / dev-alex / ops / qa-lucy.
2. Workspace switcher toggles Work ↔ Personal; Personal currently empty.
3. Ticket board shows in-progress tickets (#491, #492, #493, #497, #498, ...).
4. Brief history lists recent briefs (4/12 → 4/26 currently).
5. Cost dashboard shows today / 7-day / lifetime in $.
6. Tmux activity stream shows the most recent capture-pane output for active agent windows.

## Why a separate `apps/` tree?

The existing daemon-bundled UI lives at `services/agents-mcp/src/agents_mcp/web/`. The Phase 1 ticket (#498) calls for an *independent* prototype so we can iterate on the SDK + GUI architecture without disrupting production. Once the prototype is validated, the path forward is one of:

1. Keep both, route Phase 2 writes through the new console only.
2. Migrate the daemon-bundled UI's features here and retire `agents_mcp/web/`.
3. Throw the prototype away because we learned the daemon-bundled approach is fine.

This is a Phase 3 decision; for now, both coexist.

## What's NOT here (intentional, Phase 1 scope)

- Write actions (create ticket, send message, restart agent) — Phase 2.
- Authentication — local-only for now.
- Mobile responsiveness — desktop only.
- WebSocket / SSE — using simple polling (5s tmux, 10s tickets/agents).
- Multi-LLM SDK integration itself — Phase 3.
