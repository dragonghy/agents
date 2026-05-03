"""Reader tests — parser correctness on synthetic AX-tree output."""
from __future__ import annotations

from wechat_mcp.reader import (
    Message,
    build_list_chats_script,
    build_open_chat_script,
    build_read_messages_script,
    parse_chat_rows,
    parse_message_rows,
    search_loaded_messages,
)

# Sentinels used by the AppleScript ↔ Python protocol.
US = "\x1f"
RS = "\x1e"


def test_build_list_chats_script_respects_limit():
    s = build_list_chats_script(7)
    assert "set maxRows to 7" in s


def test_build_list_chats_script_uses_row_separator():
    s = build_list_chats_script(5)
    # WeChat 4.x emits each row's content as a single comma-joined string
    # in the cell's AXName, so we no longer need a per-field unit separator
    # inside a row — only the row separator that joins rows together.
    assert RS in s
    # Must read the cell's name (4.x location for chat-row data); the v1
    # path read AXValue, which is always missing on 4.x and produced empty
    # rows.
    assert "name of (item 1 of (UI elements of (item 1 of (UI elements of theRow))))" in s


def test_build_open_chat_script_escapes_name():
    s = build_open_chat_script('Group "Foo"')
    assert 'keystroke "Group \\"Foo\\""' in s


def test_build_read_messages_script_clamps_to_tail():
    s = build_read_messages_script(20)
    assert "set maxRows to 20" in s
    # Must walk from (rowCount - maxRows + 1) to rowCount, i.e. tail-end.
    assert "rowCount - maxRows + 1" in s


def test_build_read_messages_script_uses_4x_path():
    """WeChat 4.x: messages live two splitter groups deep, not one.

    The 3.x path ``scroll area 2 of splitter group 1 of front window`` errors
    with -1719 on 4.x. The fix is the doubly-nested splitter group path.
    """
    s = build_read_messages_script(10)
    assert "splitter group 1 of splitter group 1 of front window" in s
    # And we read the cell's AXName (4.x location), not AXValue on
    # descendants (which is always missing in 4.x).
    assert "name of (item 1 of (UI elements of (item 1 of (UI elements of theRow))))" in s
    # Negative: the 3.x sibling-scroll-area path is gone.
    assert "scroll area 2 of splitter group 1 of front window" not in s


def test_parse_chat_rows_simple():
    raw = f"Alice{US}11:23{US}see you tomorrow{RS}文件传输助手{US}{US}{RS}"
    chats = parse_chat_rows(raw)
    assert len(chats) == 2
    assert chats[0].name == "Alice"
    assert chats[0].preview == "see you tomorrow"
    # Single-field row → preview is empty (not duplicated from name).
    assert chats[1].name == "文件传输助手"
    assert chats[1].preview == ""


def test_parse_chat_rows_dedups_name_when_only_one_field():
    raw = f"Alice{US}Alice{RS}"
    chats = parse_chat_rows(raw)
    assert len(chats) == 1
    assert chats[0].name == "Alice"
    # Heuristic: if last field == first, treat as no preview.
    assert chats[0].preview == ""


def test_parse_chat_rows_handles_empty():
    assert parse_chat_rows("") == []
    assert parse_chat_rows(RS + RS) == []


def test_parse_message_rows_skips_timestamp_dividers():
    # v3 fall-back path: rows still arrive with the legacy field separator
    # on older WeChat installs. New code keeps this working.
    raw = (
        f"11:23{RS}"
        f"Alice{US}hi{RS}"
        f"昨天{RS}"
        f"Bob{US}see you{RS}"
        # Date-style divider:
        f"2026-04-25 星期六{RS}"
        f"星期三{RS}"
    )
    msgs = parse_message_rows(raw)
    bodies = [m.body for m in msgs]
    senders = [m.sender for m in msgs]
    assert "hi" in bodies
    assert "see you" in bodies
    assert "Alice" in senders
    assert "Bob" in senders
    assert len(msgs) == 2


