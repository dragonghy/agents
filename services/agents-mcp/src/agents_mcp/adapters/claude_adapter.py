"""Claude adapter — wires the Claude Agent SDK into our orchestration layer.

This is the first concrete :class:`Adapter` implementation. It uses
``claude_agent_sdk.query()`` (the one-shot async-iterator entry point) for
both first-turn and resume flows; the SDK handles JSONL persistence and
auto-compaction internally, so we only need to track its ``session_id``
in our ``session.native_handle`` column.

History rendering (:meth:`ClaudeAdapter.render_history`) walks
``~/.claude/projects/<encoded-cwd>/<native_handle>.jsonl`` and emits
:class:`RenderedMessage` items. The cwd is unknown at rendering time
(sessions might have been created from different working directories), so
we glob across every project directory and take the first match.

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

- **MCP wiring**: callers (the Session Manager) pass concrete
  ``McpSdkServerConfig`` dicts via the ``mcp_servers`` kwarg, which we
  forward verbatim to ``ClaudeAgentOptions.mcp_servers``. Phase 2.5
  (orchestration_tools) uses this to bind the per-ticket TPM tool surface.
  ``profile.mcp_servers`` (the *logical name list* declared in
  ``profile.md``) is metadata only — it is surfaced in the Web Console
  registry and read by callers that want to resolve the names themselves;
  the adapter never auto-resolves it.
- **Permission mode** defaults to ``"bypassPermissions"`` because the
  daemon is the only operator; there is no human in the loop to approve
  individual tool calls. This will be revisited when channel adapters land.
- **Token aggregation**: if the SDK returns ``cache_read_input_tokens``
  and ``cache_creation_input_tokens``, we sum them into ``tokens_in`` so
  cost dashboards see the full input side of the bill. Output is just
  ``output_tokens``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .base import (
    AssistantChunkCallback,
    Profile,
    RenderedMessage,
    RunResult,
    SessionMetadata,
)

if TYPE_CHECKING:
    from agents_mcp.store import AgentStore

logger = logging.getLogger(__name__)


# Map our runner_type to the SDK's ``model`` argument. The SDK accepts
# either an alias (sonnet/haiku/opus) or a full model id; we keep this map
# small and pass unknown values through verbatim so future model rollouts
# don't require a code change.
_MODEL_ALIASES: dict[str, str] = {
    # Sonnet — Profile files default to 4.7. Older 4.6 alias kept so any
    # archived / external-pinned configs still map cleanly.
    "claude-sonnet-4.7": "claude-sonnet-4-5",
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
        on_assistant_chunk: AssistantChunkCallback | None = None,
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
        # Note: ``profile.mcp_servers`` (the logical-name list declared in
        # profile.md) is metadata only — the adapter does not auto-resolve
        # it. Concrete server configs arrive via the ``mcp_servers`` kwarg
        # below, populated by the Session Manager (e.g. orchestration_tools
        # builds the per-ticket TPM tool surface and passes it explicitly).

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
                # Collect TextBlocks for *this* AssistantMessage; this is
                # what gets streamed to channel consumers as one progress
                # chunk. The aggregated form (across all messages in the
                # turn) is still returned in RunResult.assistant_text.
                message_text_chunks: list[str] = []
                for block in event.content:
                    if isinstance(block, TextBlock):
                        message_text_chunks.append(block.text)
                    # ToolUseBlock / ThinkingBlock / etc. are intentionally
                    # ignored at this layer — Task #11+ will surface them.
                message_text = "".join(message_text_chunks)
                if message_text:
                    assistant_chunks.append(message_text)
                    if on_assistant_chunk is not None:
                        # Best-effort streaming. A failure in the consumer
                        # (e.g. Telegram outage) must not abort the SDK
                        # turn — log and continue. The final aggregate is
                        # still recoverable from RunResult.assistant_text.
                        try:
                            await on_assistant_chunk(message_text)
                        except Exception:
                            logger.exception(
                                "ClaudeAdapter: on_assistant_chunk callback "
                                "raised; continuing turn"
                            )
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

    async def render_history(
        self,
        session_id: str,
        store: "AgentStore",
    ) -> list[RenderedMessage]:
        """Read the JSONL transcript for a session and emit rendered turns.

        Steps:

        1. Look up the session row to get ``native_handle`` (the SDK's
           session_id, which is the JSONL filename stem).
        2. Glob ``~/.claude/projects/*/<native_handle>.jsonl`` to locate
           the file (cwd at session start is unknown without storing it).
        3. Walk the JSONL line-by-line, extracting visible text from
           ``user`` and ``assistant`` records. Skip ``thinking`` blocks
           and ``tool_use``/``tool_result`` blocks (they're operationally
           noisy for human display; leave them for a future "raw view"
           toggle).
        4. Return the messages oldest-first.

        Returns an empty list if the native handle is missing (session
        spawned but never sent a message), if the JSONL doesn't exist on
        disk, or if every line fails to parse.
        """
        row = await store.get_session(session_id)
        if row is None:
            return []
        native_handle = row.get("native_handle")
        if not native_handle:
            return []

        projects_dir = Path(os.path.expanduser("~/.claude/projects"))
        if not projects_dir.is_dir():
            return []

        # Glob across every project directory; the cwd at session start
        # is unknown to us. Use glob (not rglob) — JSONL files live one
        # level deep under projects/.
        matches = list(projects_dir.glob(f"*/{native_handle}.jsonl"))
        if not matches:
            return []

        jsonl_path = matches[0]
        messages: list[RenderedMessage] = []
        try:
            with jsonl_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rendered = _render_jsonl_record(record)
                    if rendered is not None:
                        messages.append(rendered)
        except OSError as e:
            logger.warning(
                "ClaudeAdapter.render_history: failed to read %s: %s",
                jsonl_path,
                e,
            )
            return []

        return messages


def _extract_visible_text(content: Any) -> str:
    """Pull human-visible text out of an SDK content payload.

    Content can be a plain string (older format) or a list of typed
    blocks (newer format). For block lists, only ``text`` blocks count;
    ``thinking`` / ``tool_use`` / ``tool_result`` are filtered out.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in (None, "text"):
                t = block.get("text") or ""
                if t:
                    chunks.append(t)
        return "".join(chunks)
    return ""


def _render_jsonl_record(record: dict) -> RenderedMessage | None:
    """Convert a single JSONL record into a :class:`RenderedMessage`, or None.

    Skips meta records (``queue-operation``, ``compact_boundary``,
    ``system``) and any record whose visible text is empty.
    """
    rec_type = record.get("type")
    if rec_type not in ("user", "assistant"):
        return None

    msg = record.get("message")
    if not isinstance(msg, dict):
        return None
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None

    text = _extract_visible_text(msg.get("content"))
    if not text:
        # Assistant turns that were nothing but thinking/tool_use lose
        # all visible text; surface a placeholder so the UI doesn't
        # silently swallow the turn entirely.
        if role == "assistant":
            return RenderedMessage(
                role="assistant",
                text="(tool calls / thinking only — no visible text)",
                timestamp=record.get("timestamp", ""),
            )
        return None

    return RenderedMessage(
        role=role,
        text=text,
        timestamp=record.get("timestamp", ""),
    )


__all__ = ["ClaudeAdapter"]
