#!/usr/bin/env python3
"""Read and summarize an agent's Claude Code conversation log.

Reads the JSONL conversation log for a given agent and outputs a structured
behavior summary: dispatch messages, tool calls, text responses, and
detected anomaly patterns.

Usage:
    python3 tools/read_agent_log.py <agent_name> [--hours 3] [--max-messages 200]
    python3 tools/read_agent_log.py qa-lucy --hours 6
    python3 tools/read_agent_log.py all --hours 1  # scan all agents
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── Config ──

AGENTS_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_FILE = AGENTS_ROOT / ".agent-sessions"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Anomaly patterns to detect
ANOMALY_PATTERNS = [
    {
        "name": "direct_sqlite_access",
        "description": "Agent bypassed MCP and directly queried SQLite database",
        "patterns": [
            r"sqlite3\s+[\w./\-]+\.db",
            r"\.agents-mcp\.db",
            r"\.agents-tasks\.db",
            r"aiosqlite",
            r"import\s+sqlite3",
        ],
        "severity": "high",
    },
    {
        "name": "direct_http_api",
        "description": "Agent bypassed MCP and directly called REST API via curl/HTTP",
        "patterns": [
            r"curl\s+.*localhost:8765",
            r"curl\s+.*127\.0\.0\.1:8765",
            r"requests\.get.*8765",
            r"requests\.post.*8765",
        ],
        "severity": "high",
    },
    {
        "name": "repeated_tool_calls",
        "description": "Agent called the same tool repeatedly (possible dead loop)",
        # Detected programmatically, not via regex
        "patterns": [],
        "severity": "medium",
    },
    {
        "name": "missing_inbox_check",
        "description": "Agent was dispatched but didn't check inbox (get_inbox)",
        "patterns": [],
        "severity": "medium",
    },
    {
        "name": "missing_ticket_check",
        "description": "Agent was dispatched but didn't check tickets (list_tickets)",
        "patterns": [],
        "severity": "low",
    },
    {
        "name": "reserved_port_usage",
        "description": "Agent used reserved port 8765 or 9090",
        "patterns": [
            r"(?:--port|:)8765(?!\d)",
            r"(?:--port|:)9090(?!\d)",
            r"localhost:8765",
            r"localhost:9090",
        ],
        "severity": "medium",
    },
    {
        "name": "mcp_call_stuck",
        "description": "Agent's last message is a tool_use with no response for 10+ minutes (MCP call stuck)",
        # Detected programmatically, not via regex
        "patterns": [],
        "severity": "high",
    },
]


def load_sessions() -> dict[str, str]:
    """Load agent name -> session ID mapping from .agent-sessions."""
    sessions = {}
    if not SESSIONS_FILE.exists():
        return sessions
    with open(SESSIONS_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                name, sid = line.split("=", 1)
                sessions[name.strip()] = sid.strip()
    return sessions


def find_jsonl_path(agent_name: str, session_id: str) -> Path | None:
    """Find the JSONL file for an agent's session."""
    # Try agent-specific project dir first
    for pattern in [
        f"-Users-*-agents-{agent_name}",
        f"-Users-*-agents-agents-{agent_name}",
    ]:
        for d in CLAUDE_PROJECTS_DIR.glob(pattern):
            jsonl = d / f"{session_id}.jsonl"
            if jsonl.exists():
                return jsonl

    # Fallback: search all project dirs
    for d in CLAUDE_PROJECTS_DIR.iterdir():
        if d.is_dir():
            jsonl = d / f"{session_id}.jsonl"
            if jsonl.exists():
                return jsonl
    return None


def parse_jsonl(path: Path, since: datetime, max_messages: int) -> list[dict]:
    """Parse JSONL file and return messages since the given time."""
    messages = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type")
            if msg_type in ("file-history-snapshot", "queue-operation"):
                continue

            ts_str = obj.get("timestamp")
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if ts < since:
                continue

            messages.append({"raw": obj, "timestamp": ts, "type": msg_type})

            if len(messages) >= max_messages:
                break

    return messages


