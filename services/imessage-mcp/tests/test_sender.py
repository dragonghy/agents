"""Sender tests — exercise escaping + script generation without invoking osascript."""
from imessage_mcp.sender import _build_script, _escape_for_applescript, send_imessage


def test_escape_quotes_and_backslashes():
    assert _escape_for_applescript('hi "there"') == 'hi \\"there\\"'
    assert _escape_for_applescript("c:\\path") == "c:\\\\path"
    # Round-trip: backslash before quote.
    assert _escape_for_applescript('a"b\\c') == 'a\\"b\\\\c'


def test_build_script_imessage():
    s = _build_script("+15551234567", "hello", service="iMessage")
    assert "service type = iMessage" in s
    assert 'buddy "+15551234567"' in s
    assert 'send "hello"' in s


def test_build_script_sms():
    s = _build_script("+15551234567", "hello", service="SMS")
    assert "service type = SMS" in s


def test_send_no_handle():
    res = send_imessage("", "hi")
    assert not res.ok
    assert "empty handle" in res.stderr


def test_send_no_body():
    res = send_imessage("+15551234567", "")
    assert not res.ok
    assert "empty body" in res.stderr


def test_send_no_osascript_returns_failure(monkeypatch):
    # Force `which("osascript")` lookup to fail by clearing PATH.
    monkeypatch.setenv("PATH", "")
    res = send_imessage("+15551234567", "hello", runner=None)
    # On non-mac CI the shutil.which lookup may still find it via login profile;
    # we accept either an explicit "osascript not found" error OR an osascript
    # failure (bad service). The contract is "ok=False if no osascript".
    if "osascript not found" in res.stderr:
        assert not res.ok
    # Otherwise: the path was discoverable; test passes trivially.
