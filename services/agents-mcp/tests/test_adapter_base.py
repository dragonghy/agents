"""Unit tests for the Adapter Protocol shape + supporting dataclasses.

Pure structural / wiring tests. No SDK calls, no DB, no async. Anything
that touches the Claude SDK lives in test_claude_adapter.py.
"""

from __future__ import annotations

import inspect

import pytest

from agents_mcp.adapters import (
    Adapter,
    Profile,
    RenderedMessage,
    RunResult,
    SessionMetadata,
    get_adapter,
)
from agents_mcp.adapters.claude_adapter import ClaudeAdapter


# ─── Profile dataclass ─────────────────────────────────────────────────────


class TestProfile:
    def test_required_fields_only(self):
        p = Profile(
            name="developer",
            runner_type="claude-sonnet-4.6",
            system_prompt="You are a developer.",
        )
        assert p.name == "developer"
        assert p.runner_type == "claude-sonnet-4.6"
        assert p.system_prompt == "You are a developer."
        # Optional fields default to empty.
        assert p.mcp_servers == ()
        assert p.skills == ()
        assert p.description == ""
        assert p.file_path == ""
        assert p.file_hash == ""

    def test_with_mcp_servers(self):
        p = Profile(
            name="tpm",
            runner_type="claude-sonnet-4.6",
            system_prompt="Coordinator.",
            mcp_servers=("agents", "agent-hub"),
        )
        assert p.mcp_servers == ("agents", "agent-hub")

    def test_is_frozen(self):
        p = Profile(
            name="qa",
            runner_type="claude-haiku",
            system_prompt="QA.",
        )
        with pytest.raises(Exception):
            # frozen dataclass — assignment must fail
            p.name = "other"  # type: ignore[misc]


# ─── SessionMetadata dataclass ─────────────────────────────────────────────


class TestSessionMetadata:
    def test_first_turn_shape(self):
        sm = SessionMetadata(
            session_id="sess_1",
            native_handle=None,
            runner_type="claude-sonnet-4.6",
        )
        assert sm.session_id == "sess_1"
        assert sm.native_handle is None
        assert sm.runner_type == "claude-sonnet-4.6"

    def test_resume_shape(self):
        sm = SessionMetadata(
            session_id="sess_1",
            native_handle="claude-internal-uuid",
            runner_type="claude-sonnet-4.6",
        )
        assert sm.native_handle == "claude-internal-uuid"

    def test_is_frozen(self):
        sm = SessionMetadata(
            session_id="sess_1", native_handle=None, runner_type="claude"
        )
        with pytest.raises(Exception):
            sm.session_id = "other"  # type: ignore[misc]


# ─── RunResult dataclass ───────────────────────────────────────────────────


class TestRunResult:
    def test_basic_construction(self):
        r = RunResult(
            assistant_text="hello",
            tokens_in=42,
            tokens_out=7,
            native_handle="abc-def",
        )
        assert r.assistant_text == "hello"
        assert r.tokens_in == 42
        assert r.tokens_out == 7
        assert r.native_handle == "abc-def"

    def test_is_mutable_for_in_place_edits(self):
        # RunResult is intentionally mutable (not frozen) so a future
        # streaming layer can append text incrementally if it wants to.
        r = RunResult(
            assistant_text="hi", tokens_in=1, tokens_out=1, native_handle="h"
        )
        r.assistant_text = "hello"
        assert r.assistant_text == "hello"


# ─── Adapter Protocol ──────────────────────────────────────────────────────


class TestAdapterProtocol:
    def test_run_signature(self):
        sig = inspect.signature(Adapter.run)
        params = list(sig.parameters.values())
        # Required positional params come first, in this order. Additional
        # keyword-only params (e.g. ``on_assistant_chunk`` for streaming)
        # are additive and not pinned here — adapter implementations may
        # introduce their own (e.g. ClaudeAdapter adds ``mcp_servers``,
        # ``allowed_tools``).
        positional_names = [
            p.name
            for p in params
            if p.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.POSITIONAL_ONLY,
            )
        ]
        assert positional_names == [
            "self",
            "profile",
            "session_metadata",
            "new_message_text",
            "store",
        ]
        # The streaming callback is part of the formalized Protocol — pin
        # its name + keyword-only kind so adapters that opt in stay in
        # sync with the contract.
        assert "on_assistant_chunk" in sig.parameters
        assert (
            sig.parameters["on_assistant_chunk"].kind
            == inspect.Parameter.KEYWORD_ONLY
        )

    def test_run_is_async(self):
        # Adapter.run is `async def ...: ...` — the underlying function
        # is a coroutine function, even though Protocols can be tricky.
        assert inspect.iscoroutinefunction(Adapter.run)

    def test_claude_adapter_implements_protocol_structurally(self):
        # Protocols rely on structural typing; we don't subclass Adapter.
        # We assert that ClaudeAdapter has a `run` async method with the
        # required positional param names. Optional keyword-only params
        # (e.g. ``mcp_servers``, ``allowed_tools`` for orchestration tool
        # wiring — see Phase 2.5) are additive and not enforced here.
        adapter = ClaudeAdapter()
        assert hasattr(adapter, "run")
        assert inspect.iscoroutinefunction(adapter.run)
        sig = inspect.signature(adapter.run)
        params = list(sig.parameters.keys())
        # Required positional params come first, in this order.
        assert params[:4] == [
            "profile",
            "session_metadata",
            "new_message_text",
            "store",
        ]

    def test_render_history_signature(self):
        sig = inspect.signature(Adapter.render_history)
        params = [p.name for p in sig.parameters.values()]
        assert params == ["self", "session_id", "store"]
        assert inspect.iscoroutinefunction(Adapter.render_history)

    def test_claude_adapter_implements_render_history(self):
        adapter = ClaudeAdapter()
        assert hasattr(adapter, "render_history")
        assert inspect.iscoroutinefunction(adapter.render_history)


# ─── RenderedMessage dataclass ─────────────────────────────────────────────


class TestRenderedMessage:
    def test_construction(self):
        m = RenderedMessage(role="user", text="hi")
        assert m.role == "user"
        assert m.text == "hi"
        assert m.timestamp == ""

    def test_with_timestamp(self):
        m = RenderedMessage(role="assistant", text="yo", timestamp="t0")
        assert m.timestamp == "t0"

    def test_is_frozen(self):
        m = RenderedMessage(role="user", text="hi")
        with pytest.raises(Exception):
            m.text = "edit"  # type: ignore[misc]


# ─── get_adapter factory ───────────────────────────────────────────────────


class TestGetAdapter:
    def test_claude_runner_returns_claude_adapter(self):
        a = get_adapter("claude-sonnet-4.6")
        assert isinstance(a, ClaudeAdapter)

    def test_claude_haiku_returns_claude_adapter(self):
        # Different model, same family → same adapter class.
        a = get_adapter("claude-haiku")
        assert isinstance(a, ClaudeAdapter)

    def test_bare_claude_runner(self):
        a = get_adapter("claude")
        assert isinstance(a, ClaudeAdapter)

    def test_openai_raises_not_implemented(self):
        with pytest.raises(NotImplementedError, match="OpenAI"):
            get_adapter("gpt-5")
        with pytest.raises(NotImplementedError, match="OpenAI"):
            get_adapter("openai-something")

    def test_gemini_raises_not_implemented(self):
        with pytest.raises(NotImplementedError, match="Gemini"):
            get_adapter("gemini-pro")

    def test_unknown_runner_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown runner_type"):
            get_adapter("llama-7b")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="non-empty"):
            get_adapter("")
