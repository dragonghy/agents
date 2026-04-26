# imessage-mcp

MCP server that exposes the macOS Messages app to a personal AI agent.

> **Personal-agent only.** This server is intentionally **not** mounted on any
> work agent (admin, ops, dev-alex, qa-lucy, …). It's wired up via
> `agents.yaml` → `mcp_servers.imessage_personal` and only attached to the
> personal agent type. Work agents that try to call `mcp__imessage_personal__*`
> will get a "tool not found" error.

## Tools

| Tool | What it does |
| --- | --- |
| `imessage_list_chats(limit=20)` | Most-recently-active conversations with previews + unread counts |
| `imessage_get_chat(handle, limit=50)` | Last N messages with one contact (oldest-first) |
| `imessage_search(query, days=7)` | Case-insensitive keyword search over recent messages |
| `imessage_unread()` | All unread inbound messages, newest-first |
| `imessage_send(handle, body, service="iMessage")` | Sends via Messages.app (osascript bridge) |

`handle` is a phone number in E.164 form (`+15551234567`), an email, or a
group chat identifier (e.g. `chat493929391`).

## Permissions

Reading `~/Library/Messages/chat.db` requires **Full Disk Access** for the
process that hosts the MCP. That process is whatever spawned Claude Code:

- If Claude Code runs from **Terminal.app** or **iTerm2.app**, grant FDA to
  the terminal app.
- If Claude Code runs as **Claude Desktop**, grant FDA to Claude Desktop.

### Granting FDA

1. Open **System Settings → Privacy & Security → Full Disk Access**.
2. Click `+` and add the host application.
3. **Restart the host application** — FDA is checked at process spawn time;
   already-running processes retain their previous permission state.

### Self-check

```bash
uv run --directory services/imessage-mcp python -m imessage_mcp --check
```

A passing run looks like:
```
chat.db path: /Users/you/Library/Messages/chat.db
OK: chat.db opened read-only, 41217 message rows visible.
```

A failing run prints the exact next step.

## Sending

`imessage_send` shells out to `osascript` and asks Messages.app to deliver
the message. Messages.app must be set up at least once and signed into iCloud.

The body is escaped for AppleScript (`"` and `\` only). Newlines are passed
through as literal `\n` inside the AppleScript string.

If the recipient isn't an iMessage user, the call fails (Messages.app errors).
Pass `service="SMS"` to try SMS — that requires a paired iPhone via Continuity
on the same Apple ID.

## chat.db decoding notes

- `message.date` is **nanoseconds since 2001-01-01 UTC**. Conversion: divide
  by 1e9 and add 978307200 to get Unix seconds.
- iOS 14+ stores rich-text bodies in `message.attributedBody` (an
  NSKeyedArchiver blob) instead of `message.text`. This server does an
  in-process byte-scan to extract the readable substring; on rare failures
  (custom attributes, embedded URLs only) the message text is reported as
  `"(unable to decode message body)"` with `decode_failed: true`.
- The DB is opened with the SQLite `mode=ro` URI flag — this server cannot
  modify chat.db.

## Limitations / out of scope

- Group-chat sending (read-only for groups in v1)
- Attachment download / upload
- Contacts integration (separate MCP planned)
- Message reactions / tapbacks (best-effort decoder skips these)

## Development

```bash
cd services/imessage-mcp
uv sync
uv run pytest
```

Tests under `tests/` are pure-function unit tests (epoch math, decoder,
osascript escaping). Live-database integration is a manual step — see the
self-check command above.
