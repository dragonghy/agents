"""Claude adapter — wires the Claude Agent SDK into our orchestration layer.

This is the first concrete :class:`Adapter` implementation. It uses
``claude_agent_sdk.query()`` (the one-shot async-iterator entry point) for
both first-turn and resume flows; the SDK handles JSONL persistence and
auto-compaction internally, so we only need to track its ``session_id``
in our ``session.native_handle`` column.

Mapping table:

| Our concept            | SDK concept                              |
|------------------------|------------------------------------------|
| Profile.system_prompt  | ``ClaudeAgentOptions.system_prompt``     |
| Profile.runner_type    | ``ClaudeAgentOptions.model`` (mapped)    |
| SessionMetadata fields | nothing on first turn                    |
| .native_handle (str)   | ``ClaudeAgentOptions.resume`` on retry   |
| RunResult.assistant_text | concatenated TextBlock text            |
| RunResult.tokens_in/out | ``ResultMessage.usage`` final event     |
| RunResult.native_handle | ``ResultMessage.session_id``            |

Notes:

- **MCP wiring is deferred to Task #11.** ``profile.mcp_servers`` is a list
  of *logical* names ("agents", "agent-hub", ...). Resolving those to
  concrete transport configs (stdio command + args, HTTP URL, ...) is the
  Session Manager's job. For now we log non-empty mcp_server lists and
  continue without wiring; tests pass an empty list.
- **Permission mode** defaults to ``"bypassPermissions"`` because the
  daemon is the only operator; there is no human in the loop to approve
  individual tool calls. This will be revisited when channel adapters land.
- **Token aggregation**: if the SDK returns ``cache_read_input_tokens``
  and ``cache_creation_input_tokens``, we sum them into ``tokens_in`` so
  cost dashboards see the full input side of the bill. Output is just
  ``output_tokens``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .base import Profile, RunResult, SessionMetadata

if TYPE_CHECKING:
    from agents_mcp.store import AgentStore

logger = logging.getLogger(__name__)


# Map our runner_type to the SDK's ``model`` argument. The SDK accepts
# either an alias (sonnet/haiku/opus) or a full model id; we keep this map
# small and pass unknown values through verbatim so future model rollouts
# don't require a code change.
_MODEL_ALIASES: dict[str, str] = {
    "claude-sonnet-4.6": "claude-sonnet-4-5",
    "claude-sonnet": "claude-sonnet-4-5",
    "claude-opus-4.7": "claude-opus-4-5",
    "claude-opus": "claude-opus-4-5",
    "claude-haiku": "claude-haiku-4-5",
    "claude-haiku-4.5": "claude-haiku-4-5",
}


def _resolve_model(runner_type: str) -> str | None:
    """Translate a Profile ``runner_type`` to an SDK ``model`` value.

    Returns ``None`` if the SDK should pick its default. We pass-through
    unknown strings so users can specify a full model id directly.
    """
    if runner_type == "claude":
        return None  # let SDK default
    return _MODEL_ALIASES.get(runner_type, runner_type)


def _extract_tokens(usage: dict[str, Any] | None) -> tuple[int, int]:
    """Pull (tokens_in, tokens_out) from a SDK ``usage`` dict.

    Anthropic's usage shape:
        ``{input_tokens, output_tokens, cache_creation_input_tokens,
           cache_read_input_tokens}``

    We sum all three input variants into ``tokens_in`` so the cost
    dashboard sees the full input bill. Missing keys default to 0.
    """
    if not usage:
        return 0, 0
    tokens_in = (
        int(usage.get("input_tokens", 0) or 0)
        + int(usage.get("cache_creation_input_tokens", 0) or 0)
        + int(usage.get("cache_read_input_tokens", 0) or 0)
    )
    tokens_out = int(usage.get("output_tokens", 0) or 0)
    return tokens_in, tokens_out


class ClaudeAdapter:
    """Adapter implementation for the Claude Agent SDK."""

    async def run(
        self,
        profile: Profile,
        session_metadata: SessionMetadata,
        new_message_text: str,
        store: "AgentStore",
        *,
        mcp_servers: dict[str, Any] | None = None,
        allowed_tools: list[str] | None = None,
    ) -> RunResult:
        """Execute one Claude turn for the given session.

        First-turn flow:
            1. Build ``ClaudeAgentOptions`` with ``system_prompt`` + ``model``
               (and no ``resume``, no ``session_id``).
            2. ``async for msg in query(prompt=new_message_text, options=opts)``.
            3. Aggregate ``TextBlock`` text from every ``AssistantMessage``.
            4. Capture ``session_id`` from the first event that carries one
               (``AssistantMessage.session_id`` or ``ResultMessage.session_id``).
            5. Take final ``usage`` from ``ResultMessage``.
            6. Persist native_handle + cost via ``store``.

        Resume flow:
            Same, but ``ClaudeAgentOptions.resume`` is set to
            ``session_metadata.native_handle``. The SDK reloads the JSONL
            from ``~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`` and
            appends the new turn.
        """
        if profile.mcp_servers:
            # TODO(Task #11): resolve logical names to McpServerConfig dicts
            # via the Session Manager and pass through ClaudeAgentOptions.
            logger.info(
                "ClaudeAdapter: profile=%s requested mcp_servers=%s but "
                "MCP wiring is not yet implemented (Task #11). Continuing "
                "without MCP servers.",
                profile.name,
                list(profile.mcp_servers),
            )

        opts_kwargs: dict[str, Any] = dict(
            system_prompt=profile.system_prompt,
            model=_resolve_model(profile.runner_type),
            resume=session_metadata.native_handle,
            permission_mode="bypassPermissions",
        )
        if mcp_servers:
            opts_kwargs["mcp_servers"] = mcp_servers
        if allowed_tools:
            # ClaudeAgentOptions.allowed_tools defaults to []; passing an
            # empty list is meaningless (it's the same as omitting it),
            # so we only set the field when there's something to allow.
            opts_kwargs["allowed_tools"] = list(allowed_tools)

        opts = ClaudeAgentOptions(**opts_kwargs)

        assistant_chunks: list[str] = []
        captured_session_id: str | None = None
        final_usage: dict[str, Any] | None = None

        async for event in query(prompt=new_message_text, options=opts):
            if isinstance(event, AssistantMessage):
                if event.session_id and captured_session_id is None:
                    captured_session_id = event.session_id
                for block in event.content:
                    if isinstance(block, TextBlock):
                        assistant_chunks.append(block.text)
                    # ToolUseBlock / ThinkingBlock / etc. are intentionally
                    # ignored at this layer — Task #11+ will surface them.
            elif isinstance(event, ResultMessage):
                if event.session_id and captured_session_id is None:
                    captured_session_id = event.session_id
                final_usage = event.usage
                if event.is_error:
                    raise RuntimeError(
                        f"Claude SDK returned error result: "
                        f"subtype={event.subtype!r} stop_reason={event.stop_reason!r} "
                        f"errors={event.errors!r}"
                    )
            # SystemMessage / UserMessage / StreamEvent / RateLimitEvent
            # are not load-bearing for v1; ignore.

        if captured_session_id is None:
            raise RuntimeError(
                "Claude SDK never emitted a session_id; this should not happen "
                "for a successful query() invocation"
            )

        tokens_in, tokens_out = _extract_tokens(final_usage)

        # Persist native_handle on the very first turn (no-op if it's already
        # set to the same value — store.update_session_native_handle is
        # idempotent).
        if session_metadata.native_handle != captured_session_id:
            await store.update_session_native_handle(
                session_metadata.session_id, captured_session_id
            )

        # Always record cost; tokens_in / tokens_out may be zero on edge
        # cases (e.g. cached-only responses) but that's still valid data.
        await store.add_session_cost(
            session_metadata.session_id, tokens_in, tokens_out
        )

        return RunResult(
            assistant_text="".join(assistant_chunks),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            native_handle=captured_session_id,
        )


__all__ = ["ClaudeAdapter"]
