"""Sender tests — exercise script generation without invoking osascript."""
from __future__ import annotations

import stat
from pathlib import Path

from wechat_mcp.sender import build_send_script, send_wechat_message


def test_build_send_script_contains_chat_and_body():
    s = build_send_script("张三", "hello world")
    # Activate -> System Events -> Cmd+F flow must all be present.
    assert 'tell application "WeChat" to activate' in s
    assert 'keystroke "f" using {command down}' in s
    assert 'keystroke "张三"' in s
    assert 'keystroke "hello world"' in s
    # Two Returns: one to open the chat, one to send.
    assert s.count("key code 36") >= 2


def test_build_send_script_escapes_quotes():
    s = build_send_script("Bob", 'say "hi" please')
    assert 'keystroke "say \\"hi\\" please"' in s


def test_build_send_script_escapes_backslashes():
    s = build_send_script("Bob", "path: c:\\foo")
    assert 'keystroke "path: c:\\\\foo"' in s


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