def extract_tool_calls(msg: dict) -> list[dict]:
    """Extract tool_use blocks from an assistant message."""
    tools = []
    content = msg.get("raw", {}).get("message", {}).get("content", [])
    if not isinstance(content, list):
        return tools
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_info = {
                "name": block.get("name", "?"),
                "input_summary": _summarize_input(block.get("input", {})),
            }
            tools.append(tool_info)
    return tools


def _summarize_input(inp: dict) -> str:
    """Create a brief summary of tool input parameters."""
    if not isinstance(inp, dict):
        return str(inp)[:100]
    parts = []
    for k, v in inp.items():
        if isinstance(v, str) and len(v) > 80:
            v = v[:77] + "..."
        parts.append(f"{k}={v}")
    return ", ".join(parts)[:200]


def extract_text(msg: dict) -> str:
    """Extract text content from a message."""
    raw = msg.get("raw", {})
    # User message
    user_msg = raw.get("message", {})
    content = user_msg.get("content", "")
    if isinstance(content, str):
        return content[:500]
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", "")[:300])
                elif block.get("type") == "tool_result":
                    texts.append(f"[tool_result for {block.get('tool_use_id', '?')[:8]}...]")
            elif isinstance(block, str):
                texts.append(block[:300])
        return " | ".join(texts)[:500]
    return str(content)[:200]


