"""Comment-driven TPM dispatch for orchestration v1.

Comments are the only inter-session bus (see design §2.4). When a new
comment arrives on a ticket, the TPM for that ticket needs to "wake up"
and decide what to do next: post a status update, push a follow-up
message into a subagent, spawn a new subagent, or close the ticket.

This module provides the wake-up shim. It is intentionally narrow:

- Look up the active TPM for the ticket.
- Refuse to forward the TPM's own comments back into itself
  (self-feedback loop guard).
- Format a small wrapper around the comment metadata + body so the TPM's
  next turn has clear provenance.
- Hand the wrapped message to :meth:`SessionManager.append_message`.

The TPM's response is whatever its system prompt + tools dictate. We
don't reach into that here.

Wiring into the daemon's ``comment_created`` event stream is Phase 2.5
(out of scope here). For now this is a building block + tests.
"""

from __future__ import annotations

import logging
from typing import Optional

from .orchestration_session_manager import SessionManager
from .store import AgentStore

logger = logging.getLogger(__name__)


def _format_comment_for_tpm(
    *,
    ticket_id: int,
    comment_id: int,
    comment_body: str,
    author_session_id: Optional[str],
) -> str:
    """Wrap a comment in a small metadata header.

    The TPM should be able to tell at a glance which ticket, which
    comment id, and who authored it (so it can attribute follow-ups,
    avoid loops, and decide whether to escalate). The body is appended
    verbatim — TPM sees exactly what got posted.

    Author is shown as ``human`` when ``author_session_id`` is ``None``
    (Human-via-Web-UI / Telegram drop-ins post comments without a
    session id). Otherwise we show the session id verbatim.
    """
    author = author_session_id if author_session_id else "human"
    return (
        f"[New comment on ticket #{ticket_id}, comment_id={comment_id}, "
        f"author={author}]\n{comment_body}"
    )


async def dispatch_comment_to_tpm(
    session_manager: SessionManager,
    store: AgentStore,
    *,
    ticket_id: int,
    comment_id: int,
    comment_body: str,
    author_session_id: Optional[str],
) -> Optional[str]:
    """Forward a new comment into the TPM session for the same ticket.

    Three guard branches before the dispatch:

    1. **No active TPM**: log a warning and return ``None``. This can
       legitimately happen if a comment lands on a ticket before
       status=4 (i.e. before a TPM has been spawned), or after the
       ticket reached terminal status and the TPM was closed.
       Decision: do nothing. The comment is preserved on the ticket;
       a future TPM session will see it via ticket history when one is
       spawned.
    2. **Comment authored by the TPM itself**: skip — wakening the TPM
       on its own comment would create an infinite self-feedback loop.
       Returns ``None``.
    3. **Otherwise**: wrap the comment with provenance metadata and
       call :meth:`SessionManager.append_message`. Returns the TPM's
       session id.

    Args:
        session_manager: Used to push the wrapped message into the TPM
            session (which triggers one Adapter turn).
        store: Used to look up the active TPM.
        ticket_id: The ticket the comment was posted on.
        comment_id: The comment's id (passed through to the TPM for
            traceability).
        comment_body: The raw comment text.
        author_session_id: Session id of whoever authored the comment.
            ``None`` when the author is a Human via Telegram / Web UI.

    Returns:
        The TPM session id that received the message, or ``None`` if
        the dispatch was skipped (no TPM, or self-comment).
    """
    tpm = await store.get_active_tpm_for_ticket(ticket_id)
    if tpm is None:
        logger.warning(
            "Comment dispatch: ticket %s has no active TPM; comment %s "
            "received with no recipient (will be visible to a future TPM "
            "via ticket history if one is spawned later)",
            ticket_id,
            comment_id,
        )
        return None

    tpm_session_id = tpm["id"]
    if author_session_id == tpm_session_id:
        logger.debug(
            "Comment dispatch: comment %s on ticket %s was authored by "
            "TPM session %s; skipping to avoid self-feedback loop",
            comment_id,
            ticket_id,
            tpm_session_id,
        )
        return None

    formatted = _format_comment_for_tpm(
        ticket_id=ticket_id,
        comment_id=comment_id,
        comment_body=comment_body,
        author_session_id=author_session_id,
    )
    logger.info(
        "Comment dispatch: forwarding comment %s on ticket %s to TPM "
        "session %s (author=%s)",
        comment_id,
        ticket_id,
        tpm_session_id,
        author_session_id if author_session_id else "human",
    )
    await session_manager.append_message(tpm_session_id, formatted)
    return tpm_session_id


__all__ = [
    "dispatch_comment_to_tpm",
]
