"""Adapter layer — translates Profile + new message into an LLM API call.

Concrete adapters (Claude, OpenAI, Gemini) live alongside this module. The
``base`` submodule defines the shared types (:class:`Profile`,
:class:`SessionMetadata`, :class:`RunResult`, and the :class:`Adapter`
Protocol) that adapters and orchestration code import from.

The :func:`get_adapter` factory dispatches by ``runner_type`` prefix:

- ``claude-*``  → :class:`agents_mcp.adapters.claude_adapter.ClaudeAdapter`
- ``gpt-*``     → reserved (raises ``NotImplementedError`` for now)
- ``gemini-*``  → reserved (raises ``NotImplementedError`` for now)

See: ``projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md`` §2.6.
"""

from __future__ import annotations

from .base import (
    Adapter,
    Profile,
    ProfileParseError,
    RenderedMessage,
    RunResult,
    SessionMetadata,
)


def get_adapter(runner_type: str) -> Adapter:
    """Return the Adapter instance that handles the given ``runner_type``.

    Dispatch is by *prefix*, not exact match, because runner_type also
    encodes the model (``claude-sonnet-4.6`` vs ``claude-haiku``) — both go
    to the same Claude adapter, which then passes the model selector through
    to the SDK.

    Args:
        runner_type: The Profile's ``runner_type``, e.g. ``"claude-sonnet-4.6"``.

    Returns:
        An adapter instance ready to ``run()``.

    Raises:
        ValueError: If the runner_type doesn't match any registered family.
        NotImplementedError: If the family is reserved but not yet built
            (OpenAI / Gemini in v1).
    """
    if not runner_type:
        raise ValueError("runner_type must be a non-empty string")

    if runner_type.startswith("claude"):
        # Imported lazily so the OpenAI / Gemini families don't pay the
        # Claude SDK import cost when they land.
        from .claude_adapter import ClaudeAdapter

        return ClaudeAdapter()

    if runner_type.startswith("gpt") or runner_type.startswith("openai"):
        raise NotImplementedError(
            f"OpenAI adapter not implemented in v1 (runner_type={runner_type!r}); "
            "see Phase 5 of the orchestration roadmap"
        )

    if runner_type.startswith("gemini"):
        raise NotImplementedError(
            f"Gemini adapter not implemented in v1 (runner_type={runner_type!r}); "
            "see Phase 5 of the orchestration roadmap"
        )

    raise ValueError(
        f"unknown runner_type {runner_type!r}; expected one of: "
        "claude-*, gpt-* / openai-* (NYI), gemini-* (NYI)"
    )


__all__ = [
    "Adapter",
    "Profile",
    "ProfileParseError",
    "RenderedMessage",
    "RunResult",
    "SessionMetadata",
    "get_adapter",
]
