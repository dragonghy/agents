"""Tests for ClaudeAdapter.

Two layers:

1. **Mock-based wiring tests** (default, fast, no network) — patch
   ``claude_agent_sdk.query`` with an async generator that yields realistic
   ``AssistantMessage`` / ``ResultMessage`` events. Verify:
     - System prompt is passed via ``ClaudeAgentOptions.system_prompt``
     - Resume on second turn passes ``ClaudeAgentOptions.resume``
     - Assistant text is the concatenation of all ``TextBlock`` content
     - native_handle is captured + persisted via store
     - Cost is reported via store
     - Token aggregation handles ``cache_*_input_tokens``
     - Error result raises

2. **Live test** (`@pytest.mark.live`, skipped by default) — actually
   calls Anthropic with a tiny prompt; asserts the response contains
   "hello" and tokens > 0. Run with:
       pytest -m live tests/test_claude_adapter.py
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import patch

import pytest

from agents_mcp.adapters.base import (
    Profile,
    RenderedMessage,
    RunResult,
    SessionMetadata,
)
from agents_mcp.adapters.claude_adapter import (
    ClaudeAdapter,
    _extract_tokens,
    _extract_visible_text,
    _render_jsonl_record,
    _resolve_model,
)
from agents_mcp.store import AgentStore


# ─── Helpers ───────────────────────────────────────────────────────────────


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-claude-adapter.db")


async def _store(db_path: str) -> AgentStore:
    s = AgentStore(db_path)
    await s.initialize()
    return s


def _fake_assistant_msg(
    text: str, session_id: str = "sdk-sess-abc", usage: dict | None = None
):
    """Build a minimally realistic AssistantMessage.

    The real SDK class is a dataclass; we use the same import for type
    correctness inside the adapter's ``isinstance`` checks.
    """
    from claude_agent_sdk import AssistantMessage, TextBlock

    return AssistantMessage(
        content=[TextBlock(text=text)],
        model="claude-sonnet-4-5",
        parent_tool_use_id=None,
        error=None,
        usage=usage,
        message_id="msg_1",
        stop_reason=None,
        session_id=session_id,
        uuid="uuid-1",
    )


def _fake_result_msg(
    session_id: str = "sdk-sess-abc",
    usage: dict | None = None,
    is_error: bool = False,
    errors: list[str] | None = None,
):
    from claude_agent_sdk import ResultMessage

    return ResultMessage(
        subtype="success" if not is_error else "error",
        duration_ms=100,
        duration_api_ms=80,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        stop_reason="end_turn",
        total_cost_usd=0.001,
        usage=usage or {"input_tokens": 10, "output_tokens": 5},
        result=None,
        structured_output=None,
        model_usage=None,
        permission_denials=None,
        errors=errors,
        uuid="uuid-result",
    )


def _stream_factory(events: list[Any]):
    """Build an async generator function that yields the given events.

    Mimics the shape of ``claude_agent_sdk.query`` — a callable returning
    an async iterator. We also stash the call args so tests can assert
    on what the adapter passed.
    """
    captured = {"calls": []}

    async def fake_query(*, prompt, options=None, transport=None):
        captured["calls"].append({"prompt": prompt, "options": options})
        for e in events:
            yield e

    return fake_query, captured


# ─── _resolve_model unit tests ─────────────────────────────────────────────


class TestResolveModel:
    def test_known_alias_maps(self):
        assert _resolve_model("claude-sonnet-4.6") == "claude-sonnet-4-5"
        assert _resolve_model("claude-haiku") == "claude-haiku-4-5"

    def test_bare_claude_returns_none(self):
        # Lets the SDK pick its default model.
        assert _resolve_model("claude") is None

    def test_unknown_passes_through(self):
        # User can specify a full model id directly.
        assert _resolve_model("claude-sonnet-5-1-future") == (
            "claude-sonnet-5-1-future"
        )


# ─── _extract_tokens unit tests ────────────────────────────────────────────


class TestExtractTokens:
    def test_none_usage_returns_zero(self):
        assert _extract_tokens(None) == (0, 0)

    def test_empty_dict_returns_zero(self):
        assert _extract_tokens({}) == (0, 0)

    def test_basic_input_output(self):
        assert _extract_tokens({"input_tokens": 100, "output_tokens": 50}) == (
            100,
            50,
        )

    def test_sums_cache_tokens_into_input(self):
        usage = {
            "input_tokens": 10,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 800,
            "output_tokens": 20,
        }
        # 10 + 200 + 800 = 1010
        assert _extract_tokens(usage) == (1010, 20)

    def test_handles_none_values(self):
        # Some SDK versions emit None for missing keys instead of omitting.
        usage = {
            "input_tokens": None,
            "output_tokens": 5,
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None,
        }
        assert _extract_tokens(usage) == (0, 5)


# ─── ClaudeAdapter.run() — first turn ──────────────────────────────────────


class TestFirstTurn:
    def test_first_turn_captures_session_id_and_persists(self, db_path):
        async def _t():
            store = await _store(db_path)
            await store.create_session(
                session_id="sess_1",
                profile_name="developer",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.6",
            )

            events = [
                _fake_assistant_msg("Hello, ", session_id="sdk-xyz"),
                _fake_assistant_msg("world!", session_id="sdk-xyz"),
                _fake_result_msg(
                    session_id="sdk-xyz",
                    usage={
                        "input_tokens": 42,
                        "output_tokens": 7,
                        "cache_read_input_tokens": 100,
                    },
                ),
            ]
            fake_query, captured = _stream_factory(events)

            adapter = ClaudeAdapter()
            profile = Profile(
                name="developer",
                runner_type="claude-sonnet-4.6",
                system_prompt="You are a developer.",
            )
            sm = SessionMetadata(
                session_id="sess_1",
                native_handle=None,
                runner_type="claude-sonnet-4.6",
            )

            with patch(
                "agents_mcp.adapters.claude_adapter.query", fake_query
            ):
                result = await adapter.run(
                    profile=profile,
                    session_metadata=sm,
                    new_message_text="hi there",
                    store=store,
                )

            # 1. Result shape
            assert isinstance(result, RunResult)
            assert result.assistant_text == "Hello, world!"
            assert result.native_handle == "sdk-xyz"
            # tokens_in = 42 + 100 (cache_read) = 142
            assert result.tokens_in == 142
            assert result.tokens_out == 7

            # 2. Wiring: system prompt + no resume + prompt text
            assert len(captured["calls"]) == 1
            call = captured["calls"][0]
            assert call["prompt"] == "hi there"
            opts = call["options"]
            assert opts.system_prompt == "You are a developer."
            assert opts.resume is None
            # runner_type "claude-sonnet-4.6" → SDK alias "claude-sonnet-4-5"
            assert opts.model == "claude-sonnet-4-5"
            assert opts.permission_mode == "bypassPermissions"

            # 3. Side effects: native_handle + cost persisted
            sess = await store.get_session("sess_1")
            assert sess["native_handle"] == "sdk-xyz"
            assert sess["cost_tokens_in"] == 142
            assert sess["cost_tokens_out"] == 7

            await store.close()

        run(_t())

    def test_resume_turn_passes_native_handle(self, db_path):
        async def _t():
            store = await _store(db_path)
            await store.create_session(
                session_id="sess_2",
                profile_name="developer",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.6",
                native_handle="sdk-existing",
            )

            events = [
                _fake_assistant_msg("Resumed.", session_id="sdk-existing"),
                _fake_result_msg(
                    session_id="sdk-existing",
                    usage={"input_tokens": 5, "output_tokens": 2},
                ),
            ]
            fake_query, captured = _stream_factory(events)

            adapter = ClaudeAdapter()
            profile = Profile(
                name="developer",
                runner_type="claude-sonnet-4.6",
                system_prompt="dev",
            )
            sm = SessionMetadata(
                session_id="sess_2",
                native_handle="sdk-existing",
                runner_type="claude-sonnet-4.6",
            )

            with patch(
                "agents_mcp.adapters.claude_adapter.query", fake_query
            ):
                result = await adapter.run(
                    profile=profile,
                    session_metadata=sm,
                    new_message_text="follow up",
                    store=store,
                )

            assert result.native_handle == "sdk-existing"
            assert result.assistant_text == "Resumed."

            # ClaudeAgentOptions.resume must be the existing handle.
            opts = captured["calls"][0]["options"]
            assert opts.resume == "sdk-existing"

            # Cost is *added*, not overwritten — second turn appends.
            sess = await store.get_session("sess_2")
            assert sess["cost_tokens_in"] == 5
            assert sess["cost_tokens_out"] == 2

            await store.close()

        run(_t())

    def test_error_result_raises(self, db_path):
        async def _t():
            store = await _store(db_path)
            await store.create_session(
                session_id="sess_err",
                profile_name="developer",
                binding_kind="standalone",
                runner_type="claude",
            )

            events = [
                _fake_result_msg(
                    session_id="sdk-err",
                    is_error=True,
                    errors=["rate_limited"],
                ),
            ]
            fake_query, _ = _stream_factory(events)

            adapter = ClaudeAdapter()
            profile = Profile(
                name="developer",
                runner_type="claude",
                system_prompt="dev",
            )
            sm = SessionMetadata(
                session_id="sess_err",
                native_handle=None,
                runner_type="claude",
            )

            with patch(
                "agents_mcp.adapters.claude_adapter.query", fake_query
            ):
                with pytest.raises(RuntimeError, match="error result"):
                    await adapter.run(
                        profile=profile,
                        session_metadata=sm,
                        new_message_text="hi",
                        store=store,
                    )

            await store.close()

        run(_t())

    def test_no_session_id_emitted_raises(self, db_path):
        async def _t():
            store = await _store(db_path)
            await store.create_session(
                session_id="sess_nosid",
                profile_name="developer",
                binding_kind="standalone",
                runner_type="claude",
            )

            # AssistantMessage with no session_id, ResultMessage missing too —
            # construct ResultMessage with an empty session_id which the
            # adapter treats as "unset".
            from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

            events = [
                AssistantMessage(
                    content=[TextBlock(text="hi")],
                    model="claude-sonnet-4-5",
                    parent_tool_use_id=None,
                    error=None,
                    usage=None,
                    message_id="m",
                    stop_reason=None,
                    session_id=None,
                    uuid="u",
                ),
                ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="",  # empty string → falsy → not captured
                    stop_reason="end_turn",
                    total_cost_usd=0,
                    usage={"input_tokens": 1, "output_tokens": 1},
                    result=None,
                    structured_output=None,
                    model_usage=None,
                    permission_denials=None,
                    errors=None,
                    uuid="u2",
                ),
            ]
            fake_query, _ = _stream_factory(events)

            adapter = ClaudeAdapter()
            profile = Profile(
                name="developer",
                runner_type="claude",
                system_prompt="dev",
            )
            sm = SessionMetadata(
                session_id="sess_nosid",
                native_handle=None,
                runner_type="claude",
            )

            with patch(
                "agents_mcp.adapters.claude_adapter.query", fake_query
            ):
                with pytest.raises(RuntimeError, match="never emitted"):
                    await adapter.run(
                        profile=profile,
                        session_metadata=sm,
                        new_message_text="hi",
                        store=store,
                    )

            await store.close()

        run(_t())

    def test_profile_mcp_servers_metadata_does_not_auto_wire(
        self, db_path, caplog
    ):
        """``profile.mcp_servers`` is metadata only (logical-name list).

        The adapter must NOT auto-resolve those names into SDK-side MCP
        configs — concrete configs arrive only via the explicit
        ``mcp_servers=`` kwarg from the SessionManager. The deferred-
        wiring warning that used to fire here was removed in PR #38
        once Phase 2.5 finalized the wiring contract; we now assert the
        absence of that warning so a future regression doesn't quietly
        re-introduce it.
        """
        async def _t():
            store = await _store(db_path)
            await store.create_session(
                session_id="sess_mcp",
                profile_name="tpm",
                binding_kind="standalone",
                runner_type="claude",
            )

            events = [
                _fake_assistant_msg("ok", session_id="sdk-mcp"),
                _fake_result_msg(session_id="sdk-mcp"),
            ]
            fake_query, captured = _stream_factory(events)

            adapter = ClaudeAdapter()
            profile = Profile(
                name="tpm",
                runner_type="claude",
                system_prompt="tpm",
                mcp_servers=("agents", "agent-hub"),
            )
            sm = SessionMetadata(
                session_id="sess_mcp",
                native_handle=None,
                runner_type="claude",
            )

            with patch(
                "agents_mcp.adapters.claude_adapter.query", fake_query
            ):
                import logging as _logging

                with caplog.at_level(
                    _logging.INFO, logger="agents_mcp.adapters.claude_adapter"
                ):
                    await adapter.run(
                        profile=profile,
                        session_metadata=sm,
                        new_message_text="hi",
                        store=store,
                    )

            # No mcp_servers kwarg passed → SDK options has empty mcp dict.
            opts = captured["calls"][0]["options"]
            assert opts.mcp_servers == {}

            # The retired "deferred wiring" warning must NOT reappear.
            assert not any(
                "MCP wiring is not yet implemented" in r.message
                for r in caplog.records
            ), f"deferred-wiring warning leaked back in: {[r.message for r in caplog.records]}"

            await store.close()

        run(_t())


# ─── Live test (real Anthropic call) ───────────────────────────────────────


@pytest.mark.live
def test_live_hello_world(tmp_path):
    """End-to-end smoke: real Anthropic call, real tokens.

    Skipped by default. Run with:
        pytest -m live services/agents-mcp/tests/test_claude_adapter.py
    Requires ``ANTHROPIC_API_KEY`` (or whatever auth the SDK picks up;
    `claude` CLI login also works).

    Assertions are loose — model nondeterminism means we can't
    string-match exactly. We just check:
      - response contains "hello" (case-insensitive)
      - tokens_in > 0 and tokens_out > 0
      - native_handle is populated
    """
    if not (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.path.exists(
            os.path.expanduser("~/.claude/.credentials.json")
        )
    ):
        pytest.skip(
            "no ANTHROPIC_API_KEY or ~/.claude/.credentials.json; "
            "live test cannot authenticate"
        )

    async def _t():
        store = AgentStore(str(tmp_path / "live.db"))
        await store.initialize()
        await store.create_session(
            session_id="sess_live",
            profile_name="tester",
            binding_kind="standalone",
            runner_type="claude-haiku",
        )

        adapter = ClaudeAdapter()
        profile = Profile(
            name="tester",
            # Haiku for speed + cost.
            runner_type="claude-haiku",
            system_prompt=(
                "You are a tiny test assistant. Reply with one word only."
            ),
        )
        sm = SessionMetadata(
            session_id="sess_live",
            native_handle=None,
            runner_type="claude-haiku",
        )

        result = await adapter.run(
            profile=profile,
            session_metadata=sm,
            new_message_text=(
                "Say 'hello world' and nothing else. No punctuation."
            ),
            store=store,
        )

        assert "hello" in result.assistant_text.lower(), result.assistant_text
        assert result.tokens_in > 0
        assert result.tokens_out > 0
        assert result.native_handle  # non-empty

        # Persisted side effects
        sess = await store.get_session("sess_live")
        assert sess["native_handle"] == result.native_handle
        assert sess["cost_tokens_in"] == result.tokens_in
        assert sess["cost_tokens_out"] == result.tokens_out

        await store.close()

    run(_t())


# ─── render_history (Task #18 Part B) ──────────────────────────────────────


class TestExtractVisibleText:
    def test_string_input(self):
        assert _extract_visible_text("hello") == "hello"

    def test_list_with_text_block(self):
        assert _extract_visible_text([{"type": "text", "text": "hi"}]) == "hi"

    def test_list_filters_thinking(self):
        # Thinking + text → only text shows.
        blocks = [
            {"type": "thinking", "thinking": "secret"},
            {"type": "text", "text": "visible"},
        ]
        assert _extract_visible_text(blocks) == "visible"

    def test_list_filters_tool_use(self):
        blocks = [
            {"type": "tool_use", "name": "Bash", "input": {}},
            {"type": "text", "text": "after-tool"},
        ]
        assert _extract_visible_text(blocks) == "after-tool"

    def test_unknown_returns_empty(self):
        assert _extract_visible_text(None) == ""
        assert _extract_visible_text(42) == ""


class TestRenderJsonlRecord:
    def test_user_text(self):
        rec = {
            "type": "user",
            "message": {"role": "user", "content": "hello"},
            "timestamp": "2026-05-03T10:00:00Z",
        }
        m = _render_jsonl_record(rec)
        assert m is not None
        assert m.role == "user"
        assert m.text == "hello"
        assert m.timestamp == "2026-05-03T10:00:00Z"

    def test_assistant_text_blocks(self):
        rec = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "yo"}],
            },
        }
        m = _render_jsonl_record(rec)
        assert m is not None
        assert m.role == "assistant"
        assert m.text == "yo"

    def test_assistant_tool_only_surfaces_tool_calls(self):
        """Tool-only assistant turns now keep ``text=""`` and surface
        the calls structurally on ``tool_calls`` (the legacy
        ``"(tool calls / thinking only — no visible text)"`` placeholder
        was retired 2026-05-04 — UIs should render ``tool_calls`` directly).
        """
        rec = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    }
                ],
            },
        }
        m = _render_jsonl_record(rec)
        assert m is not None
        assert m.role == "assistant"
        assert m.text == ""
        assert len(m.tool_calls) == 1
        assert m.tool_calls[0].name == "Bash"
        assert m.tool_calls[0].input == {"command": "ls"}
        assert m.tool_calls[0].id == "tu_1"

    def test_user_empty_returns_none(self):
        rec = {
            "type": "user",
            "message": {"role": "user", "content": ""},
        }
        assert _render_jsonl_record(rec) is None

    def test_queue_op_record_skipped(self):
        rec = {"type": "queue-operation", "operation": "enqueue"}
        assert _render_jsonl_record(rec) is None

    def test_system_record_skipped(self):
        rec = {"type": "system", "message": {"role": "system", "content": "x"}}
        assert _render_jsonl_record(rec) is None


class TestRenderHistory:
    def test_no_native_handle_returns_empty(self, db_path):
        async def _t():
            s = await _store(db_path)
            await s.create_session(
                session_id="sess_a",
                profile_name="secretary",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.7",
            )
            adapter = ClaudeAdapter()
            out = await adapter.render_history("sess_a", s)
            assert out == []
            await s.close()

        run(_t())

    def test_unknown_session_returns_empty(self, db_path):
        async def _t():
            s = await _store(db_path)
            adapter = ClaudeAdapter()
            out = await adapter.render_history("sess_bogus", s)
            assert out == []
            await s.close()

        run(_t())

    def test_reads_jsonl(self, db_path, tmp_path, monkeypatch):
        async def _t():
            s = await _store(db_path)
            await s.create_session(
                session_id="sess_b",
                profile_name="secretary",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.7",
                native_handle="native-xyz",
            )

            # Build a fake projects dir + jsonl.
            projects = tmp_path / "claude_projects"
            project_dir = projects / "-some-cwd"
            project_dir.mkdir(parents=True)
            jsonl = project_dir / "native-xyz.jsonl"
            import json as _json

            jsonl.write_text(
                "\n".join(
                    [
                        _json.dumps({"type": "queue-operation"}),  # filtered
                        _json.dumps(
                            {
                                "type": "user",
                                "message": {"role": "user", "content": "hi"},
                                "timestamp": "t0",
                            }
                        ),
                        _json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "content": [{"type": "text", "text": "hello"}],
                                },
                                "timestamp": "t1",
                            }
                        ),
                    ]
                )
                + "\n"
            )

            # Redirect ~/.claude/projects to our tmp dir.
            monkeypatch.setenv("HOME", str(tmp_path))
            (tmp_path / ".claude").mkdir(exist_ok=True)
            (tmp_path / ".claude" / "projects").symlink_to(projects)

            adapter = ClaudeAdapter()
            out = await adapter.render_history("sess_b", s)
            assert len(out) == 2
            assert out[0].role == "user"
            assert out[0].text == "hi"
            assert out[0].timestamp == "t0"
            assert out[1].role == "assistant"
            assert out[1].text == "hello"
            await s.close()

        run(_t())

    def test_tool_use_paired_with_tool_result(
        self, db_path, tmp_path, monkeypatch
    ):
        """Tool calls + their results in the same JSONL stream pair up.

        Regression for the "(tool calls / thinking only — no visible
        text)" placeholder bug — UI users reported they couldn't see
        what the agent did mid-conversation. The adapter now surfaces
        ``tool_use`` blocks structurally on the assistant message and
        pairs in the matching ``tool_result`` content.
        """

        async def _t():
            s = await _store(db_path)
            await s.create_session(
                session_id="sess_tools",
                profile_name="secretary",
                binding_kind="standalone",
                runner_type="claude-sonnet-4.7",
                native_handle="native-tools",
            )

            projects = tmp_path / "claude_projects"
            project_dir = projects / "-some-cwd"
            project_dir.mkdir(parents=True)
            jsonl = project_dir / "native-tools.jsonl"
            import json as _json

            jsonl.write_text(
                "\n".join(
                    [
                        # Assistant turn: text + tool_use
                        _json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "content": [
                                        {"type": "text", "text": "Let me check."},
                                        {
                                            "type": "tool_use",
                                            "id": "tu_a",
                                            "name": "Bash",
                                            "input": {"command": "ls"},
                                        },
                                    ],
                                },
                                "timestamp": "t0",
                            }
                        ),
                        # User turn carrying tool_result for tu_a
                        _json.dumps(
                            {
                                "type": "user",
                                "message": {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "tool_result",
                                            "tool_use_id": "tu_a",
                                            "content": "file1.txt\nfile2.txt",
                                            "is_error": False,
                                        }
                                    ],
                                },
                                "timestamp": "t1",
                            }
                        ),
                        # Assistant turn: text only (no tools)
                        _json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "content": [{"type": "text", "text": "Done."}],
                                },
                                "timestamp": "t2",
                            }
                        ),
                    ]
                )
                + "\n"
            )

            monkeypatch.setenv("HOME", str(tmp_path))
            (tmp_path / ".claude").mkdir(exist_ok=True)
            (tmp_path / ".claude" / "projects").symlink_to(projects)

            adapter = ClaudeAdapter()
            out = await adapter.render_history("sess_tools", s)
            # 2 assistant messages emitted (the user-only-tool_result
            # turn doesn't emit its own message — it patches into the
            # earlier assistant message's tool_calls).
            assert len(out) == 2

            first = out[0]
            assert first.role == "assistant"
            assert first.text == "Let me check."
            assert len(first.tool_calls) == 1
            tc = first.tool_calls[0]
            assert tc.id == "tu_a"
            assert tc.name == "Bash"
            assert tc.input == {"command": "ls"}
            # Result was paired in from the later user turn.
            assert tc.result == "file1.txt\nfile2.txt"
            assert tc.is_error is False

            second = out[1]
            assert second.text == "Done."
            assert second.tool_calls == ()

            await s.close()

        run(_t())
