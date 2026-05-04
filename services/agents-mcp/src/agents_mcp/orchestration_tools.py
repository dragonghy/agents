"""In-process MCP tool server bound to a TPM session.

Phase 2.5 (Task: TPM tool-use bindings) — gives the TPM Profile concrete
tools so it can actually coordinate, not just describe coordination in
plain text. Today the TPM has a system prompt but no callable surface; if
it decides "I should spawn an Architect", the only thing it can do is
write that sentence back. After this module lands, a TPM session is run
with an in-process MCP server that exposes four tools:

- ``spawn_subagent`` — create a new subagent session bound to this ticket
- ``push_message`` — send a follow-up message into an existing subagent
- ``post_comment`` — post a ticket comment (visible to all subscribers)
- ``mark_ticket_status`` — close / block / re-open the ticket

Why in-process (vs stdio MCP subprocess): the SDK's
``create_sdk_mcp_server`` runs the server inside the same Python process
as the daemon, which gives the tool handlers direct access to the live
``SessionManager`` + ``AgentStore`` + Leantime client. No serialization,
no subprocess lifecycle, no port allocation. The four tools all need to
mutate orchestration state owned by the daemon — the in-process path is
strictly simpler.

The server is constructed *per TPM session* via :func:`build_tpm_tool_server`
because each TPM is bound to one ticket and we want the tool handlers to
close over that ticket-id + the spawning TPM's session id (so subagents
spawned by this TPM are correctly tagged with ``parent_session_id``).

Notes on the tool surface:

- All four tools take ``ticket_id`` as an explicit argument (see design
  doc §2.4 — explicit beats implicit when the LLM is reading a long
  conversation log). The TPM's system prompt tells it which ticket it's
  on, and we keep validation cheap: we don't enforce that the
  TPM-passed ticket_id matches its bound ticket. The TPM is allowed
  to read other tickets' comments via the agents MCP if it needs to
  cross-reference, and could theoretically post a comment on a sibling
  ticket if needed. v1 is permissive; we can tighten in a later phase
  if it's abused.

- ``spawn_subagent`` does NOT block until the subagent finishes — it
  returns the subagent's session id plus its first response. This matches
  the design intent where TPM coordinates by sequencing turns; the
  alternative (fire-and-forget with a callback) was considered and
  rejected for v1 because TPM needs the first response to decide what
  to do next.

- All tools return MCP-shaped ``{"content": [{"type": "text", "text": ...}]}``
  dicts (see SDK docs / ``__init__.py`` ``call_tool`` adapter). On
  application errors we return ``"is_error": True`` rather than raising
  so the TPM gets a structured error message it can reason about,
  not an opaque tool-failure.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import create_sdk_mcp_server, tool

if TYPE_CHECKING:
    from .orchestration_session_manager import SessionManager
    from .sqlite_task_client import SQLiteTaskClient
    from .store import AgentStore

logger = logging.getLogger(__name__)


# Allowed status codes for ``mark_ticket_status``. Mirrors the canonical
# set documented in CLAUDE.md ("Ticket Status Codes"). Status 2 is
# explicitly rejected because the codebase forbids it.
_VALID_STATUSES = frozenset({-1, 0, 1, 3, 4})


def _ok(text: str) -> dict[str, Any]:
    """Build a successful MCP tool response with the given text."""
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> dict[str, Any]:
    """Build an error MCP tool response — TPM sees ``is_error: True``."""
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def build_tpm_tool_server(
    *,
    session_manager: "SessionManager",
    store: "AgentStore",
    task_client: "SQLiteTaskClient",
    parent_session_id: str,
    bound_ticket_id: int,
):
    """Build an in-process MCP server bound to one TPM session.

    The returned object is the SDK's ``McpSdkServerConfig`` (a TypedDict
    with ``type``, ``name``, ``instance``). Callers (the SessionManager →
    Adapter path) pass it to ``ClaudeAgentOptions(mcp_servers={...})``.

    Args:
        session_manager: Used by ``spawn_subagent`` and ``push_message``
            to actually create / wake subagent sessions.
        store: Used directly by some tool handlers when they need session
            metadata (e.g. ``push_message`` validates the session exists).
        task_client: Leantime client wrapper. Used by ``post_comment`` and
            ``mark_ticket_status`` for ticket-level mutations.
        parent_session_id: The TPM's own session id. Subagents spawned
            via ``spawn_subagent`` are tagged with this as their
            ``parent_session_id`` so the per-ticket session tree is
            correctly rooted at the TPM.
        bound_ticket_id: The ticket this TPM coordinates. Mainly carried
            for logging and for the tool server's ``name`` (helps
            debugging when multiple TPMs run concurrently).

    Returns:
        ``McpSdkServerConfig`` dict ready to be passed to
        ``ClaudeAgentOptions.mcp_servers``.
    """

    # Capture references in closures. These are async helpers; the actual
    # tool handlers (decorated below) are also async.

    @tool(
        "spawn_subagent",
        (
            "Spawn a new subagent session bound to a ticket and immediately "
            "send it an initial prompt. Returns the subagent's session_id "
            "plus the assistant text from its first response so you can "
            "decide what to do next without a follow-up turn. Use this when "
            "the ticket needs work that is outside your role (you do not "
            "implement code, run tests, or analyze a database directly — "
            "you delegate to a subagent with the right Profile)."
        ),
        {
            "profile_name": str,
            "initial_prompt": str,
            "ticket_id": int,
        },
    )
    async def spawn_subagent(args: dict[str, Any]) -> dict[str, Any]:
        profile_name = args["profile_name"]
        initial_prompt = args["initial_prompt"]
        ticket_id = int(args["ticket_id"])

        try:
            row = await session_manager.spawn(
                profile_name=profile_name,
                binding_kind="ticket-subagent",
                ticket_id=ticket_id,
                parent_session_id=parent_session_id,
            )
        except FileNotFoundError as exc:
            return _err(
                f"spawn_subagent: profile {profile_name!r} not found: {exc}"
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception(
                "spawn_subagent: failed to spawn (profile=%s ticket=%s)",
                profile_name,
                ticket_id,
            )
            return _err(f"spawn_subagent: spawn failed: {exc}")

        new_session_id = row["id"]
        try:
            result = await session_manager.append_message(
                new_session_id, initial_prompt
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception(
                "spawn_subagent: first turn failed (session=%s)", new_session_id
            )
            return _err(
                f"spawn_subagent: session {new_session_id} created but "
                f"first turn failed: {exc}"
            )

        payload = {
            "session_id": new_session_id,
            "profile": profile_name,
            "first_response": result.assistant_text,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
        }
        return _ok(json.dumps(payload, indent=2))

    @tool(
        "push_message",
        (
            "Push a follow-up user message into an existing subagent session "
            "and return its assistant reply. Use this when a subagent posed "
            "a question, when its previous output left a clear next step, "
            "or when you need to redirect its work. Does not create a new "
            "session — pass the session_id returned by spawn_subagent."
        ),
        {
            "session_id": str,
            "body": str,
        },
    )
    async def push_message(args: dict[str, Any]) -> dict[str, Any]:
        sid = args["session_id"]
        body = args["body"]
        try:
            result = await session_manager.append_message(sid, body)
        except LookupError:
            return _err(f"push_message: unknown session_id {sid!r}")
        except RuntimeError as exc:
            return _err(f"push_message: {exc}")
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("push_message: failed (session=%s)", sid)
            return _err(f"push_message: {exc}")

        payload = {
            "session_id": sid,
            "response": result.assistant_text,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
        }
        return _ok(json.dumps(payload, indent=2))

    @tool(
        "post_comment",
        (
            "Post a comment on a ticket. Visible to every subscriber, "
            "including Human and any other subagents on the ticket. Use this "
            "for status updates, decisions you've made, summaries of subagent "
            "output, or escalations to Human. Returns the new comment id."
        ),
        {
            "ticket_id": int,
            "body": str,
        },
    )
    async def post_comment(args: dict[str, Any]) -> dict[str, Any]:
        ticket_id = int(args["ticket_id"])
        body = args["body"]
        try:
            comment_id = await task_client.add_comment(
                "ticket",
                ticket_id,
                body,
                author=f"tpm:{parent_session_id}",
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception(
                "post_comment: failed (ticket=%s)", ticket_id
            )
            return _err(f"post_comment: {exc}")

        return _ok(
            json.dumps(
                {
                    "ticket_id": ticket_id,
                    "comment_id": comment_id,
                    "ok": True,
                },
                indent=2,
            )
        )

    @tool(
        "mark_ticket_status",
        (
            "Update a ticket's status code. Allowed values: 0=Done, "
            "1=Blocked, 3=New, 4=In Progress, -1=Archived. Use 0 to close "
            "a ticket whose work is verified complete; use 1 when waiting "
            "on an external blocker. Status 2 is forbidden in this codebase "
            "and will be rejected."
        ),
        {
            "ticket_id": int,
            "status": int,
        },
    )
    async def mark_ticket_status(args: dict[str, Any]) -> dict[str, Any]:
        ticket_id = int(args["ticket_id"])
        status = int(args["status"])
        if status not in _VALID_STATUSES:
            return _err(
                f"mark_ticket_status: status {status} is not allowed; "
                f"valid values are {sorted(_VALID_STATUSES)} "
                f"(2 is reserved and unused)"
            )
        try:
            await task_client.update_ticket(ticket_id, status=status)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception(
                "mark_ticket_status: failed (ticket=%s status=%s)",
                ticket_id,
                status,
            )
            return _err(f"mark_ticket_status: {exc}")

        # Orchestration v1: TPM auto-close on terminal status. The MCP /
        # PATCH ticket-update paths call ``maybe_close_tpm_for_status_change``
        # for us; this tool bypasses both (writes directly through
        # ``task_client.update_ticket``) so it has to invoke the hook
        # itself, otherwise a TPM that closes its own ticket via this tool
        # would stay alive forever (ticket #35 / dogfood findings #24).
        # The hook is a no-op for non-terminal statuses, so we always call
        # it — keeps the code path simple and matches the helper's
        # idempotency contract. Failures are caught + logged so they
        # never poison the primary update return value.
        try:
            from .orchestration_tpm_dispatch import (
                maybe_close_tpm_for_status_change,
            )

            await maybe_close_tpm_for_status_change(
                store, ticket_id=ticket_id, new_status=status
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "mark_ticket_status: TPM auto-close hook failed "
                "(ticket=%s status=%s); update succeeded, hook is "
                "best-effort",
                ticket_id,
                status,
            )

        return _ok(
            json.dumps(
                {"ticket_id": ticket_id, "status": status, "ok": True},
                indent=2,
            )
        )

    server = create_sdk_mcp_server(
        name=f"orchestration_tpm_{bound_ticket_id}",
        version="1.0.0",
        tools=[
            spawn_subagent,
            push_message,
            post_comment,
            mark_ticket_status,
        ],
    )
    logger.info(
        "orchestration_tools: built tool server for TPM session %s "
        "(ticket=%s)",
        parent_session_id,
        bound_ticket_id,
    )
    return server


# Tool names exposed by build_tpm_tool_server. Used by the Adapter to
# build an ``allowed_tools`` list when the SDK requires explicit
# allow-listing of MCP tools.
TPM_TOOL_NAMES: tuple[str, ...] = (
    "spawn_subagent",
    "push_message",
    "post_comment",
    "mark_ticket_status",
)


__all__ = [
    "TPM_TOOL_NAMES",
    "build_tpm_tool_server",
]
