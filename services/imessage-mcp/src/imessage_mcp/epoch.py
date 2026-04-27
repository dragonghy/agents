"""Apple epoch <-> Unix epoch conversion.

macOS High Sierra+ stores `message.date` as nanoseconds since
2001-01-01 00:00:00 UTC. To convert to Unix time, divide by 1e9 and add
the offset between the Apple and Unix epochs.
"""
from __future__ import annotations

# Seconds between 1970-01-01 UTC and 2001-01-01 UTC.
APPLE_TO_UNIX_OFFSET_SECONDS = 978_307_200


def apple_ns_to_unix(apple_ns: int | float | None) -> float:
    """Convert macOS Messages `date` column (nanoseconds since 2001-01-01) to Unix.

    Returns 0.0 if the input is falsy. Pre-High-Sierra values (already
    in seconds, magnitude < 10^10) are passed through unchanged so the
    function is robust on legacy backups.
    """
    if not apple_ns:
        return 0.0
    n = float(apple_ns)
    # Heuristic: anything above ~10^15 is nanoseconds. ~10^9..10^10 is
    # already-seconds (Apple epoch).
    if n > 1e14:
        n = n / 1_000_000_000
    return n + APPLE_TO_UNIX_OFFSET_SECONDS


def unix_to_apple_ns(unix_seconds: float) -> int:
    """Inverse of `apple_ns_to_unix` (always returns nanoseconds)."""
    return int((unix_seconds - APPLE_TO_UNIX_OFFSET_SECONDS) * 1_000_000_000)
