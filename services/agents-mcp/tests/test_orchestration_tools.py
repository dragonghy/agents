"""Tests for the in-process MCP tool server (orchestration_tools.py).

These tests exercise the four tool handlers (``spawn_subagent``,
``push_message``, ``post_comment``, ``mark_ticket_status``) directly via
the SDK's ``McpSdkServerConfig.instance`` — i.e. by invoking the MCP
``Server.call_tool`` callback that ``create_sdk_mcp_server`` registered.
This keeps the tests sync-friendly (no real LLM, no subprocess CLI).

Layered approach:

1. **Unit tests on tool handlers** — drive them through the MCP server's
   internal ``call_tool`` dispatcher with collaborator mocks.
2. **Server shape tests** — verify the four expected tool names are
   exposed by ``list_tools()`` and that ``McpSdkServerConfig.type == "sdk"``.
3. **Failure-path tests** — invalid status, unknown session, missing
   profile.

We avoid going through ``query()`` (the LLM path) entirely; that's covered
by the live demo script.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agents_mcp.adapters.base import RunResult
from agents_mcp.orchestration_tools import (
    TPM_TOOL_NAMES,
    build_tpm_tool_server,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeSessionManager:
    """Records calls; returns canned responses.

    The orchestration tools only call two SessionManager methods (``spawn``
    + ``append_message``), so the fake just stubs those.
    """

    def __init__(self):
        self.spawn_calls: list[dict] = []
        self.append_calls: list[dict] = []
        self.spawned_id_counter = 0
        self.spawn_should_raise: Exception | None = None
        self.append_should_raise: Exception | None = None
        self.canned_first_response = "first response from subagent"
        self.canned_append_response = "follow-up reply"

    async def spawn(self, **kwargs):
        self.spawn_calls.append(dict(kwargs))
        if self.spawn_should_raise is not None:
            raise self.spawn_should_raise
        self.spawned_id_counter += 1
        return {"id": f"sess_subagent_{self.spawned_id_counter}"}

    async def append_message(self, session_id: str, body: str) -> RunResult:
        self.append_calls.append({"session_id": session_id, "body": body})
        if self.append_should_raise is not None:
            raise self.append_should_raise
        # Distinguish "first turn after spawn" from "follow-up" by whether
        # this session id was just spawned.
        is_first_turn = any(
            session_id == f"sess_subagent_{i + 1}"
            for i in range(self.spawned_id_counter)
        ) and not any(
            c["session_id"] == session_id
            for c in self.append_calls[:-1]
        )
        text = (
            self.canned_first_response
            if is_first_turn
            else self.canned_append_response
        )
        return RunResult(
            assistant_text=text,
            tokens_in=100,
            tokens_out=50,
            native_handle="fake-native",
        )


class _FakeStore:
    """Minimal placeholder. The tools don't call store directly in v1."""

    pass


class _FakeTaskClient:
    def __init__(self):
        self.add_comment_calls: list[dict] = []
        self.update_ticket_calls: list[dict] = []
        self.add_comment_should_raise: Exception | None = None
        self.update_ticket_should_raise: Exception | None = None
        self.next_comment_id = 1001

    async def add_comment(self, module, module_id, comment, author=None):
        self.add_comment_calls.append(
            {
                "module": module,
                "module_id": module_id,
                "comment": comment,
                "author": author,
            }
        )
        if self.add_comment_should_raise is not None:
            raise self.add_comment_should_raise
        cid = self.next_comment_id
        self.next_comment_id += 1
        return cid

    async def update_ticket(self, ticket_id, **kwargs):
        self.update_ticket_calls.append({"ticket_id": ticket_id, **kwargs})
        if self.update_ticket_should_raise is not None:
            raise self.update_ticket_should_raise
        return True


def _build_server(parent_session_id="sess_tpm_1", bound_ticket_id=42):
    sm = _FakeSessionManager()
    store = _FakeStore()
    tc = _FakeTaskClient()
    cfg = build_tpm_tool_server(
        session_manager=sm,
        store=store,
        task_client=tc,
        parent_session_id=parent_session_id,
        bound_ticket_id=bound_ticket_id,
    )
    return cfg, sm, store, tc


async def _call_tool(cfg, name: str, arguments: dict) -> tuple[list[dict], bool]:
    """Invoke a registered MCP tool via the in-process Server.

    The mcp.server.Server stores registered handlers in
    ``request_handlers`` / ``notification_handlers`` keyed by JSON-RPC
    method types. Easier: call the ``call_tool`` method on the lowlevel
    Server — but the SDK registers the handler via decorator, so we
    extract it from the server's internal map.
    """
    server = cfg["instance"]
    # mcp.server.lowlevel.Server stores handlers in `request_handlers`
    # mapped by request type. The decorator @server.call_tool() registers
    # a handler for CallToolRequest. We can find the handler and call it
    # via the lowlevel API, but it's simpler to call the underlying
    # tool functions through the dispatcher we know exists.
    from mcp.types import CallToolRequest, CallToolRequestParams

    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    handler = server.request_handlers[CallToolRequest]
    result = await handler(request)
    # CallToolResult is wrapped in a ServerResult; unwrap.
    inner = result.root if hasattr(result, "root") else result
    content = []
    for c in inner.content:
        # Each c is a TextContent / ImageContent / ... pydantic model
        content.append(c.model_dump())
    return content, bool(getattr(inner, "isError", False))


