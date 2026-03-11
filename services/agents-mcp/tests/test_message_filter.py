"""Tests for the agents_only message filtering feature."""

import asyncio
import os
import tempfile

import pytest
from agents_mcp.store import AgentStore


@pytest.fixture
def store():
    """Create a temporary AgentStore for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    s = AgentStore(db_path)
    asyncio.get_event_loop().run_until_complete(s.initialize())
    yield s
    asyncio.get_event_loop().run_until_complete(s.close())
    os.unlink(db_path)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestConversationThreadsFilter:
    def test_no_filter_returns_all(self, store):
        """Without agent_ids filter, all threads should be returned."""
        run(store.insert_message("dev-alex", "qa-lucy", "hello"))
        run(store.insert_message("old-agent", "test-bot", "hi"))
        run(store.insert_message("dev-alex", "human", "question"))

        threads = run(store.get_conversation_threads())
        assert len(threads) == 3

    def test_filter_by_agent_ids(self, store):
        """With agent_ids filter, only threads where both agents are in the list."""
        run(store.insert_message("dev-alex", "qa-lucy", "hello"))
        run(store.insert_message("old-agent", "test-bot", "hi"))
        run(store.insert_message("dev-alex", "human", "question"))
        run(store.insert_message("qa-lucy", "human", "report"))

        current_agents = ["dev-alex", "qa-lucy", "human"]
        threads = run(store.get_conversation_threads(agent_ids=current_agents))

        # Should only return threads between current agents (3 out of 4)
        # dev-alex <-> qa-lucy, dev-alex <-> human, qa-lucy <-> human
        assert len(threads) == 3

        # old-agent <-> test-bot should be filtered out
        agent_pairs = [(t["agent_a"], t["agent_b"]) for t in threads]
        assert ("old-agent", "test-bot") not in agent_pairs

    def test_filter_excludes_mixed_threads(self, store):
        """Threads with one current and one old agent should be excluded."""
        run(store.insert_message("dev-alex", "qa-lucy", "hello"))
        run(store.insert_message("dev-alex", "old-agent", "legacy msg"))

        current_agents = ["dev-alex", "qa-lucy", "human"]
        threads = run(store.get_conversation_threads(agent_ids=current_agents))

        # Only dev-alex <-> qa-lucy should be included
        assert len(threads) == 1
        assert threads[0]["agent_a"] == "dev-alex"
        assert threads[0]["agent_b"] == "qa-lucy"

    def test_filter_empty_list_same_as_no_filter(self, store):
        """Empty agent_ids list is falsy, so it behaves like no filter (returns all)."""
        run(store.insert_message("dev-alex", "qa-lucy", "hello"))

        threads = run(store.get_conversation_threads(agent_ids=[]))
        # Empty list is falsy in Python, so no filter applied
        assert len(threads) == 1

    def test_filter_preserves_thread_metadata(self, store):
        """Filtered threads should still have correct metadata."""
        run(store.insert_message("dev-alex", "qa-lucy", "first message"))
        run(store.insert_message("qa-lucy", "dev-alex", "second message"))

        current_agents = ["dev-alex", "qa-lucy"]
        threads = run(store.get_conversation_threads(agent_ids=current_agents))

        assert len(threads) == 1
        thread = threads[0]
        assert thread["message_count"] == 2
        assert thread["agent_a"] == "dev-alex"
        assert thread["agent_b"] == "qa-lucy"
        # last_sender and last_message are present
        assert thread["last_sender"] in ("dev-alex", "qa-lucy")
        assert thread["last_message"] is not None

    def test_none_filter_same_as_no_filter(self, store):
        """Passing agent_ids=None should behave the same as no filter."""
        run(store.insert_message("dev-alex", "qa-lucy", "hello"))
        run(store.insert_message("old-agent", "test-bot", "hi"))

        threads_none = run(store.get_conversation_threads(agent_ids=None))
        threads_no_arg = run(store.get_conversation_threads())
        assert len(threads_none) == len(threads_no_arg) == 2
