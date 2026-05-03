"""Send a WeChat message by driving WeChat for Mac via osascript.

The send flow:

1. ``activate`` WeChat (brings it to front; UI scripting needs the window
   visible — minimised is OK on most macOS versions, but background-only
   isn't reliable).
2. Open the global search palette (Cmd+F is per-conversation; the global
   one is **Cmd+F** with the sidebar focused, but the most reliable cross-
   version trigger is the toolbar search button activated with the chat
   list focused — we use the **Cmd+F** with the main window in front,
   which targets the conversation switcher in WeChat 3.8.x).
3. Type the chat name to filter the sidebar.
4. Press Return to open the top match.
5. Click into the message input field, type the body, press Return to send.

This sequence works for both 1:1 chats and group chats. It does **not**
distinguish between two contacts that share a display name — WeChat returns
its own most-active match. Callers wanting strict targeting should disambig-
uate at the agent layer (e.g. read the chat first to confirm identity).

Only plain text is supported. Attachments / images / emoji shortcodes are
out of scope for v1.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .applescript import (
    ScriptResult,
    escape_applescript_string,
    run_osascript,
)

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    ok: bool
    chat_name: str
    body: str
    stderr: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "chat_name": self.chat_name,
            "body": self.body,
            "stderr": self.stderr,
        }


def build_send_script(chat_name: str, body: str) -> str:
    """Render the AppleScript that sends ``body`` to ``chat_name``.

    Verified live against WeChat for Mac 4.x on 2026-05-02 (admin).

    The structure is intentionally linear — no branching — because debugging
    a multi-step UI script that branches is painful. If a step fails, the
    whole script errors out and the failure mode is recoverable (caller
    retries; nothing was sent).

    Critical CJK fix
    ----------------
    The original implementation used ``keystroke "<name>"`` for both the
    chat-name search and the message body. This silently fails for CJK
    input on macOS: ``keystroke`` posts virtual key events through whatever
    IME is active, and most IMEs route Chinese characters through a
    composition buffer that the MCP can't drive — the search field ends up
    populated with literal romaji like ``a a a a a a`` instead of "老婆".

    Symptom is a textbook pitfall #14 ("DOM .click() returned" ≠ "modal
    opened"): osascript exits 0 and ``ok=True`` propagates back, but no
    message was sent — the search just landed on whatever IME-mangled
    fallback text happened to match.

    Workaround: write the value to the system clipboard and paste with
    ``Cmd+V``. macOS pastes verbatim, bypassing the IME entirely. This
    works for 1:1 chats, group chats, mixed CJK / emoji bodies, and any
    contact name that isn't ASCII. The cost is one extra clipboard write
    per send.

    The ``delay`` values are deliberately conservative. WeChat 4.x can take
    ~300-500ms to render the search dropdown when the contact list is
    large; under-tuning the delay leads to "Return pressed before the chat
    opened" which silently closes the search palette and types the body
    into nowhere.
    """
    safe_name = escape_applescript_string(chat_name)
    safe_body = escape_applescript_string(body)
    return (
        # Stage 0: Set chat-name on clipboard before activating WeChat (so
        # the Cmd+V paste below picks up the right value).
        f'set the clipboard to "{safe_name}"\n'
        'tell application "WeChat" to activate\n'
        'delay 0.5\n'
        'tell application "System Events"\n'
        '  tell process "WeChat"\n'
        # Dismiss any leftover modal/search overlay (Esc twice — one for the
        # search dropdown, one for the conversation switcher itself if it
        # was already open).
        '    key code 53\n'
        '    delay 0.2\n'
        '    key code 53\n'
        '    delay 0.2\n'
        # Open the search palette. Cmd+F is the conversation switcher in
        # both WeChat 3.8.x and 4.x on macOS.
        '    keystroke "f" using {command down}\n'
        '    delay 0.5\n'
        # Clear any leftover search text, then paste the chat name.
        '    keystroke "a" using {command down}\n'
        '    key code 51\n'  # Delete
        '    delay 0.2\n'
        '    keystroke "v" using {command down}\n'
        '    delay 0.7\n'
        # Open the top match.
        '    key code 36\n'  # Return
        '    delay 0.7\n'
        # Focus the message input. Tab moves focus from the chat list to
        # the input area on 4.x; we then Cmd+A + Delete to clear any draft
        # text that may have been there.
        '    keystroke tab\n'
        '    delay 0.3\n'
        '    keystroke "a" using {command down}\n'
        '    key code 51\n'  # Delete
        '    delay 0.2\n'
        '  end tell\n'
        'end tell\n'
        # Stage 1: Set body on clipboard, then paste + send.
        f'set the clipboard to "{safe_body}"\n'
        'tell application "System Events"\n'
        '  tell process "WeChat"\n'
        '    keystroke "v" using {command down}\n'
        '    delay 0.4\n'
        '    key code 36\n'  # Return → send
        '    delay 0.3\n'
        '  end tell\n'
        'end tell\n'
    )


def send_wechat_message(
    chat_name: str,
    body: str,
    runner: str | None = None,
    timeout: float = 20.0,
) -> SendResult:
    """Send ``body`` to ``chat_name`` via the WeChat for Mac UI.

    Args:
        chat_name: Display name of the chat as it appears in the WeChat
            sidebar. For groups, use the exact group name. For 1:1 chats,
            use the contact's WeChat display name (not your alias for them
            — WeChat search matches against the sender's own profile name).
        body: Plain-text message. ``"`` and ``\\`` are escaped automatically.
        runner: Override path to ``osascript`` (tests).
        timeout: Hard cap on the script's runtime. Bumped above the iMessage
            default (10s) because WeChat's search palette can take ~3s to
            populate when the contact list is large.

    Returns a :class:`SendResult`. On failure, ``stderr`` contains the
    osascript diagnostic so callers can surface a meaningful error to the
    agent (and from there, to the human).
    """
    if not chat_name:
        return SendResult(ok=False, chat_name=chat_name, body=body, stderr="empty chat_name")
    if not body:
        return SendResult(ok=False, chat_name=chat_name, body=body, stderr="empty body")

    script = build_send_script(chat_name, body)
    res: ScriptResult = run_osascript(script, timeout=timeout, runner=runner)

    if not res.ok:
        return SendResult(ok=False, chat_name=chat_name, body=body, stderr=res.stderr or res.stdout)

    return SendResult(ok=True, chat_name=chat_name, body=body, stderr="")
