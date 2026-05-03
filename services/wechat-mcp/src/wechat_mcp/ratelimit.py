"""In-process rate limiter for outbound WeChat sends.

WeChat's anti-spam systems are tuned to humans: 1–3 messages every few
seconds is fine, but 50 in a minute looks like a bot and is the most
plausible failure mode for our AppleScript-driven send. The limiter
enforces two policies:

- **Per-chat throttle**: at least ``per_chat_min_interval`` seconds between
  consecutive sends to the *same* chat name (so a single agent task can't
  flood one contact).
- **Global ceiling**: no more than ``global_max_per_minute`` sends across
  all chats, in any rolling 60-second window.

Both are best-effort and reset when the MCP process restarts. That's an
acceptable trade-off because the limits are conservative — if the daemon
restarts we just get a fresh allowance.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    per_chat_min_interval: float = 3.0
    global_max_per_minute: int = 20
    _last_per_chat: dict[str, float] = field(default_factory=dict)
    _global_window: deque[float] = field(default_factory=deque)

    def check(self, chat_name: str, now: float | None = None) -> tuple[bool, str]:
        """Return ``(allowed, reason)``. ``reason`` is empty if allowed.

        The caller is expected to call :meth:`record` *only when the send
        succeeds*. That prevents failed attempts from consuming the budget
        and ensures retries can fire immediately after a UI hiccup.
        """
        now = time.monotonic() if now is None else now

        # Drop entries older than 60s from the global window.
        cutoff = now - 60.0
        while self._global_window and self._global_window[0] < cutoff:
            self._global_window.popleft()

        if len(self._global_window) >= self.global_max_per_minute:
            return False, (
                f"global rate limit: {self.global_max_per_minute} sends/minute "
                "exceeded; back off and retry later"
            )

        last = self._last_per_chat.get(chat_name)
        if last is not None:
            elapsed = now - last
            if elapsed < self.per_chat_min_interval:
                wait = self.per_chat_min_interval - elapsed
                return False, (
                    f"per-chat throttle: wait {wait:.1f}s before sending "
                    f"to '{chat_name}' again"
                )

        return True, ""

    def record(self, chat_name: str, now: float | None = None) -> None:
        """Record a successful send."""
        now = time.monotonic() if now is None else now
        self._last_per_chat[chat_name] = now
        self._global_window.append(now)
