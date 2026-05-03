"""Session Manager — owns the lifecycle of orchestration v1 Sessions.

A :class:`SessionManager` is the thin layer between callers (TPM auto-spawn
hook, comment-driven dispatcher, channel adapters) and the two collaborators
that already exist:

- :class:`agents_mcp.store.AgentStore` for session row CRUD.
- :class:`agents_mcp.adapters.base.Adapter` (resolved via
  :func:`agents_mcp.adapters.get_adapter`) for the actual LLM round-trip.

The manager itself holds no in-process state. Sessions are stateless from our
side; the conversation history lives in the Adapter's native store (Claude
SDK's JSONL). That means restarts are safe, hot reloads are free, and there
is no "warm pool" of session objects to manage.

What the manager does provide:

- :meth:`spawn` — generate an id, insert a row, touch the Profile registry's
  ``last_used_at``. Does NOT call the Adapter; the first turn happens on the
  first :meth:`append_message`.
- :meth:`append_message` — load the Profile from disk, look up the Adapter,
  build a :class:`SessionMetadata` snapshot, and delegate to ``adapter.run``.
  The Adapter persists ``native_handle`` + cost via the store directly; we
  return its :class:`RunResult` unchanged.
- :meth:`close` — mark a session closed (idempotent passthrough to the store).

Out of scope (deferred to later tasks):

- TPM auto-spawn hook (Task #12).
- Comment-driven dispatch (Task #13).
- Streaming / SSE (later phase).
- Mid-session adapter switch (explicitly disallowed by design §2.6).

Naming note: this module is ``orchestration_session_manager`` rather than
``session_manager`` because the latter is already taken by the legacy v2
tmux-based SessionManager (``services/agents-mcp/src/agents_mcp/session_manager.py``)
that the daemon currently relies on. The two managers represent different
generations of the architecture; once the orchestration v1 dispatcher / TPM
hook lands and the tmux flow is retired, we can rename this back. Decision
recorded in ``projects/agent-hub/orchestration-v1-progress.md``.

See: ``projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md``
§2.2 (Session) + §2.6 (Adapter) + §2.7 (Daemon).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from .adapters import get_adapter
from .adapters.base import RunResult, SessionMetadata
from .profile_loader import load_profile
from .store import AgentStore

logger = logging.getLogger(__name__)


# Allowed binding kinds. Mirrors the CHECK constraint in store.py's session
# table; we duplicate it here so we can fail fast (with a useful message)
# before the SQLite layer raises a generic IntegrityError.
_VALID_BINDING_KINDS = frozenset(
    {"ticket-subagent", "human-channel", "standalone"}
)


def _generate_session_id() -> str:
    """Return a sortable, dependency-free session id.

    Layout: ``sess_<10 hex of ms-since-epoch><12 hex random>`` = 22 hex chars
    after the prefix. The ms-since-epoch prefix gives ULID-style monotonic
    ordering for 35+ years of timestamps without bumping past 10 hex digits;
    the random suffix protects against same-millisecond collisions.

    Not strictly ULID format — we don't bother with Crockford base32 or the
    exact 26-char layout — but it satisfies the same operational properties:
    short, sortable, globally unique enough for our scale.
    """
    ms = int(time.time() * 1000) & 0xFFFFFFFFFF  # 40 bits = 10 hex digits
    rand = os.urandom(6).hex()  # 12 hex digits
    return f"sess_{ms:010x}{rand}"


class SessionManager:
    """Lifecycle owner for orchestration v1 Sessions.

    Holds references to the store and the profiles directory; everything
    else (Profile content, native handles, conversation history) lives off
    to the side. Methods are async — they delegate to async store CRUD or
    to the async Adapter.
    """

    def __init__(
        self,
        store: AgentStore,
        profiles_dir: Path,
        *,
        task_client: Any = None,
    ):
        """Construct a SessionManager.

        Args:
            store: AgentStore for session row CRUD.
            profiles_dir: Path to the ``profiles/`` directory containing
                ``<name>/profile.md`` files.
            task_client: Optional Leantime/SQLite task client. Required
                only when orchestration tools (``post_comment`` /
                ``mark_ticket_status``) are wired in for a TPM session.
                Other Profile types don't need it; passing ``None`` is fine
                until you spawn something with ``orchestration_tools=True``.
        """
        self._store = store
        self._profiles_dir = Path(profiles_dir)
        self._task_client = task_client

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def spawn(
        self,
        *,
        profile_name: str,
        binding_kind: str,
        ticket_id: Optional[int] = None,
        channel_id: Optional[str] = None,
        parent_session_id: Optional[str] = None,
    ) -> dict:
        """Create a new session and return its row.

        Validates inputs, loads the Profile (so a typo'd ``profile_name``
        fails before we insert anything), generates an id, inserts the row,
        and bumps the Profile registry's ``last_used_at``.

        Does NOT call the Adapter — the first LLM turn happens on the first
        :meth:`append_message`. This keeps spawn cheap (no API round-trip)
        and preserves the design property that "session = metadata row;
        history lives in the Adapter".

        Args:
            profile_name: Directory name under ``profiles/``. The Profile
                file is read here to fail fast if the name is wrong.
            binding_kind: One of ``ticket-subagent``, ``human-channel``,
                ``standalone``. Mismatch raises :class:`ValueError`.
            ticket_id: Optional ticket binding. Required by convention for
                ``ticket-subagent`` but not enforced here — the dispatcher /
                TPM hook owns that policy.
            channel_id: Optional channel binding (e.g. ``telegram:123``).
            parent_session_id: Spawning TPM's session id, if this is a
                subagent under a TPM. ``None`` for TPM and standalone.

        Returns:
            The session row as a dict (same shape as
            :meth:`AgentStore.get_session`).

        Raises:
            ValueError: ``binding_kind`` is not one of the allowed values.
            FileNotFoundError: profile.md doesn't exist for the given name.
            ProfileParseError: profile.md exists but is malformed.
        """
        if binding_kind not in _VALID_BINDING_KINDS:
            raise ValueError(
                f"binding_kind must be one of {sorted(_VALID_BINDING_KINDS)}, "
                f"got {binding_kind!r}"
            )

        # Load the Profile up-front — this surfaces typo'd names + parse
        # errors as exceptions BEFORE we insert a session row, so we never
        # leave orphan rows pointing at non-existent profiles.
        profile = load_profile(profile_name, self._profiles_dir)

        session_id = _generate_session_id()
        row = await self._store.create_session(
            session_id=session_id,
            profile_name=profile.name,
            binding_kind=binding_kind,
            runner_type=profile.runner_type,
            ticket_id=ticket_id,
            channel_id=channel_id,
            parent_session_id=parent_session_id,
        )
        # Best-effort: bump last_used_at on the Profile registry. If the
        # registry hasn't been scanned yet (e.g. first boot, profile only
        # just dropped on disk), this is a no-op — the registry is a
        # discovery cache, not a foreign key.
        await self._store.touch_profile_used(profile.name)

        logger.info(
            "SessionManager: spawned session %s (profile=%s binding=%s "
            "ticket=%s channel=%s parent=%s)",
            session_id,
            profile.name,
            binding_kind,
            ticket_id,
            channel_id,
            parent_session_id,
        )
        return row

    async def append_message(
        self,
        session_id: str,
        message_text: str,
    ) -> RunResult:
        """Push a new user message into a session and run one Adapter turn.

        Steps:

        1. Look up the session metadata row.
        2. Reject if the session is closed (no late writes after teardown).
        3. Re-load the Profile from disk — picks up any edits made since
           the session started, which is intentional (Profile content is
           live; the system prompt for the next turn reflects current
           profile.md).
        4. Resolve the Adapter via :func:`get_adapter` based on the
           session's stored ``runner_type`` (NOT the profile's — they
           should match, but the session row is the source of truth for
           "which adapter is bound to this conversation").
        5. Build a :class:`SessionMetadata` snapshot.
        6. Call ``adapter.run(profile, snapshot, message_text, store)``.
           The Adapter is responsible for persisting ``native_handle`` on
           first turn and adding cost via the store on every turn.
        7. Return the :class:`RunResult` unchanged.

        Args:
            session_id: The id returned by :meth:`spawn`.
            message_text: The new user message to feed into the
                conversation.

        Returns:
            The Adapter's :class:`RunResult` for this turn.

        Raises:
            LookupError: No session with that id.
            RuntimeError: Session exists but is closed.
            FileNotFoundError / ProfileParseError: Profile was deleted /
                broken between spawn and this call.
            Anything the Adapter raises: bubbled unchanged so callers can
                decide retry / surface policy.
        """
        session_row = await self._store.get_session(session_id)
        if session_row is None:
            raise LookupError(f"unknown session id: {session_id!r}")
        if session_row["status"] == "closed":
            raise RuntimeError(
                f"session {session_id!r} is closed; cannot append messages"
            )

        profile = load_profile(session_row["profile_name"], self._profiles_dir)

        adapter = get_adapter(session_row["runner_type"])

        snapshot = SessionMetadata(
            session_id=session_row["id"],
            native_handle=session_row["native_handle"],
            runner_type=session_row["runner_type"],
        )

        # If this Profile asks for the orchestration tool surface (TPM),
        # build an in-process MCP server bound to this session + ticket
        # and pass it to the Adapter. Other Profiles get plain text-only
        # turns. The tool server is rebuilt every turn — cheap (no IPC,
        # no subprocess) and means TPM-ticket binding is always fresh.
        adapter_kwargs: dict[str, Any] = {}
        if profile.orchestration_tools:
            ticket_id = session_row["ticket_id"]
            if ticket_id is None:
                raise RuntimeError(
                    f"profile {profile.name!r} declares orchestration_tools=True "
                    f"but session {session_id!r} has no ticket_id; "
                    f"orchestration tools require a ticket binding"
                )
            if self._task_client is None:
                raise RuntimeError(
                    f"profile {profile.name!r} declares orchestration_tools=True "
                    f"but SessionManager was constructed without a task_client; "
                    f"pass task_client=... to enable orchestration tools"
                )
            # Local import — keeps the SDK + tools module out of the
            # import path for non-orchestration callers.
            from .orchestration_tools import (
                TPM_TOOL_NAMES,
                build_tpm_tool_server,
            )

            mcp_server = build_tpm_tool_server(
                session_manager=self,
                store=self._store,
                task_client=self._task_client,
                parent_session_id=session_id,
                bound_ticket_id=int(ticket_id),
            )
            server_name = f"orchestration_tpm_{ticket_id}"
            adapter_kwargs["mcp_servers"] = {server_name: mcp_server}
            # Claude Code addresses MCP tools as
            # ``mcp__<server_name>__<tool_name>``. Pre-allow them so the
            # session can call them without an interactive permission
            # prompt (which never resolves in headless daemon mode even
            # with bypassPermissions for some SDK versions).
            adapter_kwargs["allowed_tools"] = [
                f"mcp__{server_name}__{tn}" for tn in TPM_TOOL_NAMES
            ]

        logger.debug(
            "SessionManager: appending to %s (profile=%s runner=%s "
            "native_handle=%s tools=%s)",
            session_id,
            profile.name,
            session_row["runner_type"],
            session_row["native_handle"],
            "orchestration" if profile.orchestration_tools else "none",
        )
        return await adapter.run(
            profile, snapshot, message_text, self._store, **adapter_kwargs
        )

    async def close(self, session_id: str) -> bool:
        """Mark a session closed. Idempotent.

        Thin passthrough to :meth:`AgentStore.close_session`. Returns
        ``True`` if this call transitioned the session from active to
        closed; returns ``False`` if it was already closed or doesn't
        exist (the store can't tell us which, and callers don't need to).
        """
        return await self._store.close_session(session_id)


__all__ = ["SessionManager"]