# ─── Server shape ────────────────────────────────────────────────────────────


class TestServerShape:
    def test_returns_sdk_config(self):
        cfg, *_ = _build_server()
        assert cfg["type"] == "sdk"
        assert cfg["name"].startswith("orchestration_tpm_")
        assert "instance" in cfg

    def test_exposes_four_tools(self):
        async def _t():
            cfg, *_ = _build_server()
            server = cfg["instance"]
            from mcp.types import ListToolsRequest

            handler = server.request_handlers[ListToolsRequest]
            req = ListToolsRequest(method="tools/list")
            result = await handler(req)
            inner = result.root if hasattr(result, "root") else result
            names = sorted(t.name for t in inner.tools)
            assert names == sorted(TPM_TOOL_NAMES)
            assert names == sorted(
                [
                    "mark_ticket_status",
                    "post_comment",
                    "push_message",
                    "spawn_subagent",
                ]
            )

        run(_t())


# ─── spawn_subagent ─────────────────────────────────────────────────────────


class TestSpawnSubagent:
    def test_happy_path_spawns_and_runs_first_turn(self):
        async def _t():
            cfg, sm, _store, _tc = _build_server(
                parent_session_id="sess_tpm_xyz", bound_ticket_id=42
            )
            content, is_error = await _call_tool(
                cfg,
                "spawn_subagent",
                {
                    "profile_name": "architect",
                    "initial_prompt": "Diagnose this slow query.",
                    "ticket_id": 42,
                },
            )
            assert is_error is False
            # Should have called sm.spawn once with the expected args.
            assert len(sm.spawn_calls) == 1
            call = sm.spawn_calls[0]
            assert call["profile_name"] == "architect"
            assert call["binding_kind"] == "ticket-subagent"
            assert call["ticket_id"] == 42
            assert call["parent_session_id"] == "sess_tpm_xyz"

            # Should have called sm.append_message once for the first turn.
            assert len(sm.append_calls) == 1
            assert sm.append_calls[0]["body"] == "Diagnose this slow query."

            # Reply payload should include session_id + first_response.
            payload = json.loads(content[0]["text"])
            assert payload["session_id"] == "sess_subagent_1"
            assert payload["profile"] == "architect"
            assert payload["first_response"] == "first response from subagent"
            assert payload["tokens_in"] == 100
            assert payload["tokens_out"] == 50

        run(_t())

    def test_unknown_profile_returns_error_payload(self):
        async def _t():
            cfg, sm, _store, _tc = _build_server()
            sm.spawn_should_raise = FileNotFoundError(
                "profile.md not found"
            )
            content, is_error = await _call_tool(
                cfg,
                "spawn_subagent",
                {
                    "profile_name": "nonsense",
                    "initial_prompt": "x",
                    "ticket_id": 5,
                },
            )
            assert is_error is True
            assert "spawn_subagent" in content[0]["text"]
            assert "nonsense" in content[0]["text"]

        run(_t())

    def test_uses_passed_ticket_id_not_just_bound_id(self):
        # In v1 we deliberately let the TPM pass any ticket_id (permissive
        # design). Verify that the arg is forwarded unchanged.
        async def _t():
            cfg, sm, _store, _tc = _build_server(bound_ticket_id=999)
            await _call_tool(
                cfg,
                "spawn_subagent",
                {
                    "profile_name": "developer",
                    "initial_prompt": "y",
                    "ticket_id": 7,  # different from bound_ticket_id
                },
            )
            assert sm.spawn_calls[0]["ticket_id"] == 7

        run(_t())


# ─── push_message ───────────────────────────────────────────────────────────


