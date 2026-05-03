# Telegram Channel Adapter — manual smoke runbook

> Phase 4 (#26) ships the Telegram bot rewired as an orchestration v1
> channel adapter. The end-to-end Human → Telegram → daemon → secretary →
> Telegram round-trip is **not automated** — Telegram is hard to drive
> headlessly. This runbook documents the manual verification path.

## Prereqs

- `.env` configured with `TELEGRAM_BOT_TOKEN`, `HUMAN_TELEGRAM_CHAT_ID`
  (or legacy `TELEGRAM_HUMAN_CHAT_ID`).
- `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` set.
- Daemon running on `127.0.0.1:8765`:
  ```bash
  uv run --directory services/agents-mcp agents-mcp --daemon \
    --host 127.0.0.1 --port 8765
  ```
- Bot running:
  ```bash
  uv run --directory services/telegram-bot python bot.py
  ```

## Smoke 1 — inbound: free-text message → secretary spawn → reply

1. Open Telegram, message the bot: "what time is it where I am?"
2. **Expect bot logs**:
   ```
   Received from <chat_id>: what time is it where I am?
   No active session for chat <chat_id>; spawning 'secretary'
   ```
3. **Expect daemon logs (.daemon.log)**:
   ```
   SessionManager: spawned session sess_... (profile=secretary
     binding=human-channel ticket=None channel=telegram:<chat_id> ...)
   ```
4. **Expect bot logs after a few seconds**:
   ```
   SSE: relaying assistant turn from sess_... to chat <chat_id> (...)
   ```
5. **Expect Telegram**: a reply from the bot with the secretary's answer.

## Smoke 2 — reuse: second message reuses the same session

1. Send another message in the same chat.
2. Bot logs should NOT say "spawning 'secretary'" — the existing active
   session is reused via
   `GET /api/v1/orchestration/sessions?channel_id=telegram:<chat>&status=active`.
3. The daemon log shows `SessionManager: appending to sess_...` with the
   same session id as smoke 1.

## Smoke 3 — `/list` shows the chat's history

1. `/list` in Telegram.
2. Reply contains a row for the active session and any prior closed ones,
   with profile name + status + created_at.

## Smoke 4 — `/new` closes current and opens a fresh session

1. `/new` in Telegram.
2. Reply: "Started a new secretary session: `<id>`".
3. Daemon DB: `SELECT id, status FROM session WHERE channel_id =
   'telegram:<chat>' ORDER BY created_at DESC LIMIT 2;` shows the newest
   active and the previous one as `closed`.

## Smoke 5 — `/profile housekeeper` switches Profile

1. `/profile housekeeper`.
2. Reply: "Switched to *housekeeper* (session `<id>`)".
3. The next free-text message goes to housekeeper, not secretary.

## Smoke 6 — SSE auto-reconnect after daemon restart

1. With the bot running and a chat session active, restart the daemon:
   ```bash
   pkill -f 'agents-mcp.*--daemon'
   nohup uv run --directory services/agents-mcp agents-mcp --daemon \
     --host 127.0.0.1 --port 8765 >> .daemon.log 2>&1 &
   ```
2. Bot logs show `SSE: stream error ...; reconnecting in 1.0s` then
   `SSE: connecting (last_event_id=N)` once daemon is back.
3. Send a message in Telegram — round-trip still works.

## Smoke 7 — morning-brief secretary delivery

This is path (b) in the design. With `HUMAN_TELEGRAM_CHAT_ID` set in the
daemon env, at 7:00 AM local the daemon should:

1. Save the data brief to `briefs/brief-YYYY-MM-DD.md` (legacy step,
   unchanged).
2. **NEW**: spawn a secretary session bound to `telegram:<chat>`.
3. **NEW**: prompt the secretary to compose + send the brief.
4. The bot's SSE listener picks up the assistant turn and relays it to
   Telegram — Human receives the brief there.

To test without waiting until 7am, you can call the helper directly from
a Python REPL inside the daemon process, or temporarily set
`target_hour` to the current hour-1 in `server.py`. For the PR review
we rely on the unit tests in
`services/agents-mcp/tests/test_morning_brief.py` to verify the
branching logic; the live smoke is an operator step at the next morning.

If `HUMAN_TELEGRAM_CHAT_ID` is unset OR the secretary spawn / append
fails, the loop falls back to the legacy admin-notify P2P message path
so the daemon stays useful. Logs distinguish the two paths.

## Troubleshooting

- "**No active session for chat ...; spawning ...**" loops every message:
  the spawn is succeeding but the session isn't being marked active in
  the DB. Check `SELECT * FROM session WHERE channel_id = ...;`.
- **Bot doesn't relay assistant turn**: the SSE connection is the most
  likely culprit. `curl -N http://127.0.0.1:8765/api/v1/orchestration/events`
  should hold open and emit events. If it doesn't, the daemon's event bus
  isn't wired (check `.daemon.log` for `Orchestration SSE:` line at boot).
- **Bot logs `Telegram send failed: 400 ... can't parse markdown`**: the
  bot retries without markdown automatically; benign.
- **`Failed to forward your message to the agent`** to Human: the daemon
  returned non-200 to `POST /sessions/<id>/messages`. Check `.daemon.log`
  for the underlying error (often profile parse error or API-key issue).
