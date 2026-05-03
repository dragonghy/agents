#!/usr/bin/env python
"""Live multi-agent orchestration demo.

What this does:

1. Sets up an isolated environment (temp SQLite DBs, the live ``profiles/``
   directory at the repo root).
2. Creates a fake-but-believable ticket about a slow query needing a DB
   index. The ticket id is offset (999100) so it can't collide with
   anything in a real Leantime DB.
3. Spawns a real TPM session via :class:`SessionManager`. The TPM has the
   four orchestration tools wired in via the in-process MCP server built
   by :mod:`orchestration_tools`.
4. Sends the TPM a kickoff prompt that frames the problem.
5. Watches the TPM's tool calls. Each tool call creates / wakes a real
   subagent session (Architect, Developer, etc.) using the live Claude
   Agent SDK.
6. Logs every tool call + every subagent first-response to a transcript
   file.
7. Captures total tokens + estimated cost.

Why isolated DBs: this is a demo, not a daemon-side run. We don't want
the demo to mutate the real ``.agents-tasks.db`` / ``.agents-mcp.db`` —
the SQLiteTaskClient happily creates the schema on the fly when pointed
at a tmp file.

Why real LLM calls: the whole point of Phase 2.5 is to verify the SDK's
tool-use surface actually wires through. Mocked calls already passed in
the unit tests; this demo answers "does the TPM, when given the four
tools, actually use them?"

Cost budget: ~$1-2. The TPM uses Sonnet and may take 3-6 turns; each
subagent first-response is one turn. If anything goes wildly off-budget,
the script aborts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Allow running the script from anywhere — resolve the repo root and add
# the package src to sys.path.
HERE = Path(__file__).resolve().parent
SERVICES_DIR = HERE.parent
PKG_SRC = SERVICES_DIR / "src"
REPO_ROOT = SERVICES_DIR.parent.parent
sys.path.insert(0, str(PKG_SRC))

from agents_mcp.orchestration_session_manager import SessionManager  # noqa: E402
from agents_mcp.sqlite_task_client import SQLiteTaskClient  # noqa: E402
from agents_mcp.store import AgentStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("orchestration_demo")

# Quiet down very chatty SDK loggers during the demo.
logging.getLogger("claude_agent_sdk").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

DEMO_TICKET_ID = 999100
DEMO_TICKET_HEADLINE = (
    "Add index on orders.user_id to fix slow OrderHistoryView query"
)
DEMO_TICKET_DESCRIPTION = (
    "The OrderHistoryView page is loading in 3-4 seconds for users with "
    "more than ~500 orders. Profiling shows the query "
    "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 50 "
    "is doing a full table scan. We probably need an index, but want a "
    "second pair of eyes before shipping."
)
DEMO_KICKOFF_COMMENT = (
    "Investigate this slow query and propose a fix. The slow query is:\n"
    "    SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 50\n"
    "The orders table has ~5M rows. Decide whether an index is the right "
    "fix, design it if so, and report back via a ticket comment."
)

# Approximate 4.5/4.6 Sonnet pricing as of Q2 2026 (USD per 1M tokens).
# This is for a rough cost estimate in the transcript; not load-bearing.
SONNET_INPUT_PER_M = 3.00
SONNET_OUTPUT_PER_M = 15.00


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in * SONNET_INPUT_PER_M / 1_000_000
        + tokens_out * SONNET_OUTPUT_PER_M / 1_000_000
    )


def truncate(text: str, n: int = 600) -> str:
    if len(text) <= n:
        return text
    return text[:n] + f"... [+{len(text) - n} chars]"


async def _ensure_ticket(
    task_client: SQLiteTaskClient, ticket_id: int
) -> None:
    """Force-create a row at the requested id.

    The SQLiteTaskClient's ``create_ticket`` auto-assigns rowids; we want
    a known id (999100) so the demo's tool-call args are predictable. We
    insert directly via the same SQLite connection it's using.
    """
    db = await task_client._get_db()  # noqa: SLF001 — demo only
    # If a row with this id exists already, leave it alone.
    async with db.execute(
        "SELECT id FROM tickets WHERE id = ?", (ticket_id,)
    ) as cur:
        existing = await cur.fetchone()
    if existing:
        logger.info("ticket %s already exists; reusing", ticket_id)
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    await db.execute(
        "INSERT INTO tickets "
        "(id, headline, description, projectId, userId, date, status, "
        " workspace_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticket_id,
            DEMO_TICKET_HEADLINE,
            DEMO_TICKET_DESCRIPTION,
            task_client.project_id,
            1,
            now,
            4,  # In Progress
            1,  # work workspace
        ),
    )
    await db.commit()
    logger.info("seeded demo ticket %s", ticket_id)


async def run_demo(
    *, transcript_path: Path, max_turns: int = 8
) -> dict[str, Any]:
    """Run the live demo. Returns a dict suitable for json.dumps."""
    profiles_dir = REPO_ROOT / "profiles"
    if not profiles_dir.is_dir():
        raise RuntimeError(
            f"profiles dir not found: {profiles_dir} — script run from "
            "wrong location?"
        )

    tmpdir = Path(tempfile.mkdtemp(prefix="orch-demo-"))
    logger.info("demo workspace: %s", tmpdir)
    tasks_db = str(tmpdir / "tasks.db")
    agents_db = str(tmpdir / "agents.db")

    # Set up the two stores.
    store = AgentStore(agents_db)
    await store.initialize()
    task_client = SQLiteTaskClient(db_path=tasks_db, project_id=999)

    # Seed the demo ticket.
    await _ensure_ticket(task_client, DEMO_TICKET_ID)

    mgr = SessionManager(store, profiles_dir, task_client=task_client)

    # Spawn the TPM.
    tpm_row = await mgr.spawn(
        profile_name="tpm",
        binding_kind="ticket-subagent",
        ticket_id=DEMO_TICKET_ID,
    )
    tpm_session_id = tpm_row["id"]
    logger.info("TPM session spawned: %s", tpm_session_id)

    transcript: dict[str, Any] = {
        "ticket": {
            "id": DEMO_TICKET_ID,
            "headline": DEMO_TICKET_HEADLINE,
            "description": DEMO_TICKET_DESCRIPTION,
        },
        "tpm_session_id": tpm_session_id,
        "turns": [],
        "totals": {
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "tpm_turns": 0,
        },
        "final_state": {},
    }

    # Drive the TPM up to ``max_turns`` times. We feed in the kickoff
    # prompt as the first turn; subsequent turns feed back the prior
    # assistant text as a follow-up so the TPM keeps making progress.
    # The TPM may decide to stop on its own (e.g. by closing the ticket
    # then producing a short text reply); we detect that via the final
    # ticket status post-loop.

    next_message = DEMO_KICKOFF_COMMENT

    for turn_idx in range(max_turns):
        logger.info(
            "TPM turn %d: sending message (%d chars)",
            turn_idx + 1,
            len(next_message),
        )
        result = await mgr.append_message(tpm_session_id, next_message)
        transcript["turns"].append(
            {
                "kind": "tpm",
                "turn": turn_idx + 1,
                "user_input": truncate(next_message, 800),
                "assistant_text": truncate(result.assistant_text, 4000),
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
            }
        )
        transcript["totals"]["tokens_in"] += result.tokens_in
        transcript["totals"]["tokens_out"] += result.tokens_out
        transcript["totals"]["tpm_turns"] = turn_idx + 1

        logger.info(
            "TPM turn %d complete: tokens_in=%d tokens_out=%d, "
            "assistant text length=%d",
            turn_idx + 1,
            result.tokens_in,
            result.tokens_out,
            len(result.assistant_text),
        )

        # Inspect the ticket: if it's closed (status 0) or archived (-1),
        # the TPM has terminated the work and we can stop.
        async with (await task_client._get_db()).execute(  # noqa: SLF001
            "SELECT status FROM tickets WHERE id = ?", (DEMO_TICKET_ID,)
        ) as cur:
            row = await cur.fetchone()
        current_status = row["status"] if row else None
        logger.info(
            "ticket %s status=%s after TPM turn %d",
            DEMO_TICKET_ID,
            current_status,
            turn_idx + 1,
        )
        if current_status in (0, -1):
            logger.info("ticket reached terminal status %s; stopping", current_status)
            break

        # Continue: nudge the TPM to keep going. We send a generic "what's
        # next?" follow-up so the TPM has to either call another tool or
        # explicitly mark the ticket terminal.
        next_message = (
            "Update: I see your previous response. What's the next "
            "concrete tool call? If the work is done, close the ticket. "
            "If you're waiting on something, post a comment explaining "
            "what and mark the ticket Blocked. Otherwise, keep coordinating."
        )

    # Pull final ticket state + comments.
    async with (await task_client._get_db()).execute(  # noqa: SLF001
        "SELECT id, headline, status FROM tickets WHERE id = ?",
        (DEMO_TICKET_ID,),
    ) as cur:
        row = await cur.fetchone()
    final_ticket_status = row["status"] if row else None

    comments_resp = await task_client.get_comments(
        "ticket", DEMO_TICKET_ID, limit=0
    )
    comments = comments_resp.get("comments", []) if isinstance(comments_resp, dict) else comments_resp
    transcript["final_state"] = {
        "ticket_status": final_ticket_status,
        "comment_count": len(comments),
        "comments": [
            {
                "id": c.get("id"),
                "author": c.get("author"),
                "text": truncate(c.get("text", ""), 800),
            }
            for c in comments
        ],
    }

    # List all subagent sessions on this ticket. We filter to ones whose
    # parent_session_id matches the TPM (i.e. spawned by THIS TPM via
    # the spawn_subagent tool, not the TPM itself).
    all_ticket_sessions = await store.list_sessions(ticket_id=DEMO_TICKET_ID)
    subagent_rows = [
        r for r in all_ticket_sessions
        if r.get("parent_session_id") == tpm_session_id
    ]
    transcript["subagent_sessions"] = [
        {
            "id": r["id"],
            "profile": r["profile_name"],
            "status": r["status"],
            "tokens_in": r["cost_tokens_in"],
            "tokens_out": r["cost_tokens_out"],
        }
        for r in subagent_rows
    ]
    for sub in subagent_rows:
        transcript["totals"]["tokens_in"] += sub["cost_tokens_in"]
        transcript["totals"]["tokens_out"] += sub["cost_tokens_out"]

    transcript["totals"]["cost_usd"] = estimate_cost(
        transcript["totals"]["tokens_in"],
        transcript["totals"]["tokens_out"],
    )

    logger.info(
        "demo finished: tpm_turns=%d total_tokens_in=%d total_tokens_out=%d "
        "estimated_cost=$%.4f",
        transcript["totals"]["tpm_turns"],
        transcript["totals"]["tokens_in"],
        transcript["totals"]["tokens_out"],
        transcript["totals"]["cost_usd"],
    )

    # Write the transcript file.
    transcript_md = render_transcript_markdown(transcript)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(transcript_md, encoding="utf-8")
    logger.info("transcript written to %s", transcript_path)

    # Also write a sibling JSON for machine consumption.
    json_path = transcript_path.with_suffix(".json")
    json_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    logger.info("raw transcript written to %s", json_path)

    return transcript


def render_transcript_markdown(transcript: dict) -> str:
    """Pretty-print the transcript as a markdown report."""
    out: list[str] = []
    t = transcript
    out.append("# Orchestration v1 — Multi-Agent Demo Transcript")
    out.append("")
    out.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M %Z')}")
    out.append(f"**TPM session**: `{t['tpm_session_id']}`")
    out.append("")
    out.append("## Scenario")
    out.append("")
    out.append(f"- **Ticket ID**: {t['ticket']['id']} (synthetic — not in production Leantime)")
    out.append(f"- **Headline**: {t['ticket']['headline']}")
    out.append("")
    out.append("```")
    out.append(t["ticket"]["description"])
    out.append("```")
    out.append("")
    out.append(f"## Totals")
    out.append("")
    out.append(f"- **TPM turns**: {t['totals']['tpm_turns']}")
    out.append(
        f"- **Tokens in**: {t['totals']['tokens_in']:,} "
        f"(includes cache reads)"
    )
    out.append(f"- **Tokens out**: {t['totals']['tokens_out']:,}")
    out.append(
        f"- **Estimated cost**: ${t['totals']['cost_usd']:.4f} USD "
        f"(at Sonnet $3 in / $15 out per 1M)"
    )
    out.append("")
    out.append("## Subagent sessions spawned by TPM")
    out.append("")
    if not t["subagent_sessions"]:
        out.append("_(none — TPM did not spawn any subagents)_")
    else:
        out.append("| Session | Profile | Status | Tokens in | Tokens out |")
        out.append("|---|---|---|---|---|")
        for s in t["subagent_sessions"]:
            out.append(
                f"| `{s['id']}` | {s['profile']} | {s['status']} | "
                f"{s['tokens_in']:,} | {s['tokens_out']:,} |"
            )
    out.append("")
    out.append("## TPM turn-by-turn")
    out.append("")
    for turn in t["turns"]:
        out.append(f"### Turn {turn['turn']}")
        out.append("")
        out.append("**User input:**")
        out.append("")
        out.append("```")
        out.append(turn["user_input"])
        out.append("```")
        out.append("")
        out.append("**TPM assistant text:**")
        out.append("")
        out.append("```")
        out.append(turn["assistant_text"])
        out.append("```")
        out.append("")
        out.append(
            f"_Tokens: in={turn['tokens_in']:,} out={turn['tokens_out']:,}_"
        )
        out.append("")
    out.append("## Final ticket state")
    out.append("")
    out.append(f"- **Status**: {t['final_state']['ticket_status']}")
    out.append(f"- **Comments posted**: {t['final_state']['comment_count']}")
    out.append("")
    if t["final_state"]["comments"]:
        out.append("### Comments")
        out.append("")
        for i, c in enumerate(t["final_state"]["comments"], 1):
            out.append(f"**{i}. comment_id={c['id']}** (author=`{c['author']}`)")
            out.append("")
            out.append("```")
            out.append(c["text"])
            out.append("```")
            out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcript",
        default=str(
            REPO_ROOT
            / "projects/agent-hub/research/"
            "orchestration-v1-multi-agent-demo-2026-05-02.md"
        ),
        help="Where to write the transcript markdown.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=8,
        help="Maximum TPM turns before giving up.",
    )
    args = parser.parse_args()

    # The Claude Agent SDK runs `claude` as a subprocess which transparently
    # picks up auth from (in priority order) ANTHROPIC_API_KEY,
    # ~/.claude/.credentials.json, or the macOS keychain entry the
    # ``claude login`` command writes. We just sanity-check that at least
    # one of those is present; the actual auth is the SDK's problem.
    import shutil

    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_creds_file = os.path.exists(
        os.path.expanduser("~/.claude/.credentials.json")
    )
    has_claude_cli = shutil.which("claude") is not None
    if not (has_api_key or has_creds_file or has_claude_cli):
        logger.error(
            "no ANTHROPIC_API_KEY, ~/.claude/.credentials.json, or "
            "`claude` CLI on PATH — live demo cannot authenticate"
        )
        sys.exit(2)

    transcript_path = Path(args.transcript).expanduser().resolve()
    asyncio.run(
        run_demo(
            transcript_path=transcript_path,
            max_turns=args.max_turns,
        )
    )


if __name__ == "__main__":
    main()
