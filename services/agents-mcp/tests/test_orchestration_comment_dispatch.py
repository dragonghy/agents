"""Tests for orchestration v1 comment-driven TPM dispatch.

Hermetic. We mock the SessionManager at the ``append_message`` boundary
(it's the only collaborator we don't want to actually exercise — the
real one would load Profile + go through the Adapter, which would touch
the LLM). The real :class:`AgentStore` is used so the
``get_active_tpm_for_ticket`` lookup logic is exercised end-to-end.

Style mirrors the rest of the orchestration v1 tests: sync wrapper +
local ``run()`` helper, no pytest-asyncio dep.
"""

from __future__ import annotations

import asyncio

import pytest

from agents_mcp.orchestration_comment_dispatch import (
    _format_comment_for_tpm,
    dispatch_comment_to_tpm,
)
from agents_mcp.store import AgentStore


# ── Fixtures / helpers ─────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-comment-dispatch.db")


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _make_store(db_path: str) -> AgentStore:
    s = AgentStore(db_path)
    await s.initialize()
    return s


async def _seed_active_tpm(
    store: AgentStore, *, session_id: str, ticket_id: int
) -> dict:
    """Insert an active TPM session row directly via the store.

    We don't need :class:`SessionManager` here because the comment
    dispatcher only reads sessions; it doesn't load profiles. Going
    direct keeps the test independent of the SessionManager and
    profile_loader code paths.
    """
    return await store.create_session(
        session_id=session_id,
        profile_name="tpm",
        binding_kind="ticket-subagent",
        runner_type="claude-sonnet-4.6",
        ticket_id=ticket_id,
    )


