---
name: agent-identity
description: Agent real-world identity — email, phone, payment, and personal info for autonomous service registration.
---

# Agent Identity

Agents have real-world identity to register for services, receive verification codes, and make purchases without Human intervention.

## 1. Email

**Address**: huayang.guo@outlook.com
**Access**: Microsoft Outlook MCP (`mcp__microsoft__*` tools)
**Account ID**: Use `mcp__microsoft__list_accounts` to get the current account ID

Use cases:
- Register for new services
- Receive email verification codes
- Send work-related emails

## 2. Phone Number (SMS)

**Number**: +16502853480
**Provider**: Twilio (receive-only)
**Access**: Twilio REST API

To read incoming SMS (e.g., verification codes):
```bash
curl -s "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/Messages.json?To=%2B16502853480&PageSize=5" \
  -u "${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}"
```

Credentials are in `.env` as `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`, and in 1Password under "Twilio - Agent Phone Number".

**Limitation**: This number can receive SMS only, not send. Some platforms block VoIP numbers for verification — in those cases, create an `agent:human` ticket asking Human to verify manually.

## 3. Payment

**Provider**: Privacy.com virtual card
**1Password entry**: "Privacy.com - Unused Card 1 ($20/mo limit)"
**Monthly limit**: $20

To retrieve card details:
```
mcp__1password__item_lookup(vaultId="kc6iyzxme5inasbmdt2hlm3x5q", query="Privacy.com")
```

Rules:
- First use locks the card to that merchant permanently
- Any purchase must be within the $20/mo limit
- For purchases exceeding the limit, create an `agent:human` ticket for approval
- Card details: number in `username` field, expiry and CVV in `password` field

## 4. Personal Information

Use when registering for services that require personal details (name, address, etc.).

- **Full Name**: Huayang Guo
- **Email**: huayang.guo@outlook.com
- **Phone**: +19176574918 (Human's personal number, use only when Twilio number is rejected)
- **Mailing Address**: 970 Corte Madera Ave APT 302, Sunnyvale, CA 94085
- **Date of Birth**: 09/03/1989

Also stored in 1Password under "Human Identity - Personal Info".

## 5. Self-Service Registration Flow

When you need to sign up for a new service:

1. **Register** with email (huayang.guo@outlook.com)
2. **Email verification**: Check inbox via `mcp__microsoft__search_emails` for the verification code/link
3. **Phone verification**: If SMS code required, poll Twilio API for incoming messages to +16502853480
4. **Payment**: If payment needed and within $20/mo, use the Privacy.com card from 1Password
5. **Personal info**: Use the details in section 4 above

If any step fails (VoIP number rejected, card declined, etc.), create an `agent:human` ticket with what you need and move on to other work.

## 6. Communication with Human

**Primary channel**: Telegram bot (@agents_daemon_bot)
- Human messages are forwarded to daemon and stored in `human_messages` table
- Use `send_human_message()` MCP tool to send messages to Human
- Human receives push notifications on their phone

**Secondary channel**: Email (for Morning Briefs and formal reports)

**MCP tools**:
- `get_human_conversation()` — read conversation history
- `send_human_message()` — send message to Human
- `get_pending_human_decisions()` — check unanswered decisions
