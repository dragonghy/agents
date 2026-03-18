"""Auth API routes: register, login, logout, me."""

import json
import re

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..auth import create_token, get_current_user, hash_password, verify_password
from ..models import create_user, get_user_by_email, get_user_by_id
from ..security import auth_limiter

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get_client_ip(request: Request) -> str:
    """Get client IP for rate limiting."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def register(request: Request) -> JSONResponse:
    """POST /api/auth/register"""
    if not auth_limiter.is_allowed(_get_client_ip(request)):
        return JSONResponse({"error": "Too many requests"}, status_code=429)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    name = (body.get("name") or "").strip() or None

    # Validation
    if not email or not EMAIL_RE.match(email):
        return JSONResponse({"error": "Invalid email address"}, status_code=400)
    if len(password) < 8:
        return JSONResponse(
            {"error": "Password must be at least 8 characters"}, status_code=400
        )

    # Check if email already exists
    existing = await get_user_by_email(email)
    if existing:
        return JSONResponse({"error": "Email already registered"}, status_code=409)

    # Create user
    password_hash = hash_password(password)
    user = await create_user(email, password_hash, name)

    # Auto-login: return JWT
    token = create_token(user["id"], user["email"])
    return JSONResponse(
        {"user": user, "token": token},
        status_code=201,
    )


async def login(request: Request) -> JSONResponse:
    """POST /api/auth/login"""
    if not auth_limiter.is_allowed(_get_client_ip(request)):
        return JSONResponse({"error": "Too many requests"}, status_code=429)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return JSONResponse({"error": "Email and password required"}, status_code=400)

    user = await get_user_by_email(email)
    if not user or not verify_password(password, user["password"]):
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)

    token = create_token(user["id"], user["email"])
    return JSONResponse({
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
        },
        "token": token,
    })


async def logout(request: Request) -> JSONResponse:
    """POST /api/auth/logout — stateless JWT, just acknowledge."""
    return JSONResponse({"ok": True})


async def me(request: Request) -> JSONResponse:
    """GET /api/auth/me — get current user info."""
    payload = await get_current_user(request)
    if not payload:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    user = await get_user_by_id(payload["sub"])
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    return JSONResponse({"user": user})


routes = [
    Route("/api/auth/register", register, methods=["POST"]),
    Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/auth/me", me, methods=["GET"]),
]
