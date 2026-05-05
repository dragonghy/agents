"""TPM auto-spawn / auto-close hooks for orchestration v1.

The doctrine here is narrow and deliberate (see
``projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md`` §2.3):

- A ticket gets a TPM **only** on the ``status=3 → status=4`` transition
  (New → In Progress). Every other transition is a no-op for spawn purposes.
  We don't spawn on ticket creation (ticket may sit in New for a long time
  before anyone picks it up), and we don't re-spawn on rework transitions
  (e.g. Blocked → In Progress) — the existing TPM resumes.
- A ticket's TPM is closed when the ticket transitions to a terminal
  state (``status=0`` Done or ``status=-1`` Archived). This is the
  symmetric bookend to spawn.
- Both hooks are idempotent: spawning when a TPM already exists is a
  silent no-op; closing when none exists is a silent no-op.

These functions are pure orchestration helpers — they take a
:class:`SessionManager` and an :class:`AgentStore` and do nothing else
side-effecty. The caller (a future daemon-side ticket-status-changed
event listener; Phase 2.5 plumbing) decides when to invoke them.

Out of scope here:

- Wiring into the daemon's ticket-status-changed event stream. That's
  daemon plumbing for a later commit.
- Comment-driven dispatch — see ``orchestration_comment_dispatch.py``.
- Subagent auto-spawn under a TPM — TPM decides that itself by emitting
  a tool call from inside its session.
"""

from __future__ import annotations

import logging
from typing import Optional

from .orchestration_session_manager import SessionManager
from .store import AgentStore

logger = logging.getLogger(__name__)


# Ticket status codes (mirrors the convention documented in CLAUDE.md):
#   0  = Done
#   1  = Blocked
#   3  = New
#   4  = In Progress
#  -1  = Archived
# (Status 2 is intentionally unused.)
_STATUS_NEW = 3
_STATUS_IN_PROGRESS = 4
_STATUS_DONE = 0
_STATUS_ARCHIVED = -1

_TERMINAL_STATUSES = frozenset({_STATUS_DONE, _STATUS_ARCHIVED})


async def maybe_spawn_tpm_for_status_change(
    session_manager: SessionManager,
    store: AgentStore,
    *,
    ticket_id: int,
    old_status: int,
    new_status: int,
) -> Optional[str]:
    """Spawn a TPM for ``ticket_id`` iff this is the canonical 3→4 hop.

    Doctrine (see module docstring): only the New→In-Progress transition
    spawns a TPM. All other transitions are no-ops here — including
    Blocked→In-Progress and other rework hops, because the original TPM
    persists across the ticket's life and just resumes.

    Args:
        session_manager: Used to spawn the TPM session if needed.
        store: Used to check whether an active TPM already exists for
            this ticket (idempotency guard).
        ticket_id: The ticket whose status just changed.
        old_status: Previous status code.
        new_status: New status code.

    Returns:
        The new TPM session id if one was spawned, or ``None`` if this
        call was a no-op (wrong transition, or TPM already present).

    Notes:
        Profile name is hardcoded to ``"tpm"``; binding is
        ``"ticket-subagent"`` with no parent (the TPM is the root of the
        per-ticket session tree). Failures from
        :meth:`SessionManager.spawn` (e.g. profile.md missing) bubble up
        unchanged — the caller decides how to surface them.
    """
    if old_status != _STATUS_NEW or new_status != _STATUS_IN_PROGRESS:
        logger.debug(
            "TPM auto-spawn: skipping ticket %s (status %s -> %s is not 3->4)",
            ticket_id,
            old_status,
            new_status,
        )
        return None

    existing = await store.get_active_tpm_for_ticket(ticket_id)
    if existing is not None:
        logger.info(
            "TPM auto-spawn: ticket %s already has active TPM %s; no-op",
            ticket_id,
            existing["id"],
        )
        return None

    row = await session_manager.spawn(
        profile_name="tpm",
        binding_kind="ticket-subagent",
        ticket_id=ticket_id,
    )
    logger.info(
        "TPM auto-spawn: ticket %s entered status=4; spawned TPM session %s",
        ticket_id,
        row["id"],
    )
    return row["id"]


