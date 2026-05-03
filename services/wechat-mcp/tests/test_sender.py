"""Sender tests — exercise script generation without invoking osascript."""
from __future__ import annotations

import stat
from pathlib import Path

from wechat_mcp.sender import build_send_script, send_wechat_message


def test_build_send_script_contains_chat_and_body():
    s = build_send_script("张三", "hello world")
    # Activate → search palette flow must all be present.
    assert 'tell application "WeChat" to activate' in s
    assert 'keystroke "f" using {command down}' in s
    # CJK fix: chat name + body go through the clipboard, not keystroke,
    # because System Events keystroke routes Chinese through the IME and
    # produces garbage like "a a a a a" in the WeChat search field.
    assert 'set the clipboard to "张三"' in s
    assert 'set the clipboard to "hello world"' in s
    # Two paste operations (one for chat-name search, one for body).
    assert s.count('keystroke "v" using {command down}') >= 2
    # Two Returns: one to open the chat, one to send.
    assert s.count("key code 36") >= 2


def test_build_send_script_escapes_quotes_in_clipboard():
    s = build_send_script("Bob", 'say "hi" please')
    # Quotes in body must be escaped inside the AppleScript "set the
    # clipboard to" literal — otherwise the script syntax errors out.
    assert 'set the clipboard to "say \\"hi\\" please"' in s


def test_build_send_script_escapes_backslashes_in_clipboard():
    s = build_send_script("Bob", "path: c:\\foo")
    assert 'set the clipboard to "path: c:\\\\foo"' in s


def test_send_rejects_empty_chat_name():
    res = send_wechat_message("", "hello")
    assert not res.ok
    assert "empty chat_name" in res.stderr


def test_send_rejects_empty_body():
    res = send_wechat_message("Alice", "")
    assert not res.ok
    assert "empty body" in res.stderr


def test_send_returns_failure_when_osascript_errors(tmp_path):
    fake = tmp_path / "fake_osascript"
    fake.write_text('#!/bin/sh\necho "boom" >&2\nexit 1\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    res = send_wechat_message("Alice", "hello", runner=str(fake))
    assert not res.ok
    assert "boom" in res.stderr


def test_send_succeeds_with_fake_runner_returning_ok(tmp_path):
    fake = tmp_path / "fake_osascript"
    fake.write_text('#!/bin/sh\nexit 0\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    res = send_wechat_message("Alice", "hello", runner=str(fake))
    assert res.ok
    assert res.chat_name == "Alice"
    assert res.body == "hello"
