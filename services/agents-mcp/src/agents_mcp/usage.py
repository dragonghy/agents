"""Token usage collection from Claude Code session JSONL files.

Scans ~/.claude/projects/<project-dir>/<session>.jsonl for each agent,
extracts per-message usage data from assistant messages, and aggregates
daily/lifetime stats per model.

Usage data lives in message.usage:
  input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Claude Code stores projects under ~/.claude/projects/
# The project dir name is the absolute working dir with "/" replaced by "-"
CLAUDE_PROJECTS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "projects")


def _agent_project_dir(root_dir: str, agent_id: str) -> Optional[str]:
    """Compute the Claude Code project directory for an agent.

    Agent working dir: <root_dir>/agents/<agent_id>
    Project dir name: path with "/" replaced by "-"
    """
    agent_work_dir = os.path.join(root_dir, "agents", agent_id)
    real_path = os.path.realpath(agent_work_dir)
    project_dir_name = real_path.replace("/", "-")
    project_path = os.path.join(CLAUDE_PROJECTS_DIR, project_dir_name)
    if os.path.isdir(project_path):
        return project_path
    return None


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO timestamp from JSONL messages."""
    if not ts_str:
        return None
    try:
        # Handle various ISO formats
        ts_str = ts_str.rstrip("Z")
        if "+" in ts_str:
            ts_str = ts_str.split("+")[0]
        return datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def scan_session_file(file_path: str, start_offset: int = 0) -> dict:
    """Scan a single session JSONL file for token usage data.

    Args:
        file_path: Path to the .jsonl file
        start_offset: Byte offset to start reading from (for incremental scans)

    Returns:
        {
            "end_offset": int,
            "daily": {
                "YYYY-MM-DD": {
                    "<model>": {
                        "input_tokens": int,
                        "output_tokens": int,
                        "cache_read_tokens": int,
                        "cache_write_tokens": int,
                        "message_count": int,
                    }
                }
            }
        }
    """
    daily = defaultdict(lambda: defaultdict(lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "message_count": 0,
    }))

    try:
        file_size = os.path.getsize(file_path)
        if start_offset >= file_size:
            return {"end_offset": file_size, "daily": {}}

        with open(file_path, "r") as f:
            if start_offset > 0:
                f.seek(start_offset)
                # Skip partial line after seek
                f.readline()

            while True:
                line = f.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") != "assistant":
                    continue

                message = obj.get("message", {})
                if not isinstance(message, dict):
                    continue

                usage = message.get("usage")
                model = message.get("model", "unknown")
                if not usage or not isinstance(usage, dict):
                    continue

                # Skip synthetic/empty messages
                if model.startswith("<") or not model:
                    continue

                # Determine date from message timestamp
                timestamp = _parse_timestamp(obj.get("timestamp", ""))
                if timestamp:
                    date_str = timestamp.strftime("%Y-%m-%d")
                else:
                    # Fallback: use file modification date
                    mtime = os.path.getmtime(file_path)
                    date_str = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")

                entry = daily[date_str][model]
                entry["input_tokens"] += usage.get("input_tokens", 0)
                entry["output_tokens"] += usage.get("output_tokens", 0)
                entry["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)
                entry["cache_write_tokens"] += usage.get("cache_creation_input_tokens", 0)
                entry["message_count"] += 1

            end_offset = f.tell()

    except (OSError, IOError) as e:
        logger.warning(f"Error reading {file_path}: {e}")
        return {"end_offset": start_offset, "daily": {}}

    # Convert defaultdicts to regular dicts
    result_daily = {}
    for date_str, models in daily.items():
        result_daily[date_str] = dict(models)

    return {"end_offset": end_offset, "daily": result_daily}


def collect_agent_usage(root_dir: str, agent_id: str,
                        scan_state: Optional[dict] = None) -> dict:
    """Collect token usage for a single agent across all sessions.

    Args:
        root_dir: Project root directory (e.g. /Users/huayang/code/agents)
        agent_id: Agent name (e.g. 'dev-alex')
        scan_state: Previous scan state for incremental scanning.
                    Format: {"<filename>": <last_byte_offset>, ...}

    Returns:
        {
            "agent_id": str,
            "scan_state": {"<filename>": <offset>, ...},
            "daily": {
                "YYYY-MM-DD": {
                    "<model>": {
                        "input_tokens": int,
                        "output_tokens": int,
                        "cache_read_tokens": int,
                        "cache_write_tokens": int,
                        "message_count": int,
                    }
                }
            }
        }
    """
    project_dir = _agent_project_dir(root_dir, agent_id)
    if not project_dir:
        return {
            "agent_id": agent_id,
            "scan_state": scan_state or {},
            "daily": {},
        }

    scan_state = dict(scan_state or {})
    all_daily = defaultdict(lambda: defaultdict(lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "message_count": 0,
    }))

    # List all JSONL session files
    try:
        jsonl_files = [
            f for f in os.listdir(project_dir)
            if f.endswith(".jsonl")
        ]
    except OSError:
        jsonl_files = []

    new_scan_state = {}
    for filename in jsonl_files:
        file_path = os.path.join(project_dir, filename)
        prev_offset = scan_state.get(filename, 0)

        result = scan_session_file(file_path, start_offset=prev_offset)
        new_scan_state[filename] = result["end_offset"]

        # Merge daily data
        for date_str, models in result["daily"].items():
            for model, usage in models.items():
                entry = all_daily[date_str][model]
                for key in ("input_tokens", "output_tokens",
                            "cache_read_tokens", "cache_write_tokens",
                            "message_count"):
                    entry[key] += usage.get(key, 0)

    # Convert to regular dicts
    result_daily = {}
    for date_str, models in all_daily.items():
        result_daily[date_str] = dict(models)

    return {
        "agent_id": agent_id,
        "scan_state": new_scan_state,
        "daily": result_daily,
    }


def aggregate_usage(daily: dict) -> dict:
    """Aggregate daily usage into summary stats.

    Args:
        daily: Daily usage dict from collect_agent_usage

    Returns:
        {
            "today": {"input_tokens": ..., "output_tokens": ..., ...},
            "lifetime": {"input_tokens": ..., "output_tokens": ..., ...},
            "by_model": {"<model>": {"input_tokens": ..., ...}},
            "daily_totals": [{"date": "YYYY-MM-DD", "input_tokens": ..., ...}],
        }
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lifetime = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "message_count": 0,
    }
    today = dict(lifetime)
    by_model = defaultdict(lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "message_count": 0,
    })
    daily_totals = []

    for date_str in sorted(daily.keys()):
        models = daily[date_str]
        day_total = {
            "date": date_str,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "message_count": 0,
        }

        for model, usage in models.items():
            for key in ("input_tokens", "output_tokens",
                        "cache_read_tokens", "cache_write_tokens",
                        "message_count"):
                val = usage.get(key, 0)
                lifetime[key] += val
                day_total[key] += val
                by_model[model][key] += val

                if date_str == today_str:
                    today[key] += val

        daily_totals.append(day_total)

    return {
        "today": today,
        "lifetime": lifetime,
        "by_model": dict(by_model),
        "daily_totals": daily_totals,
    }
