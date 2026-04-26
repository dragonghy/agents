"""FastAPI app — read-only console for the agent harness.

Mounts:
- /api/workspaces, /api/agents, /api/tickets, /api/briefs, /api/cost, /api/tmux
- /api/health
- /  → static SPA (built by `npm run build`, dropped into ./static/)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import repo
from app.routes import agents, briefs, cost, tickets, tmux, workspaces

app = FastAPI(
    title="Agent Harness Console",
    description="Read-only Phase 1 — ticket #498",
    version="0.1.0",
)

# Vite dev server runs on :3001 and proxies /api → :3000, but if the user wants
# to hit the backend directly during dev we still allow CORS from localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    """Confirm both DBs and the briefs dir are reachable in read-only mode."""
    out: dict = {"status": "ok"}
    try:
        out["repo_root"] = str(repo.repo_root())
    except FileNotFoundError as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)
    out["mcp_db_exists"] = repo.mcp_db_path().exists()
    out["tasks_db_exists"] = repo.tasks_db_path().exists()
    out["briefs_dir_exists"] = repo.briefs_dir().exists()
    out["agents_yaml_exists"] = repo.agents_yaml_path().exists()
    return out


# Mount all API routers under /api
api_routers = [
    workspaces.router,
    agents.router,
    tickets.router,
    briefs.router,
    cost.router,
    tmux.router,
]
for r in api_routers:
    app.include_router(r, prefix="/api")


# Static SPA mount with HTML fallback for client-side routing.
static_dir = Path(__file__).parent / "static"
if static_dir.exists() and (static_dir / "index.html").exists():
    # Mount /assets (Vite's default) for hashed chunks.
    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/")
    async def spa_index():
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        # Files outside /assets but inside static (vite.svg, favicons, etc.)
        candidate = static_dir / path
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        # SPA client routes — return index.html so React Router takes over
        return FileResponse(str(static_dir / "index.html"))
else:
    @app.get("/")
    async def no_spa():
        return {
            "status": "no-spa",
            "message": (
                "Frontend not built. Run `cd ../frontend && npm run build` "
                "or `make build` from apps/console/."
            ),
            "api_health": "/api/health",
        }
