---
name: personal-mcp-toolkit
description: How to use the personal-life MCPs (Gmail / Calendar / Drive / iMessage / WeChat) bound to assistant-aria. Use when Human asks aria to read mail, check schedule, follow up on a text, or message someone.
---

# Personal MCP Toolkit

This skill is the daily-use playbook for aria's four personal MCPs. Setup is documented separately in `google-personal-mcp` (Google OAuth one-time provisioning) and the `services/<mcp>/README.md` files. **This doc is for after the wiring is done.**

## Who this skill is for

- **assistant-aria** — the only agent that has these MCPs mounted (per-agent isolation via `agents.assistant-aria.extra_mcp_servers`; see claude.md pitfall #13). Work agents (admin / dev-alex / qa-lucy / ops) cannot call any of the tools below — they're not in those agents' MCP sets.

## Quick reference — which MCP for which job

| Human asks | MCP | Tool |
|---|---|---|
| "Any new email about X?" | google_personal | `search_gmail_messages` then `get_gmail_message_content` |
| "What's on my calendar tomorrow?" | google_personal | `get_events` |
| "Add a meeting at 3pm" | google_personal | `manage_event` (create) |
| "Pull that doc I shared" | google_personal | `search_drive_files` then `get_drive_file_content` |
| "Reply 'on my way' to <person>" | imessage_personal | `imessage_send` |
| "Did <person> text me back?" | imessage_personal | `imessage_get_chat` |
| "Any unread iMessages?" | imessage_personal | `imessage_unread` |
| "Tell my wife I'll be late" (微信) | wechat_personal | `wechat_send` |
| "Any new WeChat from <person>?" | wechat_personal | `wechat_get_chat` |
| "Show me recent WeChat conversations" | wechat_personal | `wechat_list_chats` |

## 1. Google Personal (Gmail + Calendar + Drive)

**Backend**: `taylorwilsdon/google_workspace_mcp` (`uvx workspace-mcp --single-user`). Token lives at `~/.google_workspace_mcp/credentials/<gmail>.json` and auto-refreshes; you don't manage it.

### Tools (high-frequency)

| Tool | What it does | Notes |
|---|---|---|
| `search_gmail_messages(q, max_results)` | Gmail search, returns IDs + thread IDs | Use Gmail query syntax: `from:bob@example.com`, `is:unread`, `after:2026/05/01`, `subject:invoice`. Combine with AND/OR. |
| `get_gmail_message_content(message_id)` | Full email body + headers | Use after search; bodies can be large, summarise before showing Human |
| `send_gmail_message(to, subject, body, ...)` | Send email | Always run a draft past Human first if substantive. For "ack" / "got it" replies, send directly is fine |
| `manage_gmail_label(...)` | Apply / remove labels | Useful for "archive everything from X" workflows |
| `list_calendars()` | Shows all accessible calendars | Run once if you need a non-primary calendar ID |
| `get_events(time_min, time_max, calendar_id)` | List events in a window | Default `calendar_id="primary"` |
| `manage_event(action, ...)` | Create / update / delete | `action="create"` requires `start`, `end`, `summary` |
| `search_drive_files(query)` | Drive file search | `query` uses Drive's syntax (`name contains 'foo'`, `mimeType='application/pdf'`) |
| `get_drive_file_content(file_id)` | Read file content | Google Docs auto-export to plaintext; PDFs OCR'd by Drive; sheets export as CSV |

### Gotchas

- **Drive is read-only by default** (`drive:readonly` permission). You can list and read but not create/edit. If Human asks to upload, escalate — admin needs to bump permissions and re-auth.
- **Test-user mode**: Human is the only authorised Gmail account. Sending/reading ON BEHALF OF a different account will fail with "access blocked".
- **Calendar timezone**: events come back with `dateTime` in RFC3339; if Human asks "what's at noon?" remember to convert to America/Los_Angeles.
- **Don't read the entire inbox**: `search_gmail_messages` defaults are sensible. Don't do `q=""` with `max_results=1000`.

### Typical flow — "any new email from Bob?"

1. `search_gmail_messages(q="from:bob@example.com is:unread", max_results=5)`
2. For each result, `get_gmail_message_content(message_id)`
3. Summarise: "3 new from Bob since Monday — 1 about lunch Tues, 1 forwarding the CRWV pitch deck, 1 birthday wishes for your dad."
4. Don't paste full bodies unless Human asks.

## 2. iMessage Personal

**Backend**: `services/imessage-mcp/` (Python + FastMCP, reads `~/Library/Messages/chat.db` read-only via SQLite, sends via `osascript` Messages.app bridge). Requires Full Disk Access on the host terminal — see pitfall #15.

### Tools

| Tool | What it does | Notes |
|---|---|---|
| `imessage_list_chats(limit=20)` | Most-recently-active conversations | Returns handles (E.164 / email / group ID) + last message preview + unread count |
| `imessage_get_chat(handle, limit=50)` | Last N messages in one conversation | `handle` is the same value `list_chats` returned. Group chats: `chat493929391` form |
| `imessage_search(query, days=7)` | Substring search across recent messages | Case-insensitive |
| `imessage_unread()` | All unread inbound messages, newest-first | Use to start a "what did I miss?" summary |
| `imessage_send(handle, body, service="iMessage")` | Send via Messages.app | `service="SMS"` falls back to green-bubble. Body supports unicode + emoji |

### Gotchas

- **Read is fast (SQLite), send is slow (~1-2s osascript bridge).** Don't issue 5 sends in a tight loop without Human's intent — batch into one message instead.
- **`attributedBody` decode is best-effort** (pitfall #16): rich-text messages from iOS 14+ sometimes show `text="(unable to decode message body)"` with `decode_failed: true`. Treat as expected, not as a parser bug. Tell Human "X messages couldn't be decoded — those are typically link previews / styled text."
- **Group chats are write-able**: `imessage_send("chat493929391", "...")` posts to the group. Verify the handle is what you think before sending — admin can't undo.
- **Don't dump the whole `chat.db`**: 17k+ rows is normal. Use `list_chats(limit=10)` then drill into specifics.

### Typical flow — "what did I miss?"

1. `imessage_unread()`
2. Group by handle, summarise: "3 unread — Mom (kid pickup question), FasTrak (card-expiring reminder), 1 verification code from Jun Bistro."
3. Ask Human "want me to ack Mom?" before drafting.

## 3. WeChat Personal

**Backend**: `services/wechat-mcp/` (Python + FastMCP, drives WeChat for Mac via osascript / System Events Accessibility tree). Pure UI automation — no DB read, no protocol. Picked specifically to keep account-ban risk near zero. Requires Accessibility + Automation permissions on the host terminal — see `services/wechat-mcp/README.md`.

### Tools

| Tool | What it does | Notes |
|---|---|---|
| `wechat_list_chats(limit=20)` | Recent sidebar chats with name + preview | **Read-only**, doesn't take focus from Human's keyboard |
| `wechat_get_chat(chat_name, limit=50)` | Recent messages in one chat | **Takes focus briefly** to navigate to the chat. `chat_name` is the exact display name from `list_chats`. (Group names that contain commas may truncate the preview but the name field stays intact.) |
| `wechat_search(query, ...)` | Substring search over messages already loaded into Python via `get_chat` | The MCP is stateless — you must `get_chat` first, then search what you have |
| `wechat_send(chat_name, body)` | Send a plain-text message | **Takes over keyboard for ~3-5s** — see "Focus etiquette" below |

### Focus etiquette (important)

`wechat_send` takes over Human's keyboard for ~3-5 seconds because System Events posts virtual key events into the system input queue. **Read tools (`list_chats`, `get_chat`, `search`) only briefly activate WeChat without typing**, but `send` is fully intrusive.

**Rules**:
- For **batch sends** (e.g. 3 different recipients): warn Human via `send_human_message` "I'm about to send 3 WeChat messages, ~15s of keyboard blackout, OK to proceed?" before firing.
- If Human is mid-conversation in another app, **defer** sends until they ack.
- A single send during normal interaction is fine — just don't surprise them when they're typing.
- **Never send during Telegram backchannel** with Human — your own Telegram messages would race with WeChat keystrokes.

### Gotchas

- **CJK works via clipboard paste** (post 2026-05-02 fix). Earlier `keystroke "<chinese>"` failed silently because of IME composition; current implementation pastes both chat name and body via `Cmd+V`. You don't need to do anything special — just call `wechat_send("老婆", "晚饭吃啥")`.
- **Chat name disambiguation**: if Human has two contacts called "Mike", WeChat opens the most-active match. To target a specific Mike, prepend a unique substring of his contact alias or group prefix before sending.
- **Moments (朋友圈) is NOT supported** — `services/wechat-mcp` v1 explicitly excludes it. If Human asks "what did 王栋 post on Moments?", say "WeChat MCP doesn't read Moments; would you like me to file a feature ticket?"
- **Voice / Image / Sticker bodies show as `[Photo]`, `[Voice Call]`, `[Sticker]`** in `get_chat` — the AX tree gives placeholders, not media. Tell Human and ask if they want to switch to phone for that thread.
- **WeChat must be in foreground / window visible** for sends to work. If WeChat is minimised, the send fails silently. The MCP `--check` command confirms this; if `wechat_send` returns `ok=False`, that's usually the cause.
- **Outgoing detection** is heuristic via the `MeSaid:` prefix the AX tree emits. Reliable for 1:1 chats; in groups, treat `is_outgoing=True` as "from Human" and everything else as "from someone else in the group".

### Typical flow — "tell my wife I'll be late"

1. Confirm chat name with `wechat_list_chats(limit=10)` — find the row with handle "老婆".
2. Draft body: "我大概晚 30 分钟，先吃别等我"
3. **Confirm with Human first** (real-life consequences if wrong recipient) — `send_human_message("即将发给【老婆】：'我大概晚 30 分钟，先吃别等我'，OK 吗？")`
4. After Human ack: `wechat_send(chat_name="老婆", body="...")`
5. Verify `ok=True`. If `False`, escalate the `stderr` to Human.

### Pitfall #14 reminder — "ok=True ≠ delivered"

`wechat_send` returns `ok=True` if osascript exits 0, but that only means "the script ran without syntax/permission errors". It does **not** prove the message was actually delivered to WeChat servers — just that the keystroke sequence completed locally. For high-stakes sends (e.g. medical reschedule, money transfer ack), follow up with `wechat_get_chat(chat_name, limit=3)` and confirm your body appears as `MeSaid:<body>` in the latest message.

## Cross-MCP patterns

### "What's the situation today?" (morning catch-up)

When Human asks for a daily catch-up, run these in parallel and synthesise:

1. `imessage_unread()` — unread iMessages
2. `wechat_list_chats(limit=10)` — recent WeChat chats (preview shows last incoming if unread)
3. `search_gmail_messages(q="is:unread is:important", max_results=10)` — important unread email
4. `get_events(time_min=now, time_max=now+24h)` — today's calendar

Synthesise into 4 sections: **iMessage** / **WeChat** / **Email** / **Calendar**, with counts + 1-line summary of each notable item. Hold the full bodies — Human asks "tell me more about X" if they want depth.

### "Did I respond to <person>?"

Cross-check across iMessage and WeChat (Gmail's threading handles email itself):
1. `imessage_search(query=<person's name or known phrase>)` — check iMessage history
2. `wechat_list_chats(limit=20)` then drill into matching name with `wechat_get_chat`
3. Report: "Last incoming from <X> was <when>; you replied <when> with <preview>" or "No reply since <when>".

### Sending "the same message" to multiple platforms

If Human asks to alert several people across platforms:
1. **Group consent** — list all recipients in one `send_human_message`, get one ack.
2. Send each in series (don't parallelise — keyboard conflicts on WeChat sends).
3. Confirm delivery one-by-one before moving to the next.
4. Final summary: "Sent to A (iMessage ✓), B (WeChat ✓), C (Email ✓)".

## What this skill does NOT cover

- **Setup / first-time provisioning**: see `google-personal-mcp` skill for OAuth, and `services/<mcp>/README.md` for FDA / Accessibility / Automation grants.
- **Failure recovery when permissions revoked**: tell Human "Run `uv run --directory services/<mcp> python -m <mcp> --check` from terminal — paste me the output" and escalate.
- **Adding a new personal MCP**: that's an admin-level architectural change (per-agent isolation rules, see pitfall #13).
- **Moments / file attachments / voice / video**: explicitly out of scope for the v1 MCPs.

## References

- Setup: `projects/agent-hub/skills/google-personal-mcp/SKILL.md`
- iMessage source: `services/imessage-mcp/` (README has FDA grant steps)
- WeChat source: `services/wechat-mcp/` (README has Accessibility + Automation grant steps)
- Pitfall #13 (per-agent MCP isolation): `claude.md`
- Pitfall #14 ("`ok=True` ≠ side-effect succeeded"): `claude.md`
- Pitfall #15 (FDA on terminal host, not Claude Code): `claude.md`
- Pitfall #16 (`attributedBody` decode best-effort): `claude.md`
