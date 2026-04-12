"""Telegram Bot Service: transport bridge between Human and Agent Harness.

This is a thin, always-running process with NO AI logic. It is purely a
message transport bridge that:
1. Receives messages from Human via Telegram Bot API
2. Forwards them to the daemon via REST API
3. Polls daemon for outbound messages
4. Sends them to Human via Telegram

Setup:
1. Create a bot via @BotFather on Telegram
2. Save the token to 1Password or .env as TELEGRAM_BOT_TOKEN
3. Get your Telegram user ID (send /start to @userinfobot)
4. Save as TELEGRAM_HUMAN_CHAT_ID in .env
5. Run: python bot.py
"""

import asyncio
import logging
import os
import sys

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
HUMAN_CHAT_ID = os.environ.get("TELEGRAM_HUMAN_CHAT_ID", "")
DAEMON_URL = os.environ.get("DAEMON_URL", "http://127.0.0.1:8765")
POLL_INTERVAL = 5  # seconds between outbox polls
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def send_telegram(chat_id: str, text: str, session: aiohttp.ClientSession):
    """Send a message to a Telegram chat."""
    # Telegram has 4096 char limit; split if needed
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        async with session.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error(f"Telegram send failed: {resp.status} {body}")
                # Retry without markdown if parsing failed
                if "can't parse" in body.lower():
                    async with session.post(
                        f"{TELEGRAM_API}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk},
                    ) as resp2:
                        if resp2.status != 200:
                            logger.error(f"Telegram send retry failed: {await resp2.text()}")


async def forward_to_daemon(text: str, session: aiohttp.ClientSession):
    """Forward a Human message to the daemon."""
    try:
        async with session.post(
            f"{DAEMON_URL}/api/v1/human/messages",
            json={"body": text, "channel": "telegram"},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                logger.info(f"Forwarded to daemon: msg_id={data.get('message_id')}")
            else:
                logger.error(f"Daemon forward failed: {resp.status} {await resp.text()}")
    except Exception as e:
        logger.error(f"Daemon connection failed: {e}")


async def poll_outbox(session: aiohttp.ClientSession):
    """Poll daemon for outbound messages and deliver via Telegram."""
    try:
        async with session.get(f"{DAEMON_URL}/api/v1/human/outbox") as resp:
            if resp.status == 200:
                data = await resp.json()
                messages = data.get("messages", [])
                for msg in messages:
                    body = msg.get("body", "")
                    context = msg.get("context_type", "")
                    if context:
                        body = f"[{context}]\n\n{body}"
                    await send_telegram(HUMAN_CHAT_ID, body, session)
                    logger.info(f"Delivered to Telegram: msg_id={msg.get('id')}")
    except aiohttp.ClientError as e:
        logger.debug(f"Outbox poll failed: {e}")


async def handle_updates(session: aiohttp.ClientSession):
    """Long-poll Telegram for new messages from Human."""
    offset = 0
    while True:
        try:
            async with session.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=aiohttp.ClientTimeout(total=35),
            ) as resp:
                if resp.status != 200:
                    logger.error(f"getUpdates failed: {resp.status}")
                    await asyncio.sleep(5)
                    continue

                data = await resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    text = message.get("text", "")
                    chat_id = str(message.get("chat", {}).get("id", ""))

                    # Only accept messages from Human
                    if chat_id != HUMAN_CHAT_ID:
                        logger.warning(f"Ignoring message from unknown chat: {chat_id}")
                        continue

                    if not text:
                        continue

                    logger.info(f"Received from Human: {text[:50]}...")
                    await forward_to_daemon(text, session)

        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.error(f"Update handler error: {e}")
            await asyncio.sleep(5)


async def outbox_loop(session: aiohttp.ClientSession):
    """Background loop to poll daemon outbox and deliver to Telegram."""
    while True:
        await poll_outbox(session)
        await asyncio.sleep(POLL_INTERVAL)


async def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set. Get one from @BotFather.")
        sys.exit(1)
    if not HUMAN_CHAT_ID:
        logger.error("TELEGRAM_HUMAN_CHAT_ID not set. Get yours from @userinfobot.")
        sys.exit(1)

    logger.info(f"Telegram Bot starting, daemon={DAEMON_URL}")

    async with aiohttp.ClientSession() as session:
        # Verify bot token
        async with session.get(f"{TELEGRAM_API}/getMe") as resp:
            if resp.status == 200:
                me = await resp.json()
                bot_name = me.get("result", {}).get("username", "unknown")
                logger.info(f"Bot authenticated: @{bot_name}")
            else:
                logger.error(f"Bot authentication failed: {await resp.text()}")
                sys.exit(1)

        # Run update handler and outbox poller concurrently
        await asyncio.gather(
            handle_updates(session),
            outbox_loop(session),
        )


if __name__ == "__main__":
    asyncio.run(main())
