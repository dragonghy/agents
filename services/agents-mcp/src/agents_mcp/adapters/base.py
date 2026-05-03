"""Shared types for the Adapter layer.

This module hosts the small surface that Adapters and the orchestration layer
both depend on:

- :class:`Profile` — static definition of an agent kind (loaded from
  ``profiles/<name>/profile.md``).
- :class:`SessionMetadata` — the slice of a ``session`` row that an Adapter
  needs in order to start or resume a native conversation.
- :class:`RunResult` — what an Adapter returns from a single LLM turn.
- :class:`Adapter` — the Protocol every concrete adapter implements.

The Adapter Protocol is intentionally minimal for v1: a single
``async def run(...)`` that takes a Profile, a SessionMetadata, the new user
message text, and an :class:`~agents_mcp.store.AgentStore` for the
``native_handle`` + cost-tracking side effects. No streaming callbacks yet —
the Session Manager (Task #11) will layer SSE / WebSocket on top once it
exists. ``run()`` simply returns the final assistant text + token counts.

Design references:
- ``projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md`` §2.6
- ``projects/agent-hub/research/claude-sdk-session-model-2026-05-02.md``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agents_mcp.store import AgentStore


@dataclass(frozen=True)
class Profile:
    """A loaded Profile definition.

    Attributes:
        name: Unique identifier (matches the directory under profiles/). E.g. "tpm".
        description: One- or two-sentence machine-readable description; used by
            the TPM (and other Profile-selecting code) to decide which Profile
            to spawn for a given task. Source: frontmatter.
        runner_type: Adapter selector. E.g. "claude-sonnet-4.6" routes to the
            Claude adapter; "gpt-5" would route to the OpenAI adapter (future).
        mcp_servers: Logical MCP server names this Profile expects access to
            (e.g. "agents", "agent-hub", "google_personal"). The orchestrator
            wires these in at session-creation time; Profiles never bind to
            specific MCP server config files directly.
        skills: Skill names this Profile loads from the shared skills tree.
            Optional — many Profiles don't need any.
        system_prompt: The body of the .md file (everything after the closing
            frontmatter ``---``). Used as the system prompt for every session
            of this Profile.
        file_path: Absolute path to the source profile.md. Optional for
            test/synthetic profiles.
        file_hash: sha256 of the file content. Optional for test/synthetic
            profiles.
        orchestration_tools: When ``True``, the SessionManager wires an
            in-process MCP server exposing the four orchestration tools
            (``spawn_subagent``, ``push_message``, ``post_comment``,
            ``mark_ticket_status``) into this Profile's adapter run. Used by
            the TPM Profile to materialize coordination decisions; defaults
            to ``False`` for every other Profile (Developer, Architect, etc.)
            which only respond to plain text turns.
    """

    name: str
    runner_type: str
    system_prompt: str
    description: str = ""
    file_path: str = ""
    file_hash: str = ""
    mcp_servers: tuple[str, ...] = field(default_factory=tuple)
    skills: tuple[str, ...] = field(default_factory=tuple)
    orchestration_tools: bool = False


class ProfileParseError(ValueError):
    """Raised when a profile.md is malformed.

    Includes path + a short reason; callers (loader, smoke tests) catch this
    and skip the bad file rather than crashing the daemon.
    """

    def __init__(self, path: str, reason: str):
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


@dataclass(frozen=True)
class SessionMetadata:
    """The minimal view of a session row that an Adapter needs.

    Mirrors a subset of columns from the ``session`` table; we don't pass the
    whole dict so Adapter code can't drift behind schema changes it doesn't
    care about.

    Attributes:
        session_id: Our session id (primary key in ``session``).
        native_handle: Adapter-specific session locator. ``None`` on the
            first turn (the Adapter must populate it via
            ``store.update_session_native_handle`` once it learns the handle
            from the SDK). For Claude this is the SDK ``session_id`` used for
            ``resume``.
        runner_type: Mirrors ``Profile.runner_type``; carried here so the
            Adapter doesn't need to re-derive it from the profile.
    """

    session_id: str
    native_handle: str | None
    runner_type: str


@dataclass
class RunResult:
    """Outcome of one Adapter ``run()`` call (one LLM round-trip).

    Attributes:
        assistant_text: Final aggregated assistant text for this turn.
            Concatenation of all ``TextBlock`` content across emitted
            ``AssistantMessage`` events.
        tokens_in: Input token count from the SDK's final result event.
            Includes cache reads when the provider reports them; we sum them
            for a single "what did this turn cost on the input side" number.
        tokens_out: Output token count from the SDK's final result event.
        native_handle: The Adapter-specific session locator that should be
            persisted on the session row. Always set on success (first turn
            discovers it; resume turns echo it back).
    """

    assistant_text: str
    tokens_in: int
    tokens_out: int
    native_handle: str


class Adapter(Protocol):
    """Single LLM provider integration.

    Implementations live next to this file (``claude_adapter.py``; future
    ``openai_adapter.py``, ``gemini_adapter.py``) and are looked up by
    :func:`agents_mcp.adapters.get_adapter`.

    Contract:

    - ``run()`` MUST be idempotent on its inputs: same ``profile`` + same
      ``session_metadata`` + same ``new_message_text`` should produce a
      comparable ``RunResult`` (modulo LLM nondeterminism).
    - On the first turn (``session_metadata.native_handle is None``), the
      Adapter starts a fresh native session, captures the SDK's session id,
      calls ``store.update_session_native_handle(...)`` and returns it in
      ``RunResult.native_handle``.
    - On resume turns, the Adapter passes ``native_handle`` to the SDK and
      lets the SDK reload its native history (e.g. JSONL on disk for Claude).
    - On every successful turn the Adapter MUST call
      ``store.add_session_cost(session_id, tokens_in, tokens_out)`` so the
      cost dashboard stays accurate.
    - Failures bubble as exceptions; the Session Manager (Task #11) decides
      how to retry / surface them. Adapters should not swallow provider
      errors silently.
    """

    async def run(
        self,
        profile: Profile,
        session_metadata: SessionMetadata,
        new_message_text: str,
        store: "AgentStore",
    ) -> RunResult:
        """Execute one LLM turn for the given session.

        Args:
            profile: What kind of agent we're running (system prompt, model
                selector, MCP needs).
            session_metadata: Where this session is in its lifecycle —
                ``native_handle is None`` => first turn.
            new_message_text: The user message to append to the conversation.
            store: Async store handle for cost / native_handle persistence
                side effects.

        Returns:
            :class:`RunResult` with assistant text, token counts, and the
            (possibly newly-captured) native handle.
        """
        ...


__all__ = [
    "Adapter",
    "Profile",
    "ProfileParseError",
    "RunResult",
    "SessionMetadata",
]
