"""Unit tests for personal_mcp_registry.build_resolver.

Covers the contract used by SessionManager when a Profile declares
``mcp_servers: [google_personal, imessage_personal, wechat_personal]``.
"""

from __future__ import annotations

from agents_mcp.personal_mcp_registry import build_resolver


def _fake_config(extra_mcp_servers: dict) -> dict:
    return {
        "agents": {
            "assistant-aria": {
                "extra_mcp_servers": extra_mcp_servers,
            }
        }
    }


class TestBuildResolver:
    def test_resolves_google_personal(self):
        cfg = _fake_config(
            {
                "google_personal": {
                    "command": "uvx",
                    "args": ["workspace-mcp", "--single-user"],
                    "env": {"GOOGLE_OAUTH_CLIENT_ID": "abc"},
                },
            }
        )
        resolver = build_resolver(lambda: cfg)
        servers, allowed = resolver(["google_personal"])

        assert "google_personal" in servers
        s = servers["google_personal"]
        assert s["type"] == "stdio"
        assert s["command"] == "uvx"
        assert s["args"] == ["workspace-mcp", "--single-user"]
        assert s["env"] == {"GOOGLE_OAUTH_CLIENT_ID": "abc"}

        # Tool allowlist mirrors the SKILL.md — at minimum the high-frequency
        # ones must be present.
        assert "mcp__google_personal__send_gmail_message" in allowed
        assert "mcp__google_personal__get_events" in allowed
        assert "mcp__google_personal__search_drive_files" in allowed

    def test_resolves_multiple_personal_mcps(self):
        cfg = _fake_config(
            {
                "imessage_personal": {
                    "command": "uv",
                    "args": ["--directory", "/tmp/imessage", "run", "imessage-mcp"],
                },
                "wechat_personal": {
                    "command": "uv",
                    "args": ["--directory", "/tmp/wechat", "run", "wechat-mcp"],
                },
            }
        )
        resolver = build_resolver(lambda: cfg)
        servers, allowed = resolver(("imessage_personal", "wechat_personal"))

        assert set(servers.keys()) == {"imessage_personal", "wechat_personal"}
        assert "mcp__imessage_personal__imessage_send" in allowed
        assert "mcp__wechat_personal__wechat_send" in allowed
        # No tools from a server that wasn't requested
        assert not any(t.startswith("mcp__google_personal__") for t in allowed)

    def test_skips_unknown_server_silently(self):
        cfg = _fake_config({})
        resolver = build_resolver(lambda: cfg)
        servers, allowed = resolver(["nonexistent_personal"])
        assert servers == {}
        assert allowed == []

    def test_skips_malformed_config(self):
        cfg = _fake_config(
            {
                "broken": {
                    # Missing 'command'
                    "args": ["foo"],
                },
            }
        )
        resolver = build_resolver(lambda: cfg)
        servers, allowed = resolver(["broken"])
        assert servers == {}
        assert allowed == []

    def test_skips_unsubstituted_root_dir_placeholder(self):
        """Belt-and-suspenders: if agents.yaml hasn't been
        ``_resolve_root_dir``-processed yet (a daemon-startup ordering
        bug), we'd ship a literal ``{ROOT_DIR}`` to the SDK and it'd
        fail to spawn. Guard against that by skipping the entry.
        """
        cfg = _fake_config(
            {
                "imessage_personal": {
                    "command": "uv",
                    "args": ["--directory", "{ROOT_DIR}/services/imessage-mcp", "run"],
                },
            }
        )
        resolver = build_resolver(lambda: cfg)
        servers, allowed = resolver(["imessage_personal"])
        # Skipped — entry never makes it through.
        assert servers == {}
        assert allowed == []

    def test_handles_missing_assistant_aria_section(self):
        """If agents.yaml has no assistant-aria entry, resolve to empty —
        no crash.
        """
        resolver = build_resolver(lambda: {"agents": {}})
        servers, allowed = resolver(["google_personal"])
        assert servers == {}
        assert allowed == []

    def test_resolves_global_mcp_from_top_level(self):
        """Profiles can request global MCPs (e.g. ``agents``,
        ``microsoft``) declared under the top-level ``mcp_servers:`` key
        — not just personal MCPs under
        ``agents.assistant-aria.extra_mcp_servers``.
        """
        cfg = {
            "mcp_servers": {
                "agents": {
                    "command": "uv",
                    "args": ["run", "agents-mcp-proxy"],
                    "env": {"AGENTS_DAEMON_URL": "http://127.0.0.1:8765/sse"},
                },
            },
            "agents": {"assistant-aria": {"extra_mcp_servers": {}}},
        }
        resolver = build_resolver(lambda: cfg)
        servers, allowed = resolver(["agents"])
        assert "agents" in servers
        assert servers["agents"]["command"] == "uv"
        # Tool allowlist for the orchestration MCP
        assert "mcp__agents__list_tickets" in allowed
        assert "mcp__agents__add_comment" in allowed
        assert "mcp__agents__spawn_session" in allowed

    def test_personal_shadows_global_on_name_collision(self):
        """If the same logical name appears in both blocks, the personal
        (assistant-aria) entry wins — that's the right thing if a
        personal MCP later gets promoted to global scope and the user
        forgets to delete the old global entry.
        """
        cfg = {
            "mcp_servers": {
                "google_personal": {
                    "command": "old_global",
                    "args": [],
                },
            },
            "agents": {
                "assistant-aria": {
                    "extra_mcp_servers": {
                        "google_personal": {
                            "command": "new_personal",
                            "args": [],
                        },
                    },
                }
            },
        }
        resolver = build_resolver(lambda: cfg)
        servers, _ = resolver(["google_personal"])
        assert servers["google_personal"]["command"] == "new_personal"
