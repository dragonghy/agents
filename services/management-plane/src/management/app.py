"""Starlette application for the Management Plane."""

import asyncio
import logging
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, FileResponse, HTMLResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .db import close_db, get_db
from .instance_manager import MOCK_MODE, health_check_loop
from .routes.auth import routes as auth_routes
from .routes.companies import routes as company_routes
from .routes.usage import routes as usage_routes
from .security import get_cors_origins
from .billing import STRIPE_ENABLED

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def health(request: Request) -> JSONResponse:
    """GET /api/health — health check with subsystem status."""
    db_ok = False
    try:
        db = await get_db()
        await db.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass

    return JSONResponse({
        "status": "ok" if db_ok else "degraded",
        "service": "management-plane",
        "database": db_ok,
        "stripe": STRIPE_ENABLED,
        "mock_mode": MOCK_MODE,
    })


async def on_shutdown():
    """Clean up database connection on shutdown."""
    await close_db()
    logger.info("Management Plane shut down")


# Determine static file paths
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SERVICE_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
_STATIC_DIR = os.path.join(_SERVICE_DIR, "web", "dist")
_INDEX_HTML = os.path.join(_STATIC_DIR, "index.html")


async def spa_fallback(request: Request):
    """Serve index.html for all non-API routes (SPA fallback)."""
    if os.path.exists(_INDEX_HTML):
        return FileResponse(_INDEX_HTML)
    return HTMLResponse(
        "<h1>Management Plane</h1><p>Frontend not built. Run <code>cd web && npm run build</code></p>",
        status_code=200,
    )


def create_app() -> Starlette:
    """Create the Starlette application."""

    api_routes = [
        Route("/api/health", health, methods=["GET"]),
        *auth_routes,
        *company_routes,
        *usage_routes,
    ]

    # SPA static files
    spa_routes = []
    if os.path.exists(_STATIC_DIR):
        spa_routes.append(
            Mount("/assets", app=StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")))
        )

    all_routes = api_routes + spa_routes + [
        Route("/{path:path}", spa_fallback, methods=["GET"]),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=get_cors_origins(),
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ]

    async def on_startup():
        """Start background tasks."""
        if not MOCK_MODE:
            asyncio.create_task(health_check_loop())
            logger.info("Health check loop started (real mode)")
        else:
            logger.info("Health check loop skipped (mock mode)")

    app = Starlette(
        routes=all_routes,
        middleware=middleware,
        on_startup=[on_startup],
        on_shutdown=[on_shutdown],
    )

    logger.info("Management Plane created (static_dir=%s, mock=%s)", _STATIC_DIR, MOCK_MODE)
    return app


app = create_app()


def main():
    """Run the server."""
    import uvicorn

    host = os.environ.get("MGMT_HOST", "0.0.0.0")
    port = int(os.environ.get("MGMT_PORT", "3000"))
    logger.info("Starting Management Plane on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
