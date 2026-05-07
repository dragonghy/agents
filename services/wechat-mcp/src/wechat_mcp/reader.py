"""Read WeChat sidebar (recent chats) and a chat's message history.

This module is the *fragile* one. WeChat for Mac doesn't expose chats or
messages through a stable AppleScript dictionary — there's no
``every chat`` collection. We use ``System Events`` to walk the
Accessibility tree of the running WeChat process and read the visible UI.

Because UI hierarchies shift between WeChat releases, every selector is
isolated in this file with a comment naming the WeChat version it was
verified against. If a future release breaks reading, the diff lives here
only.

Verified against:
- WeChat for Mac 3.8.10 (running on macOS during initial implementation;
  live verification deferred until Accessibility is granted to the host
  terminal — see README.md).

The shape of the WeChat 3.8.x main window:

::

    AXWindow "WeChat"
    └── AXSplitGroup
        ├── (left) AXScrollArea  — sidebar (recent chats list)
        │   └── AXTable / AXOutline
        │       └── AXRow*  — each row = a chat
        │           └── AXCell containing labels for name + preview
        └── (right) AXSplitGroup
            ├── AXScrollArea — message scrollback
            │   └── AXTable
            │       └── AXRow*  — each row = a message bubble
            └── AXTextArea / AXScrollArea — message input

We deliberately *do not* attempt to scrape unread badges in v1. WeChat
draws those as overlays that don't expose a stable AXValue — getting them
right requires per-version tuning. Callers should treat ``unread=None`` as
"unknown" rather than "zero".
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .applescript import ScriptResult, escape_applescript_string, run_osascript

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ChatSummary:
    """One row of the WeChat sidebar."""

    name: str
    preview: str = ""
    unread: int | None = None  # None = unknown (not zero)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "preview": self.preview,
            "unread": self.unread,
        }


@dataclass
class Message:
    """One message bubble inside a chat."""

    sender: str = ""  # "" = unknown / outgoing
    body: str = ""
    is_outgoing: bool = False
    raw: str = ""  # untouched UI text for debugging

    def to_dict(self) -> dict:
        return {
            "sender": self.sender,
            "body": self.body,
            "is_outgoing": self.is_outgoing,
            "raw": self.raw,
        }


@dataclass
class ReadError:
    """Wrapper for callers when the UI scrape fails."""

    message: str
    stderr: str = ""

    def to_dict(self) -> dict:
        return {"error": self.message, "stderr": self.stderr}


# ---------------------------------------------------------------------------
# AppleScript builders
# ---------------------------------------------------------------------------

# Sentinel separators we use inside AppleScript to delimit fields/rows.
# Chosen as ASCII control characters so they never collide with chat names
# or message bodies (which may contain emoji, Chinese punctuation, newlines,
# tabs, etc.).
_FIELD_SEP = "\x1f"  # Unit Separator
_ROW_SEP = "\x1e"    # Record Separator


def build_list_chats_script(limit: int) -> str:
    """AppleScript that reads the sidebar rows and emits one row per chat.

    Implementation notes — verified live against WeChat for Mac 4.x on
    2026-05-02 (admin):

    - WeChat 4.x stores each sidebar row's full descriptor in the AXName of
      the row's grandchild cell, NOT in any AXValue. The descriptor is a
      single comma-separated string, e.g.::

          老婆,携程这是精准推送吗,15:23,Sticky on Top

      The original v1 implementation walked ``entire contents`` looking for
      ``value of anElem`` — every probe returned ``missing value`` because
      WeChat doesn't populate AXValue on these elements. That's why the
      first run of this MCP returned 0 chats despite the sidebar being
      visibly populated.
    - We extract the row's ``name of (UI element 1 of UI element 1 of
      theRow)`` and let the Python parser split on comma. First field is
      reliably the chat name; remaining fields are preview / time / status
      markers.
    """
    return (
        'tell application "WeChat" to activate\n'
        'delay 0.4\n'
        'tell application "System Events"\n'
        '  tell process "WeChat"\n'
        '    set chatLines to {}\n'
        '    set rowList to (rows of table 1 of scroll area 1 of '
        '      splitter group 1 of front window)\n'
        f'    set maxRows to {int(limit)}\n'
        '    if (count of rowList) < maxRows then set maxRows to (count of rowList)\n'
        '    repeat with i from 1 to maxRows\n'
        '      set theRow to item i of rowList\n'
        '      set rowName to ""\n'
        '      try\n'
        '        set rowName to name of (item 1 of (UI elements of (item 1 of (UI elements of theRow))))\n'
        '      end try\n'
        '      if rowName is missing value then set rowName to ""\n'
        '      set end of chatLines to (rowName as text)\n'
        '    end repeat\n'
        f'    set AppleScript\'s text item delimiters to "{_ROW_SEP}"\n'
        '    return chatLines as text\n'
        '  end tell\n'
        'end tell\n'
    )


def build_open_chat_script(chat_name: str) -> str:
    """AppleScript that opens ``chat_name`` via the conversation switcher.

    Uses the same Cmd+F flow as the sender — the only reliable cross-version
    way we found to navigate to a chat by name. Returns "ok" on success
    (the caller follows up with :func:`build_read_messages_script`).
    """
    safe_name = escape_applescript_string(chat_name)
    return (
        'tell application "WeChat" to activate\n'
        'delay 0.4\n'
        'tell application "System Events"\n'
        '  tell process "WeChat"\n'
        '    keystroke "f" using {command down}\n'
        '    delay 0.4\n'
        f'    keystroke "{safe_name}"\n'
        '    delay 0.6\n'
        '    key code 36\n'  # Return
        '    delay 0.5\n'
        '  end tell\n'
        'end tell\n'
        'return "ok"\n'
    )


def build_read_messages_script(limit: int) -> str:
    """Read the currently-open chat's visible messages.

    *Important*: this scrapes only what's currently in WeChat's render
    buffer. WeChat lazy-loads history as you scroll up; this script doesn't
    auto-scroll because doing so reliably across versions adds complexity
    we don't need for the v1 contract ("most recent N messages").

    For most chats the rendered tail is 30–80 messages, which comfortably
    covers the ``limit <= 50`` documented ceiling.

    Implementation notes — verified live against WeChat for Mac 4.x on
    2026-05-02 (admin):

    - The right pane in WeChat 4.x is wrapped in **two** nested splitter
      groups, not one. The 3.x path
      ``scroll area 2 of splitter group 1 of front window`` errors out with
      ``Can't get scroll area 2 ... Invalid index. (-1719)`` because there
      simply isn't a sibling scroll area at that depth anymore. The 4.x
      path is::

          table 1 of scroll area 1 of splitter group 1 of splitter group 1
              of front window

    - Same v3→v4 attribute drift the sidebar already hit (see
      :func:`build_list_chats_script`): WeChat 4.x stores the row's text
      content in the AXName of the inner cell, not in any AXValue on
      descendants. The 3.x ``value of anElem`` walk returned ``missing
      value`` for everything, which is why the read returned empty bodies
      even when the AppleScript path *did* match.

    - Each row's ``AXName`` is a single string of the form
      ``<sender>Said:<body>`` (e.g. ``MeSaid:[呲牙]``, ``AaronSaid:新家！``).
      Date dividers are their own rows with content like
      ``Apr 15, 2026 20:57``. Parsing happens in
      :func:`parse_message_rows`.
    """
    return (
        'tell application "System Events"\n'
        '  tell process "WeChat"\n'
        '    set msgs to {}\n'
        # WeChat 4.x: messages live two splitter groups deep.
        '    set rowList to (rows of table 1 of scroll area 1 of '
        '      splitter group 1 of splitter group 1 of front window)\n'
        f'    set maxRows to {int(limit)}\n'
        '    set rowCount to (count of rowList)\n'
        '    set startIdx to rowCount - maxRows + 1\n'
        '    if startIdx < 1 then set startIdx to 1\n'
        '    repeat with i from startIdx to rowCount\n'
        '      set theRow to item i of rowList\n'
        '      set rowName to ""\n'
        '      try\n'
        # Read the cell's AXName (the 4.x location for row content). Same
        # nesting depth the sidebar fix uses: cell -> first UI element ->
        # first UI element.
        '        set rowName to name of (item 1 of (UI elements of (item 1 of (UI elements of theRow))))\n'
        '      end try\n'
        '      if rowName is missing value then set rowName to ""\n'
        '      set end of msgs to (rowName as text)\n'
        '    end repeat\n'
        f'    set AppleScript\'s text item delimiters to "{_ROW_SEP}"\n'
        '    return msgs as text\n'
        '  end tell\n'
        'end tell\n'
    )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_chat_rows(raw: str) -> list[ChatSummary]:
    """Parse the row-separated descriptors from list-chats.

    WeChat 4.x emits each row as a single comma-joined string built by the
    OS accessibility layer, e.g.::

        老婆,携程这是精准推送吗,15:23,Sticky on Top

    The first comma-delimited field is the chat name (what callers will
    pass back to ``wechat_get_chat`` / ``wechat_send`` — getting that right
    is the priority). The second field is the most recent preview text; the
    third is the timestamp; remaining fields are sticky/mute markers.

    This is intentionally heuristic. Chat names containing literal commas
    will be slightly truncated on the preview side, but the name field
    stays intact.
    """
    if not raw:
        return []
    out: list[ChatSummary] = []
    for row in raw.split(_ROW_SEP):
        row = row.strip()
        if not row:
            continue
        # WeChat 4.x format: "<name>,<preview>,<time>[,<status>]" — we keep
        # only the first two fields. The legacy unit-separator path is kept
        # as a fall-back so that older WeChat versions (where the v1 code
        # path produced \x1f-joined static-text values) still work without
        # a re-release.
        if _FIELD_SEP in row:
            fields = [f.strip() for f in row.split(_FIELD_SEP) if f.strip()]
            if not fields:
                continue
            name = fields[0]
            preview = fields[-1] if len(fields) > 1 else ""
            if preview == name:
                preview = ""
        else:
            parts = [p.strip() for p in row.split(",")]
            if not parts:
                continue
            name = parts[0]
            preview = parts[1] if len(parts) > 1 else ""
        out.append(ChatSummary(name=name, preview=preview))
    return out


_TIMESTAMP_PATTERN = re.compile(
    # CJK + 24h (3.x): "11:23", "昨天", "今天", "星期三", "2026-04-25 ..."
    r"^(?:\d{1,2}[:：]\d{2}|昨天|今天|星期[一二三四五六日天]|"
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}.*|"
    # English-month divider (4.x): "Apr 15, 2026 20:57", "April 15, 2026"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s*\d{4}.*)$"
)

# WeChat 4.x packs each message row's AXName as "<sender>Said:<body>".
# Splitting on the first occurrence of ``Said:`` is how we recover sender +
# body. We deliberately use a literal "Said:" rather than a regex with word
# boundaries — sender names can be single CJK characters or contain non-word
# punctuation, and a body starting with whitespace or punctuation is fine.
_WECHAT_4X_SAID_DELIM = "Said:"


def parse_message_rows(raw: str) -> list[Message]:
    """Parse the row-separated output from :func:`build_read_messages_script`.

    WeChat 4.x format (one row per message, no per-field unit separator)::

        AaronSaid:新家！\\x1eApr 15, 2026 20:57\\x1eMeSaid:[呲牙]\\x1e

    Each non-divider row is a single string of the form
    ``<sender>Said:<body>``. The sender ``Me`` is the user's own messages —
    those flip ``is_outgoing=True``. Date / time divider rows (matching
    :data:`_TIMESTAMP_PATTERN`, e.g. ``Apr 15, 2026 20:57``, ``11:23``,
    ``昨天``) are skipped.

    A v3 fall-back path is preserved for the legacy AppleScript output
    (rows containing :data:`_FIELD_SEP`). Older WeChat installs that
    haven't upgraded to 4.x still produce the unit-separator-joined static
    text values that the v1 parser was designed for, so we keep the
    multi-field heuristic alive.
    """
    if not raw:
        return []
    out: list[Message] = []
    for row in raw.split(_ROW_SEP):
        row = row.strip()
        if not row:
            continue

        # v3 legacy fall-back: if the row carries the legacy field separator,
        # parse it with the multi-field heuristic preserved from v1.
        if _FIELD_SEP in row:
            parsed = _parse_v3_row(row)
            if parsed is not None:
                out.append(parsed)
            continue

        # WeChat 4.x: skip pure timestamp / date dividers.
        if _TIMESTAMP_PATTERN.match(row):
            continue

        sender = ""
        body = row
        is_outgoing = False
        if _WECHAT_4X_SAID_DELIM in row:
            head, _, tail = row.partition(_WECHAT_4X_SAID_DELIM)
            sender_candidate = head.strip()
            # Only accept the prefix as a sender if it's plausibly a name
            # (non-empty, doesn't itself look like a divider). This guards
            # against pathological bodies like "I Said:hi" being mis-split.
            if sender_candidate and not _TIMESTAMP_PATTERN.match(sender_candidate):
                sender = sender_candidate
                body = tail
                # WeChat tags the user's own messages with the literal
                # sender "Me" (English UI). This is the only AX-tree signal
                # we get for outgoing vs incoming; older v1 code couldn't
                # distinguish at all.
                if sender == "Me":
                    is_outgoing = True

        out.append(Message(sender=sender, body=body, is_outgoing=is_outgoing, raw=row))
    return out


def _parse_v3_row(row: str) -> Message | None:
    """v3 multi-field row parser, preserved for backwards compatibility.

    Mirrors the original v1 heuristic: split on :data:`_FIELD_SEP`, drop
    pure-timestamp single-field rows, treat a short whitespace-free first
    field as a sender prefix.
    """
    fields = [f.strip() for f in row.split(_FIELD_SEP) if f.strip()]
    if not fields:
        return None
    joined = " ".join(fields)
    if len(fields) == 1 and _TIMESTAMP_PATTERN.match(fields[0]):
        return None
    sender = ""
    body = joined
    if len(fields) >= 2:
        head = fields[0]
        if (
            len(head) <= 30
            and " " not in head
            and not _TIMESTAMP_PATTERN.match(head)
        ):
            sender = head
            body = " ".join(fields[1:])
    is_outgoing = sender == "Me"
    return Message(sender=sender, body=body, is_outgoing=is_outgoing, raw=joined)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_recent_chats(
    limit: int = 20,
    runner: str | None = None,
) -> list[ChatSummary] | ReadError:
    res: ScriptResult = run_osascript(
        build_list_chats_script(limit),
        timeout=15.0,
        runner=runner,
    )
    if not res.ok:
        return ReadError(message="failed to read sidebar", stderr=res.stderr or res.stdout)
    return parse_chat_rows(res.stdout)


def read_chat_messages(
    chat_name: str,
    limit: int = 50,
    runner: str | None = None,
) -> list[Message] | ReadError:
    if not chat_name:
        return ReadError(message="chat_name is required")

    open_res = run_osascript(
        build_open_chat_script(chat_name),
        timeout=15.0,
        runner=runner,
    )
    if not open_res.ok:
        return ReadError(message="failed to open chat", stderr=open_res.stderr or open_res.stdout)

    read_res = run_osascript(
        build_read_messages_script(limit),
        timeout=15.0,
        runner=runner,
    )
    if not read_res.ok:
        return ReadError(message="failed to read messages", stderr=read_res.stderr or read_res.stdout)
    return parse_message_rows(read_res.stdout)


def search_loaded_messages(
    chats: list[tuple[str, list[Message]]],
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Filter messages already pulled from WeChat by case-insensitive substring.

    The WeChat MCP doesn't keep its own message store — search is over what
    the caller has already loaded via :func:`read_chat_messages`. This is
    deliberate: it keeps the MCP stateless and dodges the question of "where
    do we cache messages without writing local files".

    A future v2 may add a session-scoped cache, but YAGNI for v1 and the
    agent loop can drive multi-chat search itself.
    """
    if not query:
        return []
    q = query.casefold()
    results: list[dict[str, Any]] = []
    for chat_name, msgs in chats:
        for m in msgs:
            haystack = (m.body + " " + m.sender).casefold()
            if q in haystack:
                results.append({"chat": chat_name, **m.to_dict()})
                if len(results) >= limit:
                    return results
    return results
