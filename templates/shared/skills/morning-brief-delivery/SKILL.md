---
name: morning-brief-delivery
description: How to deliver the daily Morning Brief email to Human.
---

# Morning Brief Email Delivery

## When This Triggers

You receive a message from `system` saying "Morning Brief for <date> is ready."

## What To Do

1. Read the brief file from the path specified in the message (e.g., `briefs/brief-2026-04-12.md`)
2. Send it via email using Microsoft MCP:

```
mcp__microsoft__send_email(
  account_id="<from list_accounts>",
  to="huayang.guo@gmail.com",
  subject="🤖 Morning Brief — <date>",
  body=<contents of the brief file>
)
```

3. Mark the system message as read.

## If Email Fails

- Check if Microsoft MCP is authenticated (`mcp__microsoft__list_accounts`)
- If not authenticated, run `mcp__microsoft__authenticate_account` first
- If auth fails, save the brief to a ticket comment on a new `agent:human` ticket so Human can read it manually