def test_parse_message_rows_no_sender_when_first_field_is_long():
    # A long single-field message has no sender prefix and no "Said:" delim
    # → 4.x path: sender empty, body = whole row.
    raw = f"this is a really long single bubble message{RS}"
    msgs = parse_message_rows(raw)
    assert len(msgs) == 1
    assert msgs[0].sender == ""
    assert msgs[0].body == "this is a really long single bubble message"
    assert msgs[0].is_outgoing is False


def test_parse_message_rows_first_field_with_space_is_not_sender():
    # v3 fall-back: "Alice Smith" has a space → don't treat it as a sender.
    raw = f"Alice Smith{US}hello there{RS}"
    msgs = parse_message_rows(raw)
    assert len(msgs) == 1
    assert msgs[0].sender == ""
    assert msgs[0].body == "Alice Smith hello there"


# --- WeChat 4.x "<sender>Said:<body>" format (parser) -----------------------


def test_parse_message_rows_4x_me_marks_outgoing():
    """A 4.x row of the form ``MeSaid:<body>`` flips ``is_outgoing=True``."""
    raw = f"MeSaid:[呲牙]{RS}"
    msgs = parse_message_rows(raw)
    assert len(msgs) == 1
    assert msgs[0].sender == "Me"
    assert msgs[0].body == "[呲牙]"
    assert msgs[0].is_outgoing is True


def test_parse_message_rows_4x_named_sender_is_incoming():
    """``AaronSaid:hi`` → sender=Aaron, outgoing=False."""
    raw = f"AaronSaid:hi{RS}"
    msgs = parse_message_rows(raw)
    assert len(msgs) == 1
    assert msgs[0].sender == "Aaron"
    assert msgs[0].body == "hi"
    assert msgs[0].is_outgoing is False


def test_parse_message_rows_4x_skips_english_month_timestamp():
    """4.x date dividers like ``Apr 15, 2026 20:57`` are not messages."""
    raw = (
        f"AaronSaid:新家！{RS}"
        f"Apr 15, 2026 20:57{RS}"
        f"MeSaid:[呲牙]{RS}"
    )
    msgs = parse_message_rows(raw)
    assert len(msgs) == 2
    assert msgs[0].sender == "Aaron"
    assert msgs[0].body == "新家！"
    assert msgs[0].is_outgoing is False
    assert msgs[1].sender == "Me"
    assert msgs[1].body == "[呲牙]"
    assert msgs[1].is_outgoing is True


def test_parse_message_rows_v3_fallback_preserved():
    """v3 multi-field rows (legacy AppleScript output) still parse cleanly.

    Older WeChat installs that haven't moved to 4.x emit unit-separator-
    joined static text values. We must not regress them.
    """
    raw = (
        f"Alice{US}hi there{RS}"
        f"11:23{RS}"  # divider
        f"Me{US}see you{RS}"  # Me on v3 fallback also marks outgoing
    )
    msgs = parse_message_rows(raw)
    assert len(msgs) == 2
    assert msgs[0].sender == "Alice"
    assert msgs[0].body == "hi there"
    assert msgs[0].is_outgoing is False
    assert msgs[1].sender == "Me"
    assert msgs[1].body == "see you"
    assert msgs[1].is_outgoing is True


def test_search_loaded_messages_basic():
    chats = [
        ("Alice", [Message(sender="Alice", body="hello world", raw="Alice hello world")]),
        ("Bob", [Message(sender="Bob", body="goodbye", raw="Bob goodbye")]),
    ]
    results = search_loaded_messages(chats, query="hello")
    assert len(results) == 1
    assert results[0]["chat"] == "Alice"
    assert results[0]["body"] == "hello world"


def test_search_loaded_messages_case_insensitive():
    chats = [
        ("Alice", [Message(body="HELLO World")]),
    ]
    results = search_loaded_messages(chats, query="hello")
    assert len(results) == 1


def test_search_loaded_messages_respects_limit():
    chats = [
        ("Alice", [Message(body=f"msg {i}") for i in range(10)]),
    ]
    results = search_loaded_messages(chats, query="msg", limit=3)
    assert len(results) == 3


def test_search_loaded_messages_empty_query():
    chats = [("Alice", [Message(body="anything")])]
    assert search_loaded_messages(chats, query="") == []
