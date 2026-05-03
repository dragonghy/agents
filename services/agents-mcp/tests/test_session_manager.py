"""Tests for the orchestration v1 SessionManager.

Hermetic: builds synthetic profile.md files in tmp_path and a fresh
AgentStore on a tmp sqlite DB. The Adapter layer is mocked at the
``get_adapter`` boundary — we patch
``agents_mcp.orchestration_session_manager.get_adapter`` to return a fake
adapter that records its call args and yields a canned :class:`RunResult`,
so no test ever hits a real LLM.

Style mirrors test_profile_loader.py + test_orchestration_session.py: sync
test functions wrapping async coroutines via a local ``run()`` helper, no
pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from agents_mcp.adapters.base import Profile, RunResult, SessionMetadata
from agents_mcp.orchestration_session_manager import (
    SessionManager,
    _generate_session_id,
)
from agents_mcp.store import AgentStore


# ── Fixtures / helpers ─────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-session-manager.db")


@pytest.fixture
def profiles_dir(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    return d


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


def _write_profile(
    profiles_dir: Path,
    name: str,
    body: str = "You are a test agent. Do test things.\n",
    description: str = "Test profile for unit tests.",
    runner_type: str = "claude-sonnet-4.6",
) -> Path:
    """Write a well-formed profile.md and return its path."""
    d = profiles_dir / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "profile.md"
    fm = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"runner_type: {runner_type}\n"
        "---\n\n"
    )
    md.write_text(fm + body, encoding="utf-8")
    return md


class _FakeAdapter:
    """Records calls to ``run()`` and returns a canned RunResult.

    Used everywhere a test wants to exercise SessionManager without hitting
    a real LLM. Captures ``profile``, ``session_metadata``, and
    ``new_message_text`` on each call so tests can assert the manager
    forwarded the right things.

    By default emulates first-turn behaviour: persists a fake native_handle
    and adds cost via the store (mirroring the real ClaudeAdapter contract).
    """

    def __init__(
        self,
        native_handle: str = "fake-native-1",
        assistant_text: str = "ok",
        tokens_in: int = 10,
        tokens_out: int = 5,
    ):
        self.calls: list[dict] = []
        self.native_handle = native_handle
        self.assistant_text = assistant_text
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out

    async def run(
        self, profile, session_metadata, new_message_text, store, **kwargs
    ):
        self.calls.append(
            {
                "profile": profile,
                "session_metadata": session_metadata,
                "new_message_text": new_message_text,
                "store": store,
                "kwargs": kwargs,
            }
        )
        # Mirror the real Adapter contract: persist native_handle on first
        # turn + add cost. Tests for store-side effects depend on this.
        if session_metadata.native_handle != self.native_handle:
            await store.update_session_native_handle(
                session_metadata.session_id, self.native_handle
            )
        await store.add_session_cost(
            session_metadata.session_id, self.tokens_in, self.tokens_out
        )
        return RunResult(
            assistant_text=self.assistant_text,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            native_handle=self.native_handle,
        )


# ── _generate_session_id ────────────────────────────────────────────────────


class TestSessionIdGeneration:
    def test_format(self):
        sid = _generate_session_id()
        # sess_ + 22 hex chars
        assert re.fullmatch(r"sess_[0-9a-f]{22}", sid), sid

    def test_uniqueness(self):
        ids = {_generate_session_id() for _ in range(1000)}
        assert len(ids) == 1000


# ── spawn ───────────────────────────────────────────────────────────────────


class TestSpawn:
    def test_spawn_creates_row_and_assigns_id(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            mgr = SessionManager(store, profiles_dir)

            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="ticket-subagent",
                ticket_id=42,
            )
            assert row["id"].startswith("sess_")
            assert row["profile_name"] == "tpm"
            assert row["binding_kind"] == "ticket-subagent"
            assert row["ticket_id"] == 42
            assert row["status"] == "active"
            assert row["runner_type"] == "claude-sonnet-4.6"
            assert row["native_handle"] is None
            assert row["cost_tokens_in"] == 0
            assert row["cost_tokens_out"] == 0

            # Persisted in the store
            same = await store.get_session(row["id"])
            assert same == row

            await store.close()

        run(_t())

    def test_spawn_rejects_unknown_profile(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            mgr = SessionManager(store, profiles_dir)

            with pytest.raises(FileNotFoundError):
                await mgr.spawn(
                    profile_name="does-not-exist",
                    binding_kind="standalone",
                )

            # No orphan session row should have been inserted.
            assert await store.list_sessions() == []
            await store.close()

        run(_t())

    def test_spawn_rejects_invalid_binding_kind(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            mgr = SessionManager(store, profiles_dir)

            with pytest.raises(ValueError, match="binding_kind"):
                await mgr.spawn(
                    profile_name="tpm",
                    binding_kind="not-a-kind",
                )

            # No row inserted.
            assert await store.list_sessions() == []
            await store.close()

        run(_t())

    def test_spawn_with_all_binding_kinds(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            _write_profile(profiles_dir, "secretary")
            _write_profile(profiles_dir, "developer")
            mgr = SessionManager(store, profiles_dir)

            ticket = await mgr.spawn(
                profile_name="tpm",
                binding_kind="ticket-subagent",
                ticket_id=1,
            )
            assert ticket["binding_kind"] == "ticket-subagent"
            assert ticket["ticket_id"] == 1

            channel = await mgr.spawn(
                profile_name="secretary",
                binding_kind="human-channel",
                channel_id="telegram:99",
            )
            assert channel["binding_kind"] == "human-channel"
            assert channel["channel_id"] == "telegram:99"
            assert channel["ticket_id"] is None

            standalone = await mgr.spawn(
                profile_name="developer",
                binding_kind="standalone",
            )
            assert standalone["binding_kind"] == "standalone"
            assert standalone["ticket_id"] is None
            assert standalone["channel_id"] is None

            await store.close()

        run(_t())

    def test_spawn_records_parent_session_id(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            _write_profile(profiles_dir, "developer")
            mgr = SessionManager(store, profiles_dir)

            tpm_row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="ticket-subagent",
                ticket_id=7,
            )
            child_row = await mgr.spawn(
                profile_name="developer",
                binding_kind="ticket-subagent",
                ticket_id=7,
                parent_session_id=tpm_row["id"],
            )
            assert child_row["parent_session_id"] == tpm_row["id"]
            await store.close()

        run(_t())

    def test_spawn_touches_profile_registry_last_used_at(
        self, db_path, profiles_dir
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            # Pre-register the Profile so touch_profile_used has a row to
            # update. (Spawn doesn't itself populate the registry; the
            # Profile loader scan does that on daemon boot.)
            await store.upsert_profile_registry(
                name="tpm",
                description="test",
                runner_type="claude-sonnet-4.6",
                file_path=str(profiles_dir / "tpm" / "profile.md"),
                file_hash="hash_v1",
            )
            before = await store.get_profile_registry("tpm")
            assert before["last_used_at"] is None

            mgr = SessionManager(store, profiles_dir)
            await mgr.spawn(profile_name="tpm", binding_kind="standalone")

            after = await store.get_profile_registry("tpm")
            assert after["last_used_at"] is not None

            await store.close()

        run(_t())

    def test_spawn_unregistered_profile_does_not_error(
        self, db_path, profiles_dir
    ):
        """Profile registry is a discovery cache; spawning a Profile that's
        on disk but not yet registered should still succeed (touch_profile_used
        is a no-op when the row is missing).
        """
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            mgr = SessionManager(store, profiles_dir)

            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="standalone",
            )
            assert row["id"].startswith("sess_")
            # Registry was not pre-populated.
            assert await store.get_profile_registry("tpm") is None
            await store.close()

        run(_t())


# ── append_message ──────────────────────────────────────────────────────────


class TestAppendMessage:
    def test_calls_adapter_with_correct_args(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(
                profiles_dir,
                "tpm",
                body="You are TPM.\n",
                description="TPM profile",
            )
            mgr = SessionManager(store, profiles_dir)
            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="ticket-subagent",
                ticket_id=11,
            )

            fake = _FakeAdapter(native_handle="claude-sess-xyz")
            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                return_value=fake,
            ):
                result = await mgr.append_message(row["id"], "hello")

            # Adapter saw the right things
            assert len(fake.calls) == 1
            call = fake.calls[0]
            assert isinstance(call["profile"], Profile)
            assert call["profile"].name == "tpm"
            assert call["profile"].system_prompt.startswith("You are TPM.")
            assert isinstance(call["session_metadata"], SessionMetadata)
            assert call["session_metadata"].session_id == row["id"]
            assert call["session_metadata"].native_handle is None  # first turn
            assert call["session_metadata"].runner_type == "claude-sonnet-4.6"
            assert call["new_message_text"] == "hello"
            assert call["store"] is store

            # Adapter's RunResult is returned unchanged
            assert isinstance(result, RunResult)
            assert result.assistant_text == "ok"
            assert result.native_handle == "claude-sess-xyz"

            # Store reflects the side effects the (fake) adapter performed
            updated = await store.get_session(row["id"])
            assert updated["native_handle"] == "claude-sess-xyz"
            assert updated["cost_tokens_in"] == 10
            assert updated["cost_tokens_out"] == 5

            await store.close()

        run(_t())

    def test_second_call_passes_persisted_native_handle(
        self, db_path, profiles_dir
    ):
        """On the second turn, the manager should hand the Adapter the
        native_handle that the first turn persisted. This lets the SDK
        resume rather than starting a fresh native session.
        """
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            mgr = SessionManager(store, profiles_dir)
            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="standalone",
            )

            fake = _FakeAdapter(native_handle="claude-resume-1")
            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                return_value=fake,
            ):
                await mgr.append_message(row["id"], "first")
                await mgr.append_message(row["id"], "second")

            assert len(fake.calls) == 2
            assert fake.calls[0]["session_metadata"].native_handle is None
            assert (
                fake.calls[1]["session_metadata"].native_handle
                == "claude-resume-1"
            )
            assert fake.calls[1]["new_message_text"] == "second"

            # Cost accumulated from both turns
            updated = await store.get_session(row["id"])
            assert updated["cost_tokens_in"] == 20
            assert updated["cost_tokens_out"] == 10

            await store.close()

        run(_t())

    def test_rejects_closed_session(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            mgr = SessionManager(store, profiles_dir)
            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="standalone",
            )
            await mgr.close(row["id"])

            fake = _FakeAdapter()
            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                return_value=fake,
            ):
                with pytest.raises(RuntimeError, match="closed"):
                    await mgr.append_message(row["id"], "too late")

            # Adapter must NOT have been called
            assert fake.calls == []
            await store.close()

        run(_t())

    def test_rejects_unknown_session(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            mgr = SessionManager(store, profiles_dir)

            fake = _FakeAdapter()
            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                return_value=fake,
            ):
                with pytest.raises(LookupError, match="unknown session"):
                    await mgr.append_message("sess_bogus", "hi")

            assert fake.calls == []
            await store.close()

        run(_t())

    def test_uses_session_runner_type_to_pick_adapter(
        self, db_path, profiles_dir
    ):
        """The session row's runner_type is the source of truth for adapter
        dispatch (not the on-disk profile, which could have been edited).
        """
        async def _t():
            store = await _make_store(db_path)
            # Profile on disk says claude-sonnet-4.6
            _write_profile(profiles_dir, "tpm", runner_type="claude-sonnet-4.6")
            mgr = SessionManager(store, profiles_dir)
            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="standalone",
            )

            captured: list[str] = []
            fake = _FakeAdapter()

            def _spy(runner_type):
                captured.append(runner_type)
                return fake

            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                side_effect=_spy,
            ):
                await mgr.append_message(row["id"], "hi")

            assert captured == ["claude-sonnet-4.6"]
            assert (
                fake.calls[0]["session_metadata"].runner_type
                == "claude-sonnet-4.6"
            )
            await store.close()

        run(_t())


# ── close ──────────────────────────────────────────────────────────────────


class TestClose:
    def test_close_idempotent(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            mgr = SessionManager(store, profiles_dir)
            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="standalone",
            )

            assert await mgr.close(row["id"]) is True
            # Row is now closed
            assert (await store.get_session(row["id"]))["status"] == "closed"

            # Closing again is a no-op
            assert await mgr.close(row["id"]) is False
            await store.close()

        run(_t())

    def test_close_unknown_returns_false(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            mgr = SessionManager(store, profiles_dir)
            assert await mgr.close("sess_nope") is False
            await store.close()

        run(_t())


# ── orchestration_tools wiring ─────────────────────────────────────────────


def _write_tpm_profile(profiles_dir: Path):
    """Write a profile.md with ``orchestration_tools: true``."""
    d = profiles_dir / "tpm"
    d.mkdir(parents=True, exist_ok=True)
    md = d / "profile.md"
    md.write_text(
        "---\n"
        "name: tpm\n"
        "description: TPM under test.\n"
        "runner_type: claude-sonnet-4.6\n"
        "orchestration_tools: true\n"
        "---\n\n"
        "You are a TPM.\n",
        encoding="utf-8",
    )
    return md


class TestOrchestrationToolsWiring:
    """When a Profile declares orchestration_tools: true, the SessionManager
    must build an in-process MCP tool server and pass it to the adapter."""

    def test_tpm_session_passes_mcp_server_to_adapter(
        self, db_path, profiles_dir
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)

            class _DummyTaskClient:
                pass

            mgr = SessionManager(
                store, profiles_dir, task_client=_DummyTaskClient()
            )

            # spawn the TPM with a real ticket binding (required for
            # orchestration tools).
            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="ticket-subagent",
                ticket_id=999100,
            )

            fake = _FakeAdapter(native_handle="claude-tpm-1")
            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                return_value=fake,
            ):
                await mgr.append_message(row["id"], "hello tpm")

            # Adapter saw mcp_servers + allowed_tools kwargs.
            assert len(fake.calls) == 1
            kwargs = fake.calls[0]["kwargs"]
            assert "mcp_servers" in kwargs
            mcp = kwargs["mcp_servers"]
            assert len(mcp) == 1
            server_name = next(iter(mcp.keys()))
            assert server_name == "orchestration_tpm_999100"
            assert mcp[server_name]["type"] == "sdk"

            assert "allowed_tools" in kwargs
            allowed = kwargs["allowed_tools"]
            assert sorted(allowed) == sorted(
                [
                    f"mcp__{server_name}__{name}"
                    for name in (
                        "spawn_subagent",
                        "push_message",
                        "post_comment",
                        "mark_ticket_status",
                    )
                ]
            )

            await store.close()

        run(_t())

    def test_non_tpm_session_does_not_pass_mcp_server(
        self, db_path, profiles_dir
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "developer")
            mgr = SessionManager(store, profiles_dir)

            row = await mgr.spawn(
                profile_name="developer",
                binding_kind="standalone",
            )

            fake = _FakeAdapter(native_handle="claude-dev-1")
            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                return_value=fake,
            ):
                await mgr.append_message(row["id"], "hello developer")

            assert len(fake.calls) == 1
            kwargs = fake.calls[0]["kwargs"]
            assert "mcp_servers" not in kwargs
            assert "allowed_tools" not in kwargs

            await store.close()

        run(_t())

    def test_tpm_without_task_client_raises(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)
            # Construct WITHOUT task_client.
            mgr = SessionManager(store, profiles_dir)
            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="ticket-subagent",
                ticket_id=42,
            )

            fake = _FakeAdapter()
            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                return_value=fake,
            ):
                with pytest.raises(RuntimeError, match="task_client"):
                    await mgr.append_message(row["id"], "x")

            await store.close()

        run(_t())

    def test_tpm_without_ticket_id_raises(self, db_path, profiles_dir):
        async def _t():
            store = await _make_store(db_path)
            _write_tpm_profile(profiles_dir)

            class _DummyTaskClient:
                pass

            mgr = SessionManager(
                store, profiles_dir, task_client=_DummyTaskClient()
            )
            # Spawn TPM with no ticket binding (standalone). This is an
            # unusual but possible misconfiguration; we want a clear error,
            # not a silent crash inside the tool server build.
            row = await mgr.spawn(
                profile_name="tpm",
                binding_kind="standalone",
            )

            fake = _FakeAdapter()
            with patch(
                "agents_mcp.orchestration_session_manager.get_adapter",
                return_value=fake,
            ):
                with pytest.raises(RuntimeError, match="ticket_id"):
                    await mgr.append_message(row["id"], "x")

            await store.close()

        run(_t())
