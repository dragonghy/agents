# wechat-mcp

MCP server that exposes WeChat for Mac to a personal AI agent through pure
osascript / AppleScript UI automation. No protocol re-implementation, no
database scraping — the agent drives the same client a human uses, so to
WeChat's anti-spam systems it looks like a human typing.

> **Personal-agent only.** This server is intentionally **not** mounted on
> any work agent (admin, ops, dev-alex, qa-lucy, …). It's wired up via
> `agents.assistant-aria.extra_mcp_servers` in `agents.yaml` — see
> "Wiring" below.

## Why pure AppleScript

Per Human's 4/26 decision (see `projects/agent-hub/wechat-mcp-research.md`,
ticket #496), the safer of the original two finalists. A DB-read approach
needs the WeChat client running and synced anyway, so it has the same
"client must be open" requirement *and* additional brittleness from
SQLCipher key extraction + per-WeChat-major-version schema changes. Pure
AppleScript is slower (~2–3s per send) but accepts only one fragility
surface — UI selectors — instead of two.

The decisive constraint: Human's main account is a 10-year-old WeChat
account; "封号" (account ban) is unacceptable. AppleScript driving the
official client produces network traffic identical to a human, which is
the lowest-risk approach short of "don't use WeChat".

## Tools

| Tool | What it does |
| --- | --- |
| `wechat_list_chats(limit=20)` | Names + best-effort previews from the sidebar |
| `wechat_get_chat(chat_name, limit=50)` | Currently-rendered messages of a chat |
| `wechat_search(query, chat_names=None, limit=20)` | Substring search over fresh reads of given chats (defaults to top-5 recent) |
| `wechat_send(chat_name, body)` | Plain-text message via UI (rate-limited) |

`chat_name` is the contact / group name as it appears in the WeChat
sidebar. The conversation switcher is opened via Cmd+F and the top match
is selected — disambiguation across same-named chats happens at the agent
layer, not here.

## Permissions

Two macOS permissions are required, both granted to the **terminal
application** that hosts this MCP (Terminal.app, iTerm2.app, or Claude
Desktop), not to Claude Code itself:

1. **Accessibility** (System Settings → Privacy & Security → Accessibility)
   — required for `System Events` UI scripting.
2. **Automation** (System Settings → Privacy & Security → Automation) —
   the host terminal must be allowed to control "WeChat" and "System
   Events". macOS prompts the first time; if you dismiss the prompt you
   may need to re-enable manually.

After granting, **quit and relaunch** the terminal app. TCC permissions
are checked at process spawn, so an already-running terminal won't see
the grant until restarted.

### Self-check

```bash
uv run --directory services/wechat-mcp python -m wechat_mcp --check
```

Output on a working environment:

```
OK: WeChat.app found at /Applications/WeChat.app
OK: osascript at /usr/bin/osascript
OK: WeChat process is running
OK: Accessibility working — front window: WeChat
All checks passed. Bundle: com.tencent.xinWeChat
```

The script prints a precise remediation step at the first failing check.

## Wiring

```yaml
# agents.yaml — under agents.<personal-agent>.extra_mcp_servers
agents:
  assistant-aria:
    extra_mcp_servers:
      wechat_personal:
        command: uv
        args:
          - "--directory"
          - "{ROOT_DIR}/services/wechat-mcp"
          - run
          - wechat-mcp
```

**Critical**: do NOT add `wechat_personal` to the top-level `mcp_servers:`
block — that auto-loads to all v1 agents (admin / ops / dev-alex / qa-lucy)
per `claude.md` pitfall #13. Per-agent isolation lives in
`extra_mcp_servers` only. Work agents that try to call
`mcp__wechat_personal__*` will get a "tool not found" error, which is
exactly what we want.

## Send semantics & rate limiting

The send flow is:

1. `tell application "WeChat" to activate` (brings window to front).
2. `Cmd+F` opens the conversation switcher.
3. Type the chat name → Return → chat opens.
4. `Tab` to focus the input → `Cmd+A` + Delete to clear any draft → type
   the body → Return to send.

Built-in throttle:

- Per-chat: ≥3 seconds between consecutive sends to the same name.
- Global: ≤20 sends per rolling 60-second window.

Failed sends do **not** consume the budget — only successful osascript
runs are recorded. This makes retries after a transient UI hiccup work
sensibly.

These limits are best-effort and reset when the MCP process restarts.
That's intentionally conservative; if WeChat ever surfaces stricter rate
hints we'll lower the ceilings.

## Known caveats

- **WeChat must be in the foreground or at least not hidden.** osascript
  `activate` brings it forward, but if the user has it minimized to the
  dock it may take an extra ~500ms for the window to render. The send
  script's hard-coded delays cover this in practice.
- **Same-name collision.** If two contacts share a display name, the
  WeChat search palette returns its own most-active match. The MCP doesn't
  paper over this — agents needing strict targeting should `wechat_get_chat`
  the candidate first to confirm identity.
- **Reading is render-buffer only.** `wechat_get_chat` reads what's
  currently visible in WeChat's scrollback (typically 30–80 messages).
  We don't auto-scroll-up to load older history because doing so reliably
  across WeChat versions adds complexity v1 doesn't need.
- **No outgoing/incoming flag.** WeChat for Mac draws message direction
  as positional layout, not as a labelled attribute, so we can't reliably
  set `is_outgoing` from the AX tree. Compare `sender` against the user's
  own display name at the agent layer.
- **WeChat upgrades may break selectors.** Roughly every 1–2 months. All
  selectors live in `reader.py` and `sender.py`; expect to patch one of
  those files when WeChat ships a UI change. Tested against WeChat 3.8.10.

## Limitations / out of scope

- File / image / video sending (text only)
- Voice notes
- Moments (朋友圈), Channels (视频号), Mini Programs, Pay
- Group administration (kick / invite / rename)
- Message recall / edit
- Reading unread badges (WeChat draws them as overlays without stable AX values)

## Development

```bash
cd services/wechat-mcp
uv sync
uv run pytest
```

Tests are pure-function unit tests (escape correctness, AppleScript
template generation, parser heuristics, rate limiter windowing). Live
UI integration is a manual step — see `--check` and the verification
protocol in ticket #502.
