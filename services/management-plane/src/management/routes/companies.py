"""Company CRUD + instance lifecycle API routes."""

import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..auth import get_current_user
from ..models import (
    create_company,
    get_company,
    get_events,
    list_companies,
    update_company,
    verify_company_ownership,
)
from ..instance_manager import (
    create_instance,
    delete_instance,
    get_instance_logs,
    get_instance_status,
    get_template_info,
    pause_instance,
    resume_instance,
    start_instance,
    stop_instance,
)


def _require_auth(handler):
    """Decorator that injects user_id from JWT into handler."""

    async def wrapper(request: Request) -> JSONResponse:
        payload = await get_current_user(request)
        if not payload:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        request.state.user_id = payload["sub"]
        return await handler(request)

    return wrapper


async def _get_owned_company(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """Helper to get company owned by current user. Returns (company, error_response)."""
    company_id = request.path_params["id"]
    company = await verify_company_ownership(company_id, request.state.user_id)
    if not company:
        return None, JSONResponse({"error": "Company not found"}, status_code=404)
    return company, None


# ── CRUD ──


@_require_auth
async def list_companies_route(request: Request) -> JSONResponse:
    """GET /api/companies"""
    companies = await list_companies(request.state.user_id)
    return JSONResponse({"companies": companies})


@_require_auth
async def create_company_route(request: Request) -> JSONResponse:
    """POST /api/companies"""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "Company name is required"}, status_code=400)

    slug = (body.get("slug") or "").strip() or None
    template = body.get("template", "standard")
    auth_type = body.get("auth_type")
    auth_token = body.get("auth_token")

    if template not in ("solo", "standard", "full", "custom"):
        return JSONResponse({"error": "Invalid template"}, status_code=400)

    company = await create_company(
        user_id=request.state.user_id,
        name=name,
        slug=slug,
        template=template,
        auth_type=auth_type,
        auth_token=auth_token,
        config=body.get("config"),
    )

    # Auto-deploy instance
    try:
        await create_instance(company["id"])
        company = await get_company(company["id"])
    except Exception as e:
        await update_company(company["id"], status="error")
        company = await get_company(company["id"])
        return JSONResponse({"company": company, "warning": str(e)}, status_code=201)

    return JSONResponse({"company": company}, status_code=201)


@_require_auth
async def get_company_route(request: Request) -> JSONResponse:
    """GET /api/companies/:id"""
    company, err = await _get_owned_company(request)
    if err:
        return err
    return JSONResponse({"company": company})


@_require_auth
async def update_company_route(request: Request) -> JSONResponse:
    """PATCH /api/companies/:id"""
    company, err = await _get_owned_company(request)
    if err:
        return err

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Only allow updating certain fields
    allowed = {"name", "slug", "template", "config"}
    updates = {k: v for k, v in body.items() if k in allowed}

    if not updates:
        return JSONResponse({"company": company})

    updated = await update_company(company["id"], **updates)
    return JSONResponse({"company": updated})


@_require_auth
async def delete_company_route(request: Request) -> JSONResponse:
    """DELETE /api/companies/:id"""
    company, err = await _get_owned_company(request)
    if err:
        return err

    await delete_instance(company["id"])
    return JSONResponse({"ok": True})


# ── Instance lifecycle ──


@_require_auth
async def start_route(request: Request) -> JSONResponse:
    """POST /api/companies/:id/start"""
    company, err = await _get_owned_company(request)
    if err:
        return err
    try:
        result = await start_instance(company["id"])
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@_require_auth
async def stop_route(request: Request) -> JSONResponse:
    """POST /api/companies/:id/stop"""
    company, err = await _get_owned_company(request)
    if err:
        return err
    try:
        result = await stop_instance(company["id"])
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@_require_auth
async def pause_route(request: Request) -> JSONResponse:
    """POST /api/companies/:id/pause"""
    company, err = await _get_owned_company(request)
    if err:
        return err
    try:
        result = await pause_instance(company["id"])
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@_require_auth
async def resume_route(request: Request) -> JSONResponse:
    """POST /api/companies/:id/resume"""
    company, err = await _get_owned_company(request)
    if err:
        return err
    try:
        result = await resume_instance(company["id"])
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@_require_auth
async def status_route(request: Request) -> JSONResponse:
    """GET /api/companies/:id/status"""
    company, err = await _get_owned_company(request)
    if err:
        return err
    try:
        result = await get_instance_status(company["id"])
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@_require_auth
async def logs_route(request: Request) -> JSONResponse:
    """GET /api/companies/:id/logs — returns both event log and Docker logs."""
    company, err = await _get_owned_company(request)
    if err:
        return err
    events = await get_events(company["id"])
    docker_logs = await get_instance_logs(company["id"])
    return JSONResponse({"events": events, "docker_logs": docker_logs})


# ── Auth config ──


@_require_auth
async def update_auth_route(request: Request) -> JSONResponse:
    """PUT /api/companies/:id/auth"""
    company, err = await _get_owned_company(request)
    if err:
        return err

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    auth_type = body.get("auth_type")
    auth_token = body.get("auth_token")

    if not auth_type or not auth_token:
        return JSONResponse(
            {"error": "auth_type and auth_token are required"}, status_code=400
        )

    if auth_type not in ("oauth_token", "api_key", "bedrock", "vertex"):
        return JSONResponse({"error": "Invalid auth_type"}, status_code=400)

    updated = await update_company(
        company["id"], auth_type=auth_type, auth_token=auth_token
    )
    return JSONResponse({"company": updated})


@_require_auth
async def auth_status_route(request: Request) -> JSONResponse:
    """GET /api/companies/:id/auth/status"""
    company, err = await _get_owned_company(request)
    if err:
        return err

    has_auth = bool(company.get("auth_type"))
    return JSONResponse({
        "configured": has_auth,
        "auth_type": company.get("auth_type"),
    })


async def templates_route(request: Request) -> JSONResponse:
    """GET /api/templates — list available team templates."""
    templates = {
        name: get_template_info(name)
        for name in ("solo", "standard", "full")
    }
    return JSONResponse({"templates": templates})


routes = [
    Route("/api/templates", templates_route, methods=["GET"]),
    Route("/api/companies", list_companies_route, methods=["GET"]),
    Route("/api/companies", create_company_route, methods=["POST"]),
    Route("/api/companies/{id}", get_company_route, methods=["GET"]),
    Route("/api/companies/{id}", update_company_route, methods=["PATCH"]),
    Route("/api/companies/{id}", delete_company_route, methods=["DELETE"]),
    Route("/api/companies/{id}/start", start_route, methods=["POST"]),
    Route("/api/companies/{id}/stop", stop_route, methods=["POST"]),
    Route("/api/companies/{id}/pause", pause_route, methods=["POST"]),
    Route("/api/companies/{id}/resume", resume_route, methods=["POST"]),
    Route("/api/companies/{id}/status", status_route, methods=["GET"]),
    Route("/api/companies/{id}/logs", logs_route, methods=["GET"]),
    Route("/api/companies/{id}/auth", update_auth_route, methods=["PUT"]),
    Route("/api/companies/{id}/auth/status", auth_status_route, methods=["GET"]),
]
