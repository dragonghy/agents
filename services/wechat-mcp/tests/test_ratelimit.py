"""Rate limiter tests — verify per-chat and global windowing."""
from __future__ import annotations

from wechat_mcp.ratelimit import RateLimiter


def test_first_send_allowed():
    rl = RateLimiter()
    allowed, reason = rl.check("Alice", now=0.0)
    assert allowed
    assert reason == ""


def test_per_chat_throttle_blocks_within_interval():
    rl = RateLimiter(per_chat_min_interval=3.0, global_max_per_minute=100)
    rl.record("Alice", now=0.0)
    allowed, reason = rl.check("Alice", now=2.5)
    assert not allowed
    assert "per-chat" in reason


def test_per_chat_throttle_clears_after_interval():
    rl = RateLimiter(per_chat_min_interval=3.0, global_max_per_minute=100)
    rl.record("Alice", now=0.0)
    allowed, _ = rl.check("Alice", now=3.5)
    assert allowed


def test_per_chat_throttle_does_not_affect_other_chats():
    rl = RateLimiter(per_chat_min_interval=3.0, global_max_per_minute=100)
    rl.record("Alice", now=0.0)
    allowed, _ = rl.check("Bob", now=1.0)
    assert allowed


def test_global_ceiling_blocks_burst():
    rl = RateLimiter(per_chat_min_interval=0.0, global_max_per_minute=3)
    for i in range(3):
        # Different chats so per-chat throttle doesn't fire first.
        chat = f"chat-{i}"
        allowed, _ = rl.check(chat, now=float(i))
        assert allowed
        rl.record(chat, now=float(i))
    allowed, reason = rl.check("chat-3", now=3.5)
    assert not allowed
    assert "global rate limit" in reason


def test_global_ceiling_drops_old_entries():
    rl = RateLimiter(per_chat_min_interval=0.0, global_max_per_minute=3)
    # Fill the window.
    for i in range(3):
        rl.record(f"chat-{i}", now=float(i))
    # 65s later, all entries are stale.
    allowed, _ = rl.check("chat-3", now=65.0)
    assert allowed


def test_failed_send_does_not_consume_budget():
    """`record` must only be called on success — verify that pattern works."""
    rl = RateLimiter(per_chat_min_interval=3.0, global_max_per_minute=2)
    # Simulate two checks without recording (e.g. send failed).
    rl.check("Alice", now=0.0)
    rl.check("Alice", now=1.0)
    # A third attempt should still be allowed because nothing was recorded.
    allowed, _ = rl.check("Alice", now=2.0)
    assert allowed