def detect_anomalies(messages: list[dict]) -> list[dict]:
    """Detect behavioral anomalies in the message sequence."""
    anomalies = []

    # Collect all text content and tool calls for pattern matching
    all_text = []
    tool_sequence = []
    dispatch_indices = []

    for i, msg in enumerate(messages):
        if msg["type"] == "user":
            text = extract_text(msg)
            all_text.append((i, text))
            # Detect dispatch messages: must be short and match specific daemon dispatch patterns
            if len(text) < 500 and re.search(
                r"你有待处理的|你有新任务|你有 \d+ 条未读消息|定时唤醒[：:]",
                text,
            ):
                dispatch_indices.append(i)

        elif msg["type"] == "assistant":
            tools = extract_tool_calls(msg)
            for t in tools:
                tool_sequence.append((i, t["name"]))
            # Also check text blocks for anomalies
            content = msg.get("raw", {}).get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        all_text.append((i, block.get("text", "")))

    # 1. Regex-based anomaly detection
    for anomaly_def in ANOMALY_PATTERNS:
        if not anomaly_def["patterns"]:
            continue
        for idx, text in all_text:
            for pattern in anomaly_def["patterns"]:
                if re.search(pattern, text, re.IGNORECASE):
                    anomalies.append({
                        "type": anomaly_def["name"],
                        "severity": anomaly_def["severity"],
                        "description": anomaly_def["description"],
                        "message_index": idx,
                        "timestamp": messages[idx]["timestamp"].isoformat(),
                        "evidence": re.search(pattern, text, re.IGNORECASE).group()[:100],
                    })
                    break  # One match per anomaly per message is enough

    # 2. Repeated tool calls detection (same tool called 5+ times in a row)
    if len(tool_sequence) >= 5:
        streak_start = 0
        for j in range(1, len(tool_sequence)):
            if tool_sequence[j][1] != tool_sequence[streak_start][1]:
                streak_len = j - streak_start
                if streak_len >= 5:
                    anomalies.append({
                        "type": "repeated_tool_calls",
                        "severity": "medium",
                        "description": f"Tool '{tool_sequence[streak_start][1]}' called {streak_len} times consecutively",
                        "message_index": tool_sequence[streak_start][0],
                        "timestamp": messages[tool_sequence[streak_start][0]]["timestamp"].isoformat(),
                        "evidence": f"{tool_sequence[streak_start][1]} x{streak_len}",
                    })
                streak_start = j
        # Check final streak
        streak_len = len(tool_sequence) - streak_start
        if streak_len >= 5:
            anomalies.append({
                "type": "repeated_tool_calls",
                "severity": "medium",
                "description": f"Tool '{tool_sequence[streak_start][1]}' called {streak_len} times consecutively",
                "message_index": tool_sequence[streak_start][0],
                "timestamp": messages[tool_sequence[streak_start][0]]["timestamp"].isoformat(),
                "evidence": f"{tool_sequence[streak_start][1]} x{streak_len}",
            })

    # 3. Missing inbox/ticket check after dispatch
    for dispatch_idx in dispatch_indices:
        # Look at the next 10 messages after dispatch for inbox/ticket checks
        window = messages[dispatch_idx + 1 : dispatch_idx + 15]
        found_inbox = False
        found_tickets = False
        for wmsg in window:
            if wmsg["type"] == "assistant":
                tools = extract_tool_calls(wmsg)
                for t in tools:
                    if "get_inbox" in t["name"]:
                        found_inbox = True
                    if "list_tickets" in t["name"]:
                        found_tickets = True

        if not found_inbox:
            anomalies.append({
                "type": "missing_inbox_check",
                "severity": "medium",
                "description": "Agent dispatched but didn't check inbox within next 15 messages",
                "message_index": dispatch_idx,
                "timestamp": messages[dispatch_idx]["timestamp"].isoformat(),
                "evidence": extract_text(messages[dispatch_idx])[:100],
            })
        if not found_tickets:
            anomalies.append({
                "type": "missing_ticket_check",
                "severity": "low",
                "description": "Agent dispatched but didn't check tickets within next 15 messages",
                "message_index": dispatch_idx,
                "timestamp": messages[dispatch_idx]["timestamp"].isoformat(),
                "evidence": extract_text(messages[dispatch_idx])[:100],
            })

    # 4. MCP call stuck detection: last message is tool_use with no response for 10+ min
    STUCK_THRESHOLD_MINUTES = 10
    if messages:
        # Find the last assistant message that contains a tool_use
        last_tool_msg = None
        last_tool_name = None
        last_tool_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["type"] == "assistant":
                tools = extract_tool_calls(messages[i])
                if tools:
                    last_tool_msg = messages[i]
                    last_tool_name = tools[-1]["name"]
                    last_tool_idx = i
                    break

        if last_tool_msg and last_tool_idx is not None:
            # Check if there are any messages after this tool_use
            has_subsequent = any(
                messages[j]["type"] in ("user", "assistant")
                for j in range(last_tool_idx + 1, len(messages))
            )
            if not has_subsequent:
                # No messages after the tool_use — check how long it's been
                tool_ts = last_tool_msg["timestamp"]
                now = datetime.now(timezone.utc)
                stuck_minutes = (now - tool_ts).total_seconds() / 60
                if stuck_minutes >= STUCK_THRESHOLD_MINUTES:
                    anomalies.append({
                        "type": "mcp_call_stuck",
                        "severity": "high",
                        "description": (
                            f"Agent's last action is a '{last_tool_name}' tool call "
                            f"with no response for {int(stuck_minutes)} minutes — likely stuck"
                        ),
                        "message_index": last_tool_idx,
                        "timestamp": tool_ts.isoformat(),
                        "evidence": f"{last_tool_name} stuck {int(stuck_minutes)}m",
                    })

    return anomalies


def format_summary(agent_name: str, messages: list[dict], anomalies: list[dict]) -> str:
    """Format the behavior summary as readable text."""
    lines = []
    lines.append(f"=== Agent Behavior Report: {agent_name} ===")
    lines.append(f"Period: {messages[0]['timestamp'].isoformat()} to {messages[-1]['timestamp'].isoformat()}" if messages else "No messages in period")
    lines.append(f"Total messages: {len(messages)}")
    lines.append("")

    # Anomaly summary
    if anomalies:
        lines.append(f"!! ANOMALIES DETECTED: {len(anomalies)} !!")
        for a in anomalies:
            severity_icon = {"high": "!!!", "medium": "!!", "low": "!"}.get(a["severity"], "?")
            lines.append(f"  [{severity_icon}] {a['type']}: {a['description']}")
            lines.append(f"       at {a['timestamp']} | evidence: {a['evidence']}")
        lines.append("")
    else:
        lines.append("No anomalies detected.")
        lines.append("")

    # Chronological behavior log
    lines.append("--- Behavior Timeline ---")
    for msg in messages:
        ts = msg["timestamp"].strftime("%H:%M:%S")
        if msg["type"] == "user":
            text = extract_text(msg)
            # Skip tool_result messages (noisy)
            if text.startswith("[tool_result") or text.startswith("{'tool_use_id"):
                continue
            lines.append(f"[{ts}] USER: {text[:200]}")
        elif msg["type"] == "assistant":
            tools = extract_tool_calls(msg)
            if tools:
                for t in tools:
                    lines.append(f"[{ts}] TOOL: {t['name']}({t['input_summary'][:150]})")
            else:
                # Text-only assistant response
                content = msg.get("raw", {}).get("message", {}).get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")[:200]
                            if text.strip():
                                lines.append(f"[{ts}] ASST: {text}")
                                break
        elif msg["type"] == "system":
            pass  # Skip system messages in timeline

    return "\n".join(lines)


