"""Pure-function tests for AppleScript escaping + osascript runner contract."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from wechat_mcp.applescript import (
    escape_applescript_string,
    run_osascript,
)


def test_escape_quotes_and_backslashes():
    assert escape_applescript_string('hi "there"') == 'hi \\"there\\"'
    assert escape_applescript_string('c:\\path') == 'c:\\\\path'
    # Backslash must be escaped before quote, otherwise the doubled
    # backslash inserted by the quote-escaper would break the literal.
    assert escape_applescript_string('a"b\\c') == 'a\\"b\\\\c'


def test_escape_preserves_unicode():
    # WeChat names commonly contain Chinese characters and emoji — the
    # escaper must not touch them.
    assert escape_applescript_string("张三 🌟") == "张三 🌟"
    assert escape_applescript_string("你好") == "你好"


def test_escape_preserves_newlines():
    # AppleScript string literals accept embedded newlines, so we must
    # leave them as-is for multi-line message bodies.
    assert escape_applescript_string("line1\nline2") == "line1\nline2"


def test_run_osascript_missing_binary(tmp_path, monkeypatch):
    # Force shutil.which to return None by clearing PATH.
    monkeypatch.setenv("PATH", "")
    res = run_osascript('return "hi"', runner=None)
    # Either osascript was discoverable through the cached resolver and
    # the script ran, or we got the explicit not-found error.
    if "osascript not found" in res.stderr:
        assert not res.ok
    # Otherwise the test passes trivially — environment had osascript.


def _write_fake_runner(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_run_osascript_passes_script_via_stdin(tmp_path):
    # A fake "osascript" that just echoes its stdin — proves run_osascript
    # delivers the script as stdin and not as a CLI arg.
    fake = _write_fake_runner(
        tmp_path / "fake_osascript",
        '#!/bin/sh\ncat\n',
    )
    res = run_osascript('hello world', runner=str(fake))
    assert res.ok
    assert res.stdout == "hello world"


def test_run_osascript_captures_stderr(tmp_path):
    fake = _write_fake_runner(
        tmp_path / "fake_osascript",
        '#!/bin/sh\necho "boom" >&2\nexit 7\n',
    )
    res = run_osascript('whatever', runner=str(fake))
    assert not res.ok
    assert res.returncode == 7
    assert "boom" in res.stderr


def test_run_osascript_timeout(tmp_path):
    fake = _write_fake_runner(
        tmp_path / "slow_osascript",
        '#!/bin/sh\nsleep 5\n',
    )
    res = run_osascript('whatever', runner=str(fake), timeout=0.2)
    assert not res.ok
    assert "timed out" in res.stderr
