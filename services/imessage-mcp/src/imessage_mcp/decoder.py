"""Decode `attributedBody` blobs into plain text.

iOS 14+ stores rich-text iMessage bodies in `message.attributedBody`
(an NSKeyedArchiver-encoded NSAttributedString) instead of `message.text`.

This module ships two decoders:

1. `decode_attributed_body` — best-effort byte-scan that finds the NSString
   payload between the magic markers used by NSKeyedArchiver. Fast, in-process,
   no subprocess required. Works on the vast majority of messages.

2. `decode_attributed_body_via_plutil` — fallback that shells out to
   `plutil -convert xml1 -` and parses the XML. Used for diagnostics and as
   a last-resort decoder. Slower (subprocess per call) — not used on hot paths.

If both fail, callers receive None and must surface a placeholder.
"""
from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

# NSKeyedArchiver markers that bracket the NSString payload inside an
# NSAttributedString blob.
#
# Empirically (see also imessagedb, mac_messages_mcp): the readable text
# follows a one-byte length prefix after the bytes `\x01\x2b` (which encode
# `NSString` class pointer + variant), and is terminated by the bytes
# `\x86\x84` which start the NSAttributedString attribute block.
#
# We use a regex to locate the longest run of printable bytes between
# any `NSString`-class-hint marker and the next `NSDictionary` or `NSNumber`
# marker. This is permissive on purpose: false positives are filtered by
# requiring at least one non-whitespace character in the result.
_BODY_PATTERN = re.compile(
    rb"NSString\x01\x94\x84\x01\x2b(.+?)(?:\x86\x84|\x08\x0c)",
    re.DOTALL,
)
# Newer macOS variants pack with a slightly different prefix; this fallback
# searches for any printable ASCII run preceded by NSString.
_BODY_PATTERN_LOOSE = re.compile(rb"NSString\x01.{0,8}(.+?)\x86\x84", re.DOTALL)


def _strip_length_byte(payload: bytes) -> bytes:
    """Drop a leading length-prefix byte if it looks like an NSKeyedArchiver marker.

    NSKeyedArchiver typed-object encoding uses these prefixes for short strings:
      - 0x10..0x17: "next 2^(n-0x10) bytes are the length" — 1-, 2-, 4-, 8-byte
        length follows.

    We *only* strip these explicit length-marker bytes. We deliberately do NOT
    try to decode the bplist string-type bytes (0x40..0x4F, 0x60..0x6F) here —
    those are part of an outer bplist00 structure that wraps the entire blob,
    not inline payload markers. Stripping them ate the first byte of plain
    UTF-8 text on real messages.
    """
    if not payload:
        return payload
    first = payload[0]
    if first in (0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17):
        nlen = 1 << (first - 0x10)
        return payload[1 + nlen :]
    return payload


def decode_attributed_body(blob: bytes | memoryview | None) -> str | None:
    """Best-effort UTF-8 / UTF-16 plaintext extraction from an attributedBody blob.

    Returns None if no plausible string was found.
    """
    if blob is None:
        return None
    data = bytes(blob)
    if not data:
        return None

    candidates: list[bytes] = []
    for pat in (_BODY_PATTERN, _BODY_PATTERN_LOOSE):
        m = pat.search(data)
        if m:
            candidates.append(_strip_length_byte(m.group(1)))

    for raw in candidates:
        text = _try_decode(raw)
        if text and any(not c.isspace() for c in text):
            return text

    # Last resort: scan for the longest UTF-8 printable run in the blob.
    text = _longest_printable_run(data)
    if text and len(text.strip()) >= 2:
        return text
    return None


def _try_decode(raw: bytes) -> str | None:
    if not raw:
        return None
    # Trim trailing non-printables.
    raw = raw.rstrip(b"\x00\x86\x84\x08\x0c")
    for enc in ("utf-8", "utf-16-le"):
        try:
            s = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        # Strip control chars and stop at the first sentinel.
        cleaned = "".join(
            ch for ch in s if ch == "\n" or ch == "\t" or (ch.isprintable())
        )
        cleaned = cleaned.strip()
        if cleaned:
            return cleaned
    return None


def _longest_printable_run(data: bytes) -> str | None:
    best = b""
    cur = bytearray()
    for b in data:
        # Printable ASCII range, plus tab/newline/CR.
        if 0x20 <= b < 0x7F or b in (0x09, 0x0A, 0x0D):
            cur.append(b)
        else:
            if len(cur) > len(best):
                best = bytes(cur)
            cur = bytearray()
    if len(cur) > len(best):
        best = bytes(cur)
    if len(best) < 4:
        return None
    return best.decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------------------
# Subprocess-based fallback (diagnostics only)
# ---------------------------------------------------------------------------
def decode_attributed_body_via_plutil(blob: bytes) -> str | None:
    """Shell out to `plutil -convert xml1 - -o -` and grep the NSString.

    Slow — used only for troubleshooting. Returns None on any failure.
    """
    try:
        result = subprocess.run(
            ["plutil", "-convert", "xml1", "-", "-o", "-"],
            input=blob,
            capture_output=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.debug("plutil decode failed: %s", e)
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.decode("utf-8", errors="replace")
    # The first NSString value sits in <string>...</string> after a key of
    # "NSString" or with a value that doesn't look like a class name.
    matches = re.findall(r"<string>([^<]+)</string>", out)
    for s in matches:
        if s and not s.startswith("NS") and not s.startswith("__kIM"):
            return s
    return None
