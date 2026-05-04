"""Resolve a Profile's logical ``mcp_servers`` (e.g. ``"google_personal"``)
into concrete Claude SDK MCP server configs + the ``allowed_tools`` list.

Source of truth for the configs is ``agents.yaml`` —
``agents.assistant-aria.extra_mcp_servers`` keyed by logical name. This
matches the per-agent isolation pattern documented in claude.md
pitfall #13. The resolver doesn't care about which v1 agent the configs
live under; it just needs the per-MCP ``command`` / ``args`` / ``env``
shape to forward to ``claude_agent_sdk.ClaudeAgentOptions.mcp_servers``.

Tool name allow-list is hard-coded per MCP, mirroring what the
``personal-mcp-toolkit`` skill documents. Hard-coding is the only
practical option: at session-spawn time we don't have a live MCP
connection to introspect, and the SDK's ``permission_mode="bypassPermissions"``
doesn't always fully bypass — explicit ``allowed_tools`` is what makes
tool calls actually fire in headless daemon mode.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)


# Tool names per logical MCP. Source: projects/agent-hub/skills/personal-mcp-toolkit/SKILL.md.
# Keep in sync with services/<mcp>/ tool registrations.
_TOOLS_BY_SERVER: dict[str, tuple[str, ...]] = {
    "google_personal": (
        "search_gmail_messages",
        "get_gmail_message_content",
        "send_gmail_message",
        "manage_gmail_label",
        "list_calendars",
        "get_events",
        "manage_event",
        "search_drive_files",
        "get_drive_file_content",
    ),
    "imessage_personal": (
        "imessage_list_chats",
        "imessage_get_chat",
        "imessage_search",
        "imessage_unread",
        "imessage_send",
    ),
    "wechat_personal": (
        "wechat_list_chats",
        "wechat_get_chat",
        "wechat_search",
        "wechat_send",
    ),
}


def _coerce_to_sdk_config(name: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    """Translate an agents.yaml MCP config into the SDK shape.

    Expected agents.yaml shape (as used under ``extra_mcp_servers``):
        {command: str, args: [str, ...], env?: {str: str}}

    SDK shape (``McpSdkServerConfig``):
        {type: "stdio", command: str, args: [str, ...], env: {str: str}}

    ``{ROOT_DIR}`` placeholder substitution is handled by the daemon's
    yaml loader before we see it; if it's still here, that's a bug —
    we log and skip.
    """
    if not isinstance(raw, dict):
        logger.warning(
            "personal_mcp_registry: %s config is not a dict (%r); skipping",
            name,
            type(raw),
        )
        return None
    cmd = raw.get("command")
    args = raw.get("args") or []
    if not cmd or not isinstance(cmd, str):
        logger.warning(
            "personal_mcp_registry: %s missing/invalid 'command'; skipping",
            name,
        )
        return None
    if not isinstance(args, list):
        logger.warning(
            "personal_mcp_registry: %s 'args' is not a list; skipping",
            name,
        )
        return None
    env = raw.get("env") or {}
    if not isinstance(env, dict):
        env = {}
    if any("{ROOT_DIR}" in str(a) for a in args):
        logger.warning(
            "personal_mcp_registry: %s args contain unsubstituted "
            "{ROOT_DIR} placeholder; ensure agents.yaml was loaded with "
            "_resolve_root_dir applied",
            name,
        )
        return None
    return {
        "type": "stdio",
        "command": cmd,
        "args": [str(a) for a in args],
        "env": {str(k): str(v) for k, v in env.items()},
    }


def build_resolver(get_config):
    """Build a resolver callable bound to the daemon's ``get_config``.

    Returned callable signature::

        resolve(logical_names: Iterable[str]) -> tuple[dict, list[str]]

    where the first element is the dict to pass to
    ``ClaudeAgentOptions.mcp_servers`` (keyed by logical name) and the
    second is the ``allowed_tools`` list (entries like
    ``mcp__google_personal__send_gmail_message``).

    Logical names that aren't found in agents.yaml are silently skipped
    after a single warning log — a Profile shouldn't fail to spawn
    just because one of its declared MCPs isn't provisioned yet.
    """

    def resolve(
        logical_names: Iterable[str],
    ) -> tuple[dict[str, Any], list[str]]:
        cfg = get_config() or {}
        agents = cfg.get("agents") or {}
        # Personal MCP configs canonically live under
        # agents.assistant-aria.extra_mcp_servers per pitfall #13.
        # Future: support a top-level ``personal_mcp_servers:`` for
        # cross-agent reuse without coupling to one v1 agent name.
        registry: dict[str, Any] = {}
        host = agents.get("assistant-aria") or {}
        for name, raw_cfg in (host.get("extra_mcp_servers") or {}).items():
            registry[name] = raw_cfg

        servers: dict[str, Any] = {}
        allowed: list[str] = []
        missing: list[str] = []
        for name in logical_names:
            raw = registry.get(name)
            if raw is None:
                missing.append(name)
                continue
            sdk_cfg = _coerce_to_sdk_config(name, raw)
            if sdk_cfg is None:
                continue
            servers[name] = sdk_cfg
            for tool in _TOOLS_BY_SERVER.get(name, ()):
                allowed.append(f"mcp__{name}__{tool}")
        if missing:
            logger.warning(
                "personal_mcp_registry: profile requested MCP(s) %r but "
                "no config under agents.assistant-aria.extra_mcp_servers "
                "in agents.yaml — skipping",
                missing,
            )
        return servers, allowed

    return resolve


__all__ = ["build_resolver"]