class TestPushMessage:
    def test_happy_path(self):
        async def _t():
            cfg, sm, _store, _tc = _build_server()
            # Pre-spawn so the helper distinguishes first-vs-follow-up.
            sm.spawned_id_counter = 1  # simulate sess_subagent_1 exists
            sm.append_calls.append(
                {"session_id": "sess_subagent_1", "body": "first"}
            )
            content, is_error = await _call_tool(
                cfg,
                "push_message",
                {"session_id": "sess_subagent_1", "body": "any update?"},
            )
            assert is_error is False
            # The new call appended.
            assert sm.append_calls[-1] == {
                "session_id": "sess_subagent_1",
                "body": "any update?",
            }
            payload = json.loads(content[0]["text"])
            assert payload["session_id"] == "sess_subagent_1"
            assert payload["response"] == "follow-up reply"

        run(_t())

    def test_unknown_session_returns_error(self):
        async def _t():
            cfg, sm, _store, _tc = _build_server()
            sm.append_should_raise = LookupError("unknown session id")
            content, is_error = await _call_tool(
                cfg,
                "push_message",
                {"session_id": "sess_missing", "body": "?"},
            )
            assert is_error is True
            assert "push_message" in content[0]["text"]
            assert "sess_missing" in content[0]["text"]

        run(_t())

    def test_closed_session_returns_error(self):
        async def _t():
            cfg, sm, _store, _tc = _build_server()
            sm.append_should_raise = RuntimeError(
                "session 'sess_x' is closed; cannot append messages"
            )
            content, is_error = await _call_tool(
                cfg,
                "push_message",
                {"session_id": "sess_x", "body": "?"},
            )
            assert is_error is True
            assert "closed" in content[0]["text"]

        run(_t())


# ─── post_comment ───────────────────────────────────────────────────────────


class TestPostComment:
    def test_happy_path(self):
        async def _t():
            cfg, _sm, _store, tc = _build_server(
                parent_session_id="sess_tpm_a"
            )
            content, is_error = await _call_tool(
                cfg,
                "post_comment",
                {"ticket_id": 42, "body": "## Status\nKickoff received."},
            )
            assert is_error is False
            assert len(tc.add_comment_calls) == 1
            call = tc.add_comment_calls[0]
            assert call["module"] == "ticket"
            assert call["module_id"] == 42
            assert "Kickoff received" in call["comment"]
            # author is tagged with the TPM session id so we can attribute
            # comments back to a session (and the comment-dispatch
            # self-feedback skip can detect them).
            assert call["author"] == "tpm:sess_tpm_a"

            payload = json.loads(content[0]["text"])
            assert payload["ticket_id"] == 42
            assert payload["ok"] is True
            assert isinstance(payload["comment_id"], int)

        run(_t())

    def test_taskclient_failure_returns_error(self):
        async def _t():
            cfg, _sm, _store, tc = _build_server()
            tc.add_comment_should_raise = RuntimeError("DB unreachable")
            content, is_error = await _call_tool(
                cfg,
                "post_comment",
                {"ticket_id": 42, "body": "x"},
            )
            assert is_error is True
            assert "DB unreachable" in content[0]["text"]

        run(_t())


# ─── mark_ticket_status ─────────────────────────────────────────────────────


class TestMarkTicketStatus:
    def test_status_zero_calls_update(self):
        async def _t():
            cfg, _sm, _store, tc = _build_server()
            content, is_error = await _call_tool(
                cfg,
                "mark_ticket_status",
                {"ticket_id": 42, "status": 0},
            )
            assert is_error is False
            assert tc.update_ticket_calls == [
                {"ticket_id": 42, "status": 0}
            ]
            payload = json.loads(content[0]["text"])
            assert payload["status"] == 0
            assert payload["ok"] is True

        run(_t())

    def test_status_two_is_rejected(self):
        async def _t():
            cfg, _sm, _store, tc = _build_server()
            content, is_error = await _call_tool(
                cfg,
                "mark_ticket_status",
                {"ticket_id": 42, "status": 2},
            )
            assert is_error is True
            assert "2" in content[0]["text"]
            assert tc.update_ticket_calls == []

        run(_t())

    def test_invalid_status_is_rejected(self):
        async def _t():
            cfg, _sm, _store, tc = _build_server()
            content, is_error = await _call_tool(
                cfg,
                "mark_ticket_status",
                {"ticket_id": 42, "status": 99},
            )
            assert is_error is True
            assert tc.update_ticket_calls == []

        run(_t())

    @pytest.mark.parametrize("status", [-1, 0, 1, 3, 4])
    def test_all_valid_statuses_pass_through(self, status):
        async def _t():
            cfg, _sm, _store, tc = _build_server()
            _, is_error = await _call_tool(
                cfg,
                "mark_ticket_status",
                {"ticket_id": 42, "status": status},
            )
            assert is_error is False
            assert tc.update_ticket_calls[-1]["status"] == status

        run(_t())

    def test_taskclient_failure_returns_error(self):
        async def _t():
            cfg, _sm, _store, tc = _build_server()
            tc.update_ticket_should_raise = RuntimeError(
                "Leantime unreachable"
            )
            content, is_error = await _call_tool(
                cfg,
                "mark_ticket_status",
                {"ticket_id": 42, "status": 1},
            )
            assert is_error is True
            assert "Leantime unreachable" in content[0]["text"]

        run(_t())
