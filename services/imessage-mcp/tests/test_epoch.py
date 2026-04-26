from imessage_mcp.epoch import (
    APPLE_TO_UNIX_OFFSET_SECONDS,
    apple_ns_to_unix,
    unix_to_apple_ns,
)


def test_apple_epoch_zero_is_2001_01_01():
    # apple_ns_to_unix(0) returns 0.0 (treated as missing)
    assert apple_ns_to_unix(0) == 0.0
    assert apple_ns_to_unix(None) == 0.0


def test_apple_ns_round_trip():
    unix = 1_700_000_000.0  # late 2023
    ns = unix_to_apple_ns(unix)
    assert abs(apple_ns_to_unix(ns) - unix) < 1e-3


def test_legacy_seconds_format_passes_through():
    # Pre-High-Sierra format: already-seconds (Apple epoch).
    apple_seconds = 600_000_000  # ~ 2020
    expected_unix = apple_seconds + APPLE_TO_UNIX_OFFSET_SECONDS
    assert apple_ns_to_unix(apple_seconds) == expected_unix


def test_known_value():
    # 2024-01-01 00:00:00 UTC = 1704067200 unix
    # Apple-seconds = unix - 978307200 = 725760000
    # As nanoseconds = 7.2576e17
    apple_ns = int(725_760_000 * 1e9)
    assert abs(apple_ns_to_unix(apple_ns) - 1_704_067_200) < 1.0
