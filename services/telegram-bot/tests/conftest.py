"""Pytest config — allow tests to import the top-level ``bot`` module."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Set required env vars BEFORE the bot module loads, otherwise the
# module-level ``BOT_TOKEN`` / ``HUMAN_CHAT_ID`` / ``DAEMON_URL`` will pick
# up empty strings and tests that introspect URL constants will look weird.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_HUMAN_CHAT_ID", "55555")
os.environ.setdefault("DAEMON_URL", "http://daemon.test")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
