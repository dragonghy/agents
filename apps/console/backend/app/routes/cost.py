"""Cost dashboard — aggregate token_usage_daily into today / 7d / lifetime USD."""

from datetime import date, timedelta

from fastapi import APIRouter

from app import db, pricing, repo

router = APIRouter(prefix="/cost", tags=["cost"])


def _row_cost(row: dict) -> float:
    return pricing.estimate_usd(
        row.get("input_tokens", 0) or 0,
        row.get("output_tokens", 0) or 0,
        row.get("cache_read_tokens", 0) or 0,
        row.get("cache_write_tokens", 0) or 0,
    )


@router.get("/summary")
async def cost_summary():
    today = date.today().isoformat()
    seven_days_ago = (date.today() - timedelta(days=6)).isoformat()

    rows = await db.fetch_all(
        repo.mcp_db_path(),
        "SELECT agent_id, date, model, input_tokens, output_tokens, "
        "cache_read_tokens, cache_write_tokens, message_count "
        "FROM token_usage_daily",
    )

    today_total = 0.0
    week_total = 0.0
    lifetime_total = 0.0
    today_in = today_out = 0
    lifetime_in = lifetime_out = 0
    by_agent: dict[str, dict] = {}

    for r in rows:
        cost = _row_cost(r)
        lifetime_total += cost
        lifetime_in += r["input_tokens"] or 0
        lifetime_out += r["output_tokens"] or 0
        if r["date"] == today:
            today_total += cost
            today_in += r["input_tokens"] or 0
            today_out += r["output_tokens"] or 0
        if r["date"] >= seven_days_ago:
            week_total += cost
        bucket = by_agent.setdefault(
            r["agent_id"],
            {
                "agent_id": r["agent_id"],
                "today_usd": 0.0,
                "week_usd": 0.0,
                "lifetime_usd": 0.0,
                "lifetime_messages": 0,
            },
        )
        bucket["lifetime_usd"] += cost
        bucket["lifetime_messages"] += r["message_count"] or 0
        if r["date"] == today:
            bucket["today_usd"] += cost
        if r["date"] >= seven_days_ago:
            bucket["week_usd"] += cost

    # Round per-agent
    for b in by_agent.values():
        b["today_usd"] = round(b["today_usd"], 4)
        b["week_usd"] = round(b["week_usd"], 4)
        b["lifetime_usd"] = round(b["lifetime_usd"], 4)

    top_today = sorted(
        by_agent.values(), key=lambda x: x["today_usd"], reverse=True
    )[:5]
    by_agent_sorted = sorted(
        by_agent.values(), key=lambda x: x["lifetime_usd"], reverse=True
    )

    return {
        "today_usd": round(today_total, 4),
        "week_usd": round(week_total, 4),
        "lifetime_usd": round(lifetime_total, 4),
        "today_input_tokens": today_in,
        "today_output_tokens": today_out,
        "lifetime_input_tokens": lifetime_in,
        "lifetime_output_tokens": lifetime_out,
        "top_today": top_today,
        "by_agent": by_agent_sorted,
        "pricing": {
            "input_per_million": pricing.INPUT_PER_M,
            "output_per_million": pricing.OUTPUT_PER_M,
            "cache_read_per_million": pricing.CACHE_READ_PER_M,
            "cache_write_per_million": pricing.CACHE_WRITE_PER_M,
            "note": "Sonnet rates; matches morning_brief.py for parity.",
        },
    }