async def maybe_spawn_tpm_for_new_ticket(
    session_manager: SessionManager,
    store: AgentStore,
    *,
    ticket_id: int,
    status: int,
) -> Optional[str]:
    """Spawn a TPM immediately when a new ticket is created.

    Per Human directive 2026-05-04 ("every newly-created ticket should
    auto-trigger TPM triage"): any newly-created non-terminal ticket
    gets a TPM right away so it can analyse the description, decide
    sub-tasks, and either spawn a developer / housekeeper or post a
    clarifying comment. Avoids the "ticket sits with no owner for hours"
    failure mode the old 3→4-only policy created.

    No-op if:
    - The ticket is already in a terminal state (Done / Archived) — no
      point analysing something already closed.
    - A TPM is already bound to the ticket — idempotent so callers can
      retry safely (e.g. on POST + immediate PATCH back-to-back).

    Args:
        session_manager: Used to spawn the TPM session.
        store: Used to check whether an active TPM already exists.
        ticket_id: Newly inserted ticket id.
        status: The ticket's current status. Skipped if terminal.

    Returns:
        The new TPM session id if one was spawned, else ``None``.
    """
    if status in _TERMINAL_STATUSES:
        logger.debug(
            "TPM auto-spawn (new ticket): #%s starts in terminal status=%s; skipping",
            ticket_id,
            status,
        )
        return None
    existing = await store.get_active_tpm_for_ticket(ticket_id)
    if existing is not None:
        logger.info(
            "TPM auto-spawn (new ticket): #%s already has active TPM %s; no-op",
            ticket_id,
            existing["id"],
        )
        return None
    row = await session_manager.spawn(
        profile_name="tpm",
        binding_kind="ticket-subagent",
        ticket_id=ticket_id,
    )
    logger.info(
        "TPM auto-spawn (new ticket): #%s → spawned TPM session %s",
        ticket_id,
        row["id"],
    )
    return row["id"]


async def maybe_close_tpm_for_status_change(
    store: AgentStore,
    *,
    ticket_id: int,
    new_status: int,
) -> bool:
    """Close the active TPM for ``ticket_id`` iff the ticket is now terminal.

    Terminal statuses are ``0`` (Done) and ``-1`` (Archived). All other
    transitions are no-ops; in particular Blocked (status=1) does NOT
    tear the TPM down — Blocked tickets often resume.

    Idempotent: if no active TPM exists, returns ``False`` without
    raising.

    Args:
        store: Used to look up + close the TPM session.
        ticket_id: The ticket whose status just changed.
        new_status: New status code.

    Returns:
        ``True`` if a TPM was found and closed; ``False`` otherwise (no
        TPM, or non-terminal status).
    """
    if new_status not in _TERMINAL_STATUSES:
        logger.debug(
            "TPM auto-close: ticket %s new status %s is not terminal; no-op",
            ticket_id,
            new_status,
        )
        return False

    existing = await store.get_active_tpm_for_ticket(ticket_id)
    if existing is None:
        logger.debug(
            "TPM auto-close: ticket %s has no active TPM; no-op",
            ticket_id,
        )
        return False

    closed = await store.close_session(existing["id"])
    if closed:
        logger.info(
            "TPM auto-close: ticket %s reached terminal status %s; "
            "closed TPM session %s",
            ticket_id,
            new_status,
            existing["id"],
        )
    else:
        # Race: someone closed it between our lookup and our update.
        # Surface as no-op; the desired post-condition (no active TPM)
        # holds either way.
        logger.info(
            "TPM auto-close: ticket %s TPM session %s already closed by "
            "another writer; no-op",
            ticket_id,
            existing["id"],
        )
    return closed


__all__ = [
    "maybe_close_tpm_for_status_change",
    "maybe_spawn_tpm_for_new_ticket",
    "maybe_spawn_tpm_for_status_change",
]
