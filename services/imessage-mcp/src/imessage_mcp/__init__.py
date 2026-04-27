"""iMessage MCP — read and send macOS iMessage from a personal-agent context.

Tools exposed via FastMCP:
- imessage_list_chats(limit)          — recent conversations
- imessage_get_chat(handle, limit)    — message history with one contact
- imessage_search(query, days)        — keyword search
- imessage_send(handle, body)         — send via osascript
- imessage_unread()                   — unread count + previews

Read path: ~/Library/Messages/chat.db (SQLite, opened mode=ro).
Send path: osascript driving Messages.app.

Requires Full Disk Access for the host process to read chat.db.
"""

__version__ = "0.1.0"