def format_json_summary(agent_name: str, messages: list[dict], anomalies: list[dict]) -> dict:
    """Format summary as a structured dict (for programmatic use)."""
    tool_calls = []
    dispatch_count = 0

    for msg in messages:
        if msg["type"] == "user":
            text = extract_text(msg)
            if any(kw in text for kw in ["待处理", "未读消息", "定时唤醒"]):
                dispatch_count += 1
        elif msg["type"] == "assistant":
            for t in extract_tool_calls(msg):
                tool_calls.append(t["name"])

    # Tool call frequency
    tool_freq = {}
    for t in tool_calls:
        tool_freq[t] = tool_freq.get(t, 0) + 1

    return {
        "agent": agent_name,
        "period_start": messages[0]["timestamp"].isoformat() if messages else None,
        "period_end": messages[-1]["timestamp"].isoformat() if messages else None,
        "total_messages": len(messages),
        "dispatch_count": dispatch_count,
        "tool_call_count": len(tool_calls),
        "tool_frequency": dict(sorted(tool_freq.items(), key=lambda x: -x[1])),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }


def analyze_agent(agent_name: str, session_id: str, hours: float, max_messages: int, output_json: bool = False) -> str | dict:
    """Full analysis pipeline for one agent."""
    jsonl_path = find_jsonl_path(agent_name, session_id)
    if not jsonl_path:
        msg = f"JSONL file not found for {agent_name} (session: {session_id})"
        return {"error": msg} if output_json else msg

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    messages = parse_jsonl(jsonl_path, since, max_messages)

    if not messages:
        msg = f"No messages found for {agent_name} in the last {hours}h"
        return {"agent": agent_name, "error": msg} if output_json else msg

    anomalies = detect_anomalies(messages)

    if output_json:
        return format_json_summary(agent_name, messages, anomalies)
    else:
        return format_summary(agent_name, messages, anomalies)


def main():
    parser = argparse.ArgumentParser(description="Read and analyze agent conversation logs")
    parser.add_argument("agent", help="Agent name (e.g. 'qa-lucy') or 'all' for all agents")
    parser.add_argument("--hours", type=float, default=3, help="Look back N hours (default: 3)")
    parser.add_argument("--max-messages", type=int, default=200, help="Max messages to process per agent (default: 200)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of text")
    args = parser.parse_args()

    sessions = load_sessions()
    if not sessions:
        print(f"Error: {SESSIONS_FILE} not found or empty", file=sys.stderr)
        sys.exit(1)

    if args.agent == "all":
        targets = list(sessions.items())
    else:
        sid = sessions.get(args.agent)
        if not sid:
            print(f"Error: Agent '{args.agent}' not found in {SESSIONS_FILE}", file=sys.stderr)
            print(f"Available agents: {', '.join(sorted(sessions.keys()))}", file=sys.stderr)
            sys.exit(1)
        targets = [(args.agent, sid)]

    results = []
    for agent_name, session_id in targets:
        result = analyze_agent(agent_name, session_id, args.hours, args.max_messages, args.json)
        results.append(result)

    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2, ensure_ascii=False))
    else:
        print("\n\n".join(results) if isinstance(results[0], str) else "\n\n".join(str(r) for r in results))


if __name__ == "__main__":
    main()
