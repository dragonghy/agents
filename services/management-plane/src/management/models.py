"""Data models and database operations."""

import json
import re
import uuid
from datetime import datetime

from .db import get_db


# ── User operations ──


async def create_user(email: str, password_hash: str, name: str | None = None) -> dict:
    """Create a new user. Returns the created user dict."""
    user_id = str(uuid.uuid4())
    db = await get_db()
    await db.execute(
        "INSERT INTO users (id, email, password, name) VALUES (?, ?, ?, ?)",
        (user_id, email, password_hash, name),
    )
    await db.commit()
    return {"id": user_id, "email": email, "name": name}


async def get_user_by_email(email: str) -> dict | None:
    """Get user by email. Returns dict with id, email, password, name."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, email, password, name, created_at FROM users WHERE email = ?",
        (email,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def get_user_by_id(user_id: str) -> dict | None:
    """Get user by ID. Returns dict without password."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, email, name, created_at FROM users WHERE id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


# ── Company operations ──


def _slugify(name: str) -> str:
    """Generate a URL-friendly slug from a company name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "company"


async def create_company(
    user_id: str,
    name: str,
    slug: str | None = None,
    template: str = "standard",
    auth_type: str | None = None,
    auth_token: str | None = None,
    config: dict | None = None,
) -> dict:
    """Create a new company. Returns the created company dict."""
    company_id = str(uuid.uuid4())
    if not slug:
        slug = _slugify(name)

    # Ensure slug uniqueness
    db = await get_db()
    base_slug = slug
    counter = 1
    while True:
        cursor = await db.execute("SELECT id FROM companies WHERE slug = ?", (slug,))
        if await cursor.fetchone() is None:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    config_json = json.dumps(config) if config else None

    await db.execute(
        """INSERT INTO companies
        (id, user_id, name, slug, template, auth_type, auth_token, config, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'creating')""",
        (company_id, user_id, name, slug, template, auth_type, auth_token, config_json),
    )
    await db.commit()

    # Log creation event
    await log_event(company_id, "created", {"template": template})

    return await get_company(company_id)


async def get_company(company_id: str) -> dict | None:
    """Get company by ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    result = dict(row)
    # Parse config JSON
    if result.get("config"):
        try:
            result["config"] = json.loads(result["config"])
        except json.JSONDecodeError:
            pass
    # Never expose auth_token in API responses
    result.pop("auth_token", None)
    return result


async def list_companies(user_id: str) -> list[dict]:
    """List all companies for a user."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM companies WHERE user_id = ? AND status != 'deleted' ORDER BY created_at DESC",
        (user_id,),
    )
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        r = dict(row)
        if r.get("config"):
            try:
                r["config"] = json.loads(r["config"])
            except json.JSONDecodeError:
                pass
        r.pop("auth_token", None)
        results.append(r)
    return results


async def update_company(company_id: str, **fields) -> dict | None:
    """Update company fields. Returns updated company."""
    if not fields:
        return await get_company(company_id)

    db = await get_db()

    # Handle config serialization
    if "config" in fields and isinstance(fields["config"], dict):
        fields["config"] = json.dumps(fields["config"])

    fields["updated_at"] = datetime.utcnow().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [company_id]

    await db.execute(
        f"UPDATE companies SET {set_clause} WHERE id = ?", values
    )
    await db.commit()
    return await get_company(company_id)


async def delete_company(company_id: str) -> bool:
    """Soft-delete a company."""
    db = await get_db()
    await db.execute(
        "UPDATE companies SET status = 'deleted', updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), company_id),
    )
    await db.commit()
    await log_event(company_id, "deleted")
    return True


async def verify_company_ownership(company_id: str, user_id: str) -> dict | None:
    """Get company only if owned by user. Returns None if not found or not owned."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM companies WHERE id = ? AND user_id = ?",
        (company_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    result = dict(row)
    if result.get("config"):
        try:
            result["config"] = json.loads(result["config"])
        except json.JSONDecodeError:
            pass
    result.pop("auth_token", None)
    return result


# ── Instance events ──


async def log_event(company_id: str, event_type: str, details: dict | None = None):
    """Log an instance lifecycle event."""
    db = await get_db()
    await db.execute(
        "INSERT INTO instance_events (company_id, event_type, details) VALUES (?, ?, ?)",
        (company_id, event_type, json.dumps(details) if details else None),
    )
    await db.commit()


async def get_events(company_id: str, limit: int = 50) -> list[dict]:
    """Get recent events for a company."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM instance_events WHERE company_id = ? ORDER BY created_at DESC LIMIT ?",
        (company_id, limit),
    )
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        r = dict(row)
        if r.get("details"):
            try:
                r["details"] = json.loads(r["details"])
            except json.JSONDecodeError:
                pass
        results.append(r)
    return results


# ── Token usage ──


async def record_usage(
    company_id: str,
    date: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str = "",
) -> int:
    """Record token usage for a company on a given date."""
    total = input_tokens + output_tokens
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO token_usage
        (company_id, date, input_tokens, output_tokens, total_tokens, model)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (company_id, date, input_tokens, output_tokens, total, model),
    )
    await db.commit()
    return cursor.lastrowid


async def get_usage(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Get token usage records, optionally filtered by date range."""
    db = await get_db()
    sql = "SELECT * FROM token_usage WHERE company_id = ?"
    params: list = [company_id]

    if date_from:
        sql += " AND date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date <= ?"
        params.append(date_to)

    sql += " ORDER BY date DESC, id DESC"

    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_usage_summary(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Get aggregated token usage summary for a company.

    If date_from/date_to are provided, filters all aggregations by the range.
    """
    db = await get_db()

    # Build date filter clause
    date_clause = ""
    date_params: list = []
    if date_from:
        date_clause += " AND date >= ?"
        date_params.append(date_from)
    if date_to:
        date_clause += " AND date <= ?"
        date_params.append(date_to)

    # Total usage
    cursor = await db.execute(
        f"""SELECT
            COALESCE(SUM(input_tokens), 0) as total_input,
            COALESCE(SUM(output_tokens), 0) as total_output,
            COALESCE(SUM(total_tokens), 0) as total_tokens
        FROM token_usage WHERE company_id = ?{date_clause}""",
        [company_id, *date_params],
    )
    row = await cursor.fetchone()
    totals = dict(row)

    # Daily breakdown (last 30 days or within range)
    cursor = await db.execute(
        f"""SELECT date,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens
        FROM token_usage
        WHERE company_id = ?{date_clause}
        GROUP BY date
        ORDER BY date DESC
        LIMIT 30""",
        [company_id, *date_params],
    )
    daily = [dict(r) for r in await cursor.fetchall()]

    # By model
    cursor = await db.execute(
        f"""SELECT model,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens
        FROM token_usage
        WHERE company_id = ? AND model != ''{date_clause}
        GROUP BY model
        ORDER BY total_tokens DESC""",
        [company_id, *date_params],
    )
    by_model = [dict(r) for r in await cursor.fetchall()]

    return {
        **totals,
        "daily": daily,
        "by_model": by_model,
    }


def format_tokens(count: int) -> str:
    """Format token count for display (e.g., 3200000 -> '3.2M')."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)