class _FakeSessionManager:
    """Records ``append_message`` calls. Mirrors the real interface."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def append_message(self, session_id: str, message_text: str):
        self.calls.append((session_id, message_text))
        # Real SessionManager returns a RunResult; the comment dispatcher
        # ignores the return value so we don't need to fake one here.
        return None


# ── _format_comment_for_tpm ────────────────────────────────────────────────


class TestFormatComment:
    def test_includes_ticket_id_and_comment_id(self):
        msg = _format_comment_for_tpm(
            ticket_id=123,
            comment_id=999,
            comment_body="hello world",
            author_session_id="sess_abc",
        )
        assert "ticket #123" in msg
        assert "comment_id=999" in msg
        assert "author=sess_abc" in msg
        assert "hello world" in msg

    def test_human_author_when_session_id_is_none(self):
        msg = _format_comment_for_tpm(
            ticket_id=1,
            comment_id=2,
            comment_body="hi",
            author_session_id=None,
        )
        assert "author=human" in msg
        assert "hi" in msg

    def test_body_is_appended_verbatim(self):
        body = "line one\nline two\n  indented line"
        msg = _format_comment_for_tpm(
            ticket_id=1,
            comment_id=2,
            comment_body=body,
            author_session_id=None,
        )
        # Body should appear unchanged after the header newline.
        assert msg.endswith(body)


# ── dispatch_comment_to_tpm ────────────────────────────────────────────────


class TestDispatchComment:
    def test_dispatch_calls_session_manager_append_message(self, db_path):
        async def _t():
            store = await _make_store(db_path)
            await _seed_active_tpm(store, session_id="sess_tpm1", ticket_id=10)
            mgr = _FakeSessionManager()

            target = await dispatch_comment_to_tpm(
                mgr,
                store,
                ticket_id=10,
                comment_id=55,
                comment_body="ticket update",
                author_session_id="sess_dev",
            )

            assert target == "sess_tpm1"
            assert len(mgr.calls) == 1
            session_id, msg = mgr.calls[0]
            assert session_id == "sess_tpm1"
            assert "ticket #10" in msg
            assert "comment_id=55" in msg
            assert "author=sess_dev" in msg
            assert "ticket update" in msg

            await store.close()

        run(_t())

    def test_no_tpm_returns_none(self, db_path):
        async def _t():
            store = await _make_store(db_path)
            mgr = _FakeSessionManager()

            target = await dispatch_comment_to_tpm(
                mgr,
                store,
                ticket_id=404,
                comment_id=1,
                comment_body="orphan",
                author_session_id=None,
            )
            assert target is None
            assert mgr.calls == []
            await store.close()

        run(_t())

    def test_no_tpm_logs_warning(self, db_path, caplog):
        async def _t():
            store = await _make_store(db_path)
            mgr = _FakeSessionManager()

            with caplog.at_level("WARNING", logger="agents_mcp.orchestration_comment_dispatch"):
                await dispatch_comment_to_tpm(
                    mgr,
                    store,
                    ticket_id=404,
                    comment_id=1,
                    comment_body="orphan",
                    author_session_id=None,
                )
            assert any(
                "no active TPM" in rec.message for rec in caplog.records
            )
            await store.close()

        run(_t())

    def test_comment_from_tpm_itself_is_skipped(self, db_path):
        """Self-comment must not loop the TPM back into itself."""
        async def _t():
            store = await _make_store(db_path)
            await _seed_active_tpm(
                store, session_id="sess_tpm_self", ticket_id=20
            )
            mgr = _FakeSessionManager()

            target = await dispatch_comment_to_tpm(
                mgr,
                store,
                ticket_id=20,
                comment_id=1,
                comment_body="my own status update",
                author_session_id="sess_tpm_self",
            )

            assert target is None
            assert mgr.calls == []
            await store.close()

        run(_t())

    def test_comment_from_subagent_is_dispatched(self, db_path):
        """A comment from a subagent under the same TPM is NOT a self-comment;
        it must reach the TPM so the TPM can react.
        """
        async def _t():
            store = await _make_store(db_path)
            await _seed_active_tpm(
                store, session_id="sess_tpm_a", ticket_id=30
            )
            # Subagent under the TPM.
            await store.create_session(
                session_id="sess_dev_a",
                profile_name="developer",
                binding_kind="ticket-subagent",
                runner_type="claude-sonnet-4.6",
                ticket_id=30,
                parent_session_id="sess_tpm_a",
            )
            mgr = _FakeSessionManager()

            target = await dispatch_comment_to_tpm(
                mgr,
                store,
                ticket_id=30,
                comment_id=7,
                comment_body="dev finished the patch",
                author_session_id="sess_dev_a",
            )

            assert target == "sess_tpm_a"
            assert len(mgr.calls) == 1
            assert mgr.calls[0][0] == "sess_tpm_a"
            assert "sess_dev_a" in mgr.calls[0][1]
            await store.close()

        run(_t())

    def test_message_formatting_includes_comment_id_and_author(self, db_path):
        async def _t():
            store = await _make_store(db_path)
            await _seed_active_tpm(
                store, session_id="sess_tpm_fmt", ticket_id=50
            )
            mgr = _FakeSessionManager()

            await dispatch_comment_to_tpm(
                mgr,
                store,
                ticket_id=50,
                comment_id=7777,
                comment_body="multi\nline\nbody",
                author_session_id="sess_xyz",
            )

            assert len(mgr.calls) == 1
            _, msg = mgr.calls[0]
            assert "ticket #50" in msg
            assert "comment_id=7777" in msg
            assert "author=sess_xyz" in msg
            assert "multi\nline\nbody" in msg
            await store.close()

        run(_t())

    def test_human_authored_comment_dispatches_with_human_author_label(
        self, db_path
    ):
        """A Human-via-Telegram drop-in posts a comment with no
        ``author_session_id``; it should reach the TPM with author=human.
        """
        async def _t():
            store = await _make_store(db_path)
            await _seed_active_tpm(
                store, session_id="sess_tpm_h", ticket_id=70
            )
            mgr = _FakeSessionManager()

            target = await dispatch_comment_to_tpm(
                mgr,
                store,
                ticket_id=70,
                comment_id=1,
                comment_body="please prioritise this",
                author_session_id=None,
            )

            assert target == "sess_tpm_h"
            assert len(mgr.calls) == 1
            assert "author=human" in mgr.calls[0][1]
            await store.close()

        run(_t())

    def test_closed_tpm_is_treated_as_no_tpm(self, db_path):
        """After a TPM is closed, the helper must report no recipient."""
        async def _t():
            store = await _make_store(db_path)
            await _seed_active_tpm(
                store, session_id="sess_tpm_done", ticket_id=80
            )
            await store.close_session("sess_tpm_done")

            mgr = _FakeSessionManager()
            target = await dispatch_comment_to_tpm(
                mgr,
                store,
                ticket_id=80,
                comment_id=1,
                comment_body="late comment",
                author_session_id=None,
            )
            assert target is None
            assert mgr.calls == []
            await store.close()

        run(_t())
