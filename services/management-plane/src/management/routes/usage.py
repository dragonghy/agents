"""Usage tracking + Billing API routes."""

import json
import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..auth import get_current_user
from ..billing import STRIPE_ENABLED, get_plan_info, list_plans
from ..models import (
    get_usage,
    get_usage_summary,
    record_usage,
    verify_company_ownership,
)

# Shared secret for instance daemon → management plane usage reporting
USAGE_API_SECRET = os.environ.get("MGMT_USAGE_SECRET", "dev-usage-secret")


def _require_auth(handler):
    """Decorator that injects user_id from JWT."""
    async def wrapper(request: Request) -> JSONResponse:
        payload = await get_current_user(request)
        if not payload:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        request.state.user_id = payload["sub"]
        return await handler(request)
    return wrapper


async def _get_owned_company(request: Request):
    """Get company owned by current user."""
    company_id = request.path_params["id"]
    company = await verify_company_ownership(company_id, request.state.user_id)
    if not company:
        return None, JSONResponse({"error": "Company not found"}, status_code=404)
    return company, None


# ── Usage API ──


@_require_auth
async def get_usage_route(request: Request) -> JSONResponse:
    """GET /api/companies/:id/usage — get usage data with optional date filtering."""
    company, err = await _get_owned_company(request)
    if err:
        return err

    date_from = request.query_params.get("from")
    date_to = request.query_params.get("to")

    records = await get_usage(company["id"], date_from=date_from, date_to=date_to)
    summary = await get_usage_summary(company["id"], date_from=date_from, date_to=date_to)

    return JSONResponse({
        "records": records,
        "summary": summary,
    })


async def report_usage_route(request: Request) -> JSONResponse:
    """POST /api/companies/:id/usage — record usage (called by instance daemon).

    Authentication: uses a shared secret in X-Usage-Secret header.
    """
    # Verify shared secret
    secret = request.headers.get("x-usage-secret", "")
    if secret != USAGE_API_SECRET:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    company_id = request.path_params["id"]

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    date = body.get("date", "")
    input_tokens = body.get("input_tokens", 0)
    output_tokens = body.get("output_tokens", 0)
    model = body.get("model", "")

    if not date:
        return JSONResponse({"error": "date is required (YYYY-MM-DD)"}, status_code=400)

    record_id = await record_usage(
        company_id=company_id,
        date=date,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )

    return JSONResponse({"id": record_id, "recorded": True}, status_code=201)


# ── Billing API ──


@_require_auth
async def get_billing_route(request: Request) -> JSONResponse:
    """GET /api/companies/:id/billing — get billing info."""
    company, err = await _get_owned_company(request)
    if err:
        return err

    plan = get_plan_info("free_beta")
    summary = await get_usage_summary(company["id"])

    return JSONResponse({
        "plan": {**plan, "id": "free_beta"},
        "stripe_enabled": STRIPE_ENABLED,
        "usage_summary": {
            "total_tokens": summary["total_tokens"],
            "total_input": summary["total_input"],
            "total_output": summary["total_output"],
        },
    })


async def list_plans_route(request: Request) -> JSONResponse:
    """GET /api/plans — list available plans."""
    return JSONResponse({"plans": list_plans()})


routes = [
    Route("/api/companies/{id}/usage", get_usage_route, methods=["GET"]),
    Route("/api/companies/{id}/usage", report_usage_route, methods=["POST"]),
    Route("/api/companies/{id}/billing", get_billing_route, methods=["GET"]),
    Route("/api/plans", list_plans_route, methods=["GET"]),
]
