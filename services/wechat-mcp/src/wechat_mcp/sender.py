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

    The structure is intentionally linear — no branching — because debugging
    a multi-step UI script that branches is painful. If a step fails, the
    whole script errors out and the failure mode is recoverable (caller
    retries; nothing was sent).

    The ``delay`` values are deliberately conservative. WeChat 3.8.x is
    sometimes sluggish to render the search results list; under-tuning the
    delay leads to "Return pressed before the chat opened" which silently
    closes the search palette.
    """
    safe_name = escape_applescript_string(chat_name)
    safe_body = escape_applescript_string(body)
    return (
        'tell application "WeChat" to activate\n'
        'delay 0.5\n'
        'tell application "System Events"\n'
        '  tell process "WeChat"\n'
        # Open the search palette. Cmd+F is the documented shortcut for
        # WeChat for Mac's conversation switcher (3.8.x).
        '    keystroke "f" using {command down}\n'
        '    delay 0.4\n'
        # Type the chat name into the search field.
        f'    keystroke "{safe_name}"\n'
        '    delay 0.6\n'
        # Open the top match.
        '    key code 36\n'  # Return
        '    delay 0.6\n'
        # Focus the message input. WeChat for Mac binds the input as the
        # default focus when a chat is opened, but a stray focus on the
        # message list (e.g. after arrow-key search) means typing would do
        # nothing. Tab moves focus to the input area on 3.8.x; we then
        # follow with Cmd+A to select-all (no-op if input was empty) and
        # Delete to clear any draft text the user had typed.
        '    keystroke tab\n'
        '    delay 0.2\n'
        '    keystroke "a" using {command down}\n'
        '    key code 51\n'  # Delete
        '    delay 0.1\n'
        # Type the body and send.
        f'    keystroke "{safe_body}"\n'
        '    delay 0.3\n'
        '    key code 36\n'  # Return → send
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
