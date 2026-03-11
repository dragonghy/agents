"""Auto-dispatch: periodically check Leantime and wake idle agents via tmux."""

import asyncio
import logging
import re
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from agents_mcp.leantime_client import LeantimeClient

logger = logging.getLogger(__name__)

# Track last dispatch time per agent (for schedule-based dispatch)
_last_dispatched: dict[str, float] = {}

# Track journal dispatch per agent per day (agent -> "YYYY-MM-DD")
_journal_dispatched: dict[str, str] = {}

# Rate limit: when set, all dispatch is paused until this Unix timestamp
_rate_limit_until: Optional[float] = None


def _tmux_window_exists(tmux_session: str, agent: str) -> bool:
    try:
        out = subprocess.check_output(
            ["tmux", "list-windows", "-t", tmux_session, "-F", "#{window_name}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return agent in out.strip().split("\n")
    except subprocess.CalledProcessError:
        return False


def _is_idle(tmux_session: str, agent: str) -> bool:
    try:
        out = subprocess.check_output(
            ["tmux", "capture-pane", "-t", f"{tmux_session}:{agent}", "-p"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        lines = [l for l in out.split("\n") if l.strip()]
        tail = "\n".join(lines[-10:])

        if any(marker in tail for marker in ["Running…", "Wandering…", "esc to interrupt"]):
            return False
        return any(l.startswith("❯") for l in lines[-10:])
    except subprocess.CalledProcessError:
        return False


def _capture_pane(tmux_session: str, agent: str, lines: int = 30) -> str:
    """Capture tmux pane content. Returns empty string on failure."""
    try:
        return subprocess.check_output(
            ["tmux", "capture-pane", "-t", f"{tmux_session}:{agent}",
             "-p", "-S", f"-{lines}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return ""


def _parse_reset_time(text: str) -> Optional[float]:
    """Parse rate limit reset time from text like 'resets 12am (America/Los_Angeles)'.

    Returns Unix timestamp of the reset time, or None if unparseable.
    """
    match = re.search(
        r'resets?\s+(\d{1,2})\s*(am|pm)\s*\(([^)]+)\)', text, re.IGNORECASE
    )
    if not match:
        # Fallback: if we detect rate limit but can't parse time, pause for 1 hour
        return None

    hour = int(match.group(1))
    ampm = match.group(2).lower()
    tz_name = match.group(3).strip()

    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        logger.warning(f"Unknown timezone '{tz_name}', defaulting to 1h pause")
        return time.time() + 3600

    now = datetime.now(tz)
    reset_dt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if reset_dt <= now:
        reset_dt += timedelta(days=1)

    return reset_dt.timestamp()


def _check_rate_limited(tmux_session: str, agent: str) -> Optional[float]:
    """Check if an agent's terminal shows a rate limit message.

    Returns the reset timestamp if rate limited, None otherwise.
    """
    out = _capture_pane(tmux_session, agent)
    if not out:
        return None

    lower = out.lower()
    if "hit your limit" not in lower and "rate limit" not in lower:
        return None

    reset_ts = _parse_reset_time(out)
    if reset_ts is None:
        # Rate limit detected but couldn't parse reset time; default 1 hour
        reset_ts = time.time() + 3600

    return reset_ts


def is_rate_limited() -> bool:
    """Check if dispatch is currently paused due to rate limit."""
    global _rate_limit_until
    if _rate_limit_until is None:
        return False
    if time.time() >= _rate_limit_until:
        _rate_limit_until = None
        return False
    return True


def get_rate_limit_info() -> Optional[dict]:
    """Get rate limit info if active. Used by API/WebSocket."""
    global _rate_limit_until
    if _rate_limit_until is None or time.time() >= _rate_limit_until:
        return None
    remaining = int(_rate_limit_until - time.time())
    return {
        "until": _rate_limit_until,
        "until_iso": datetime.fromtimestamp(_rate_limit_until).isoformat(),
        "remaining_seconds": remaining,
    }


def _send_tmux_message(tmux_session: str, agent: str, msg: str):
    """Send a message to an agent's tmux pane (literal text + Enter)."""
    subprocess.run(
        ["tmux", "send-keys", "-l", "-t", f"{tmux_session}:{agent}", msg],
        check=True,
    )
    time.sleep(2)
    subprocess.run(
        ["tmux", "send-keys", "-t", f"{tmux_session}:{agent}", "Enter"],
        check=True,
    )


def _dispatch_agent(tmux_session: str, agent: str):
    msg = (
        f"你有待处理的 Leantime 任务。"
        f"请先用 get_inbox(agent_id=\"{agent}\") 检查是否有未读消息并处理，"
        f"然后查询分配给你的任务（tags 包含 agent:{agent}，status=3,4）并执行。"
    )
    _send_tmux_message(tmux_session, agent, msg)


def _dispatch_agent_messages(tmux_session: str, agent: str, unread_count: int):
    msg = (
        f"你有 {unread_count} 条未读消息。"
        f"请使用 get_inbox(agent_id=\"{agent}\") 查看并处理消息，"
        f"处理完毕后检查 Leantime 任务（tags 包含 agent:{agent}，status=3,4）。"
    )
    _send_tmux_message(tmux_session, agent, msg)


def _dispatch_agent_stale(tmux_session: str, agent: str, stale_tickets: list[dict]):
    """Dispatch agent with targeted message about stale in_progress tickets."""
    ticket_list = ", ".join(f"#{t['id']}" for t in stale_tickets)
    msg = (
        f"你有 {len(stale_tickets)} 个长时间处于进行中的 ticket 需要检查：{ticket_list}。"
        f"这些 ticket 可能已完成开发但未执行交付流程。"
        f"请逐一检查：如果工作已完成，执行交付（add_comment + reassign_ticket）；"
        f"如果未完成，继续开发。"
        f"然后检查其他待处理任务（tags 包含 agent:{agent}，status=3,4）。"
    )
    _send_tmux_message(tmux_session, agent, msg)


def _dispatch_agent_schedule(tmux_session: str, agent: str, prompt: str):
    _send_tmux_message(tmux_session, agent, prompt)


def _check_journal_due(agent: str, journal_config: dict, agent_index: int) -> bool:
    """Check if it's time for this agent's daily journal.

    Returns True if:
    - journal_config is set
    - Current time >= configured time + stagger offset for this agent
    - Journal hasn't been dispatched for this agent today
    """
    if not journal_config:
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    if _journal_dispatched.get(agent) == today:
        return False

    time_str = journal_config.get("time", "01:00")
    stagger = journal_config.get("stagger_minutes", 5)
    hour, minute = map(int, time_str.split(":"))

    # Add stagger offset per agent
    target_minute = minute + agent_index * stagger
    target_hour = hour + target_minute // 60
    target_minute = target_minute % 60

    now = datetime.now()
    target = now.replace(hour=target_hour % 24, minute=target_minute, second=0, microsecond=0)

    return now >= target


def _dispatch_agent_journal(tmux_session: str, agent: str):
    """Send daily journal prompt to an agent."""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    msg = (
        f"每日工作日志：请总结你过去 24 小时的工作。"
        f"1. 查询你的 Leantime 活动：list_tickets(assignee=\"{agent}\", status=\"all\", dateFrom=\"{yesterday}\") "
        f"2. 查看收件箱：get_inbox(agent_id=\"{agent}\") "
        f"3. 按 /daily-journal skill 的格式写日志 "
        f"4. 保存到 agents/{agent}/journal/{today}.md "
        f"如果今天没有任何活动，也请记录\"今日无任务\"。"
    )
    _send_tmux_message(tmux_session, agent, msg)


def get_agent_tmux_status(tmux_session: str, agent: str) -> str:
    """Get agent's tmux status: 'idle', 'busy', 'rate_limited', 'no_window', or 'unknown'."""
    if not _tmux_window_exists(tmux_session, agent):
        return "no_window"
    if _is_idle(tmux_session, agent):
        # Check if idle due to rate limit
        out = _capture_pane(tmux_session, agent)
        lower = out.lower()
        if "hit your limit" in lower or "rate limit" in lower:
            return "rate_limited"
        return "idle"
    try:
        out = subprocess.check_output(
            ["tmux", "capture-pane", "-t", f"{tmux_session}:{agent}", "-p"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        lines = [l for l in out.split("\n") if l.strip()]
        tail = "\n".join(lines[-10:])
        if any(marker in tail for marker in ["Running…", "Wandering…", "esc to interrupt"]):
            return "busy"
        return "unknown"
    except subprocess.CalledProcessError:
        return "unknown"


async def dispatch_cycle(client: LeantimeClient, agents: list[str],
                         tmux_session: str, store=None,
                         schedules: Optional[dict] = None,
                         journal_config: Optional[dict] = None,
                         all_agents: Optional[list[str]] = None,
                         staleness_threshold: int = 30) -> dict:
    """Run one dispatch cycle. Returns status dict for each agent.

    Args:
        schedules: {agent_name: {"interval_hours": N, "prompt": "..."}}
        journal_config: {"time": "01:00", "stagger_minutes": 5}
        all_agents: All agent names (including non-dispatchable) for journal dispatch.
        staleness_threshold: Minutes before in_progress tickets are considered stale (0=disabled).
    """
    global _rate_limit_until

    # Check if rate limit is still active
    if _rate_limit_until is not None:
        if time.time() < _rate_limit_until:
            remaining = int(_rate_limit_until - time.time())
            logger.debug(f"Dispatch paused (rate limit, {remaining}s remaining)")
            return {agent: "rate_limited" for agent in agents}
        else:
            logger.info("Rate limit expired, resuming dispatch")
            _rate_limit_until = None
            # Broadcast rate limit cleared via WebSocket (best-effort)
            try:
                from agents_mcp.web.events import event_bus
                if event_bus.client_count > 0:
                    import asyncio
                    asyncio.ensure_future(
                        event_bus.broadcast("rate_limit_cleared", {})
                    )
            except Exception:
                pass

    # Check blocked deps first
    unblocked = await client.check_and_unblock_deps()
    for msg in unblocked:
        logger.info(msg)

    now = time.time()
    results = {}
    for agent in agents:
        # Check for unread messages first
        unread_count = 0
        if store:
            unread_count = await store.get_unread_count(agent)

        has_tasks = await client.has_pending_tasks(agent)

        # Check schedule trigger
        schedule_due = False
        schedule_cfg = (schedules or {}).get(agent)
        if schedule_cfg and not unread_count and not has_tasks:
            interval_sec = schedule_cfg["interval_hours"] * 3600
            last = _last_dispatched.get(agent, 0)
            if now - last >= interval_sec:
                schedule_due = True

        if not unread_count and not has_tasks and not schedule_due:
            results[agent] = "no_work"
            continue

        if not _tmux_window_exists(tmux_session, agent):
            results[agent] = "no_window"
            continue

        if not _is_idle(tmux_session, agent):
            results[agent] = "busy"
            continue

        # Check if this idle agent shows rate limit in terminal
        reset_ts = _check_rate_limited(tmux_session, agent)
        if reset_ts is not None:
            _rate_limit_until = reset_ts
            reset_str = datetime.fromtimestamp(reset_ts).strftime("%Y-%m-%d %H:%M:%S")
            logger.warning(
                f"Rate limit detected on {agent}, pausing dispatch until {reset_str}"
            )
            # Mark all remaining agents as rate_limited
            for a in agents:
                if a not in results:
                    results[a] = "rate_limited"
            # Broadcast rate limit event via WebSocket (best-effort)
            try:
                from agents_mcp.web.events import event_bus
                if event_bus.client_count > 0:
                    import asyncio
                    asyncio.ensure_future(
                        event_bus.broadcast("rate_limit_detected", {
                            "agent": agent,
                            "until": reset_str,
                            "remaining_seconds": int(reset_ts - time.time()),
                        })
                    )
            except Exception:
                pass
            return results

        # Priority: messages > tasks > schedule
        if unread_count:
            _dispatch_agent_messages(tmux_session, agent, unread_count)
            results[agent] = f"dispatched_messages({unread_count})"
            logger.info(f"Dispatched {agent} (messages: {unread_count})")
        elif has_tasks:
            stale = await client.get_stale_in_progress(agent, staleness_threshold) if staleness_threshold > 0 else []
            if stale:
                _dispatch_agent_stale(tmux_session, agent, stale)
                results[agent] = f"dispatched_stale({len(stale)})"
                logger.info(f"Dispatched {agent} (stale tickets: {[t['id'] for t in stale]})")
            else:
                _dispatch_agent(tmux_session, agent)
                results[agent] = "dispatched_tasks"
                logger.info(f"Dispatched {agent} (tasks)")
        elif schedule_due:
            _dispatch_agent_schedule(tmux_session, agent, schedule_cfg["prompt"])
            results[agent] = "dispatched_schedule"
            logger.info(f"Dispatched {agent} (schedule, interval={schedule_cfg['interval_hours']}h)")

        # Update last dispatch time for any dispatch type
        _last_dispatched[agent] = now

    # Journal dispatch pass: check ALL agents (including non-dispatchable like admin)
    journal_agents = all_agents or agents
    for idx, agent in enumerate(journal_agents):
        # Skip if already dispatched in this cycle
        if agent in results and results[agent].startswith("dispatched"):
            continue

        if not _check_journal_due(agent, journal_config, idx):
            continue

        if not _tmux_window_exists(tmux_session, agent):
            if agent not in results:
                results[agent] = "journal_no_window"
            continue

        if not _is_idle(tmux_session, agent):
            if agent not in results:
                results[agent] = "journal_deferred"
            continue

        _dispatch_agent_journal(tmux_session, agent)
        _journal_dispatched[agent] = datetime.now().strftime("%Y-%m-%d")
        results[agent] = "dispatched_journal"
        logger.info(f"Dispatched {agent} (daily journal)")

    return results


async def dispatch_loop(client: LeantimeClient, agents: list[str],
                        tmux_session: str, store=None, interval: int = 30,
                        schedules: Optional[dict] = None,
                        journal_config: Optional[dict] = None,
                        all_agents: Optional[list[str]] = None,
                        staleness_threshold: int = 30):
    """Run dispatch cycles in a loop."""
    sched_info = {a: f"{s['interval_hours']}h" for a, s in (schedules or {}).items()}
    journal_info = f", journal={journal_config['time']}" if journal_config else ""
    stale_info = f", staleness={staleness_threshold}m" if staleness_threshold else ""
    logger.info(f"Auto-dispatch started, interval={interval}s, agents={agents}, schedules={sched_info}{journal_info}{stale_info}")
    while True:
        try:
            results = await dispatch_cycle(client, agents, tmux_session,
                                           store=store, schedules=schedules,
                                           journal_config=journal_config,
                                           all_agents=all_agents,
                                           staleness_threshold=staleness_threshold)
            summary = " ".join(f"{a}:{s}" for a, s in results.items())
            logger.info(f"Dispatch cycle: {summary}")
            # Broadcast events via WebSocket (best-effort)
            try:
                from agents_mcp.web.events import event_bus
                if event_bus.client_count > 0:
                    await event_bus.broadcast("dispatch_completed", results)
                    # Also broadcast agent status update
                    statuses = {
                        a: get_agent_tmux_status(tmux_session, a)
                        for a in agents
                    }
                    await event_bus.broadcast("agent_status_changed", statuses)
            except Exception:
                pass  # WebSocket broadcast is best-effort
        except Exception as e:
            logger.error(f"Dispatch error: {e}")
        await asyncio.sleep(interval)
