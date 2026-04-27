"""Decoder tests.

We can't easily synthesize NSKeyedArchiver blobs, so these tests exercise:
- the public surface returns None for empty/None input
- the loose UTF-8 fallback finds embedded ASCII inside arbitrary bytes
- a minimal-but-realistic blob (with NSString markers) decodes correctly
"""
from imessage_mcp.decoder import (
    _longest_printable_run,
    _strip_length_byte,
    _try_decode,
    decode_attributed_body,
)


def test_none_and_empty():
    assert decode_attributed_body(None) is None
    assert decode_attributed_body(b"") is None
    assert decode_attributed_body(b"\x00\x00\x00\x00") is None


def test_longest_printable_run():
    blob = b"\x00\x01hello world\x86\x84\x00\x00short"
    run = _longest_printable_run(blob)
    assert run == "hello world"


def test_try_decode_strips_controls():
    raw = b"hi there\x86\x84"
    out = _try_decode(raw)
    assert out is not None
    assert "hi there" in out


def test_strip_length_byte_pass_through():
    # Plain text passes through (no length-marker prefix).
    assert _strip_length_byte(b"abc") == b"abc"
    # 0x10 marker → strip 1 byte of length (2^0 = 1) plus the marker itself.
    assert _strip_length_byte(b"\x10\x05abc") == b"abc"
    # Non-marker prefixes also pass through (we don't over-strip).
    assert _strip_length_byte(b"\x43abc") == b"\x43abc"


def test_synthetic_attributed_body_decodes():
    # Emulate the byte structure: ...NSString\x01\x94\x84\x01\x2b<TEXT>\x86\x84...
    payload = b"hello there"
    blob = (
        b"\x00\x00random_prefix"
        + b"NSString\x01\x94\x84\x01\x2b"
        + payload
        + b"\x86\x84tail_garbage"
    )
    out = decode_attributed_body(blob)
    assert out is not None
    # Either the strict pattern or the longest-run fallback should surface payload.
    assert "hello there" in out
