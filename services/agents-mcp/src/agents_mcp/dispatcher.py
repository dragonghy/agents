"""Auto-dispatch: periodically check task DB and wake idle agents via tmux."""

import asyncio
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from agents_mcp.sqlite_task_client import SQLiteTaskClient

logger = logging.getLogger(__name__)

# Per-agent rate limit tracking: agent -> {"reset_ts": float, "first_detected": float}
_agent_rate_limits: dict[str, dict] = {}

# Auto-restart cooldown: agent -> last restart attempt timestamp
_auto_restart_cooldown: dict[str, float] = {}
AUTO_RESTART_COOLDOWN = 300  # 5 minutes between restart attempts

# Stale dispatch cooldown: agent -> last stale dispatch timestamp
# Prevents spamming agents with the same stale ticket message every 30s.
_stale_dispatch_cooldown: dict[str, float] = {}
STALE_DISPATCH_COOLDOWN = 3600  # 1 hour between stale reminders for the same agent

# Deferred dispatch: track active deferred tasks to avoid duplicates
# agent -> asyncio.Task
_deferred_dispatch_tasks: dict[str, asyncio.Task] = {}

# Deferred dispatch configuration
DEFERRED_DISPATCH_INTERVAL = 10  # seconds between retries
DEFERRED_DISPATCH_MAX_WAIT = 120  # max seconds to keep retrying

_SUBPROCESS_TIMEOUT = 10  # seconds; prevent tmux hangs from blocking the event loop


def _tmux_window_exists(tmux_session: str, agent: str) -> bool:
    try:
        out = subprocess.check_output(
            ["tmux", "list-windows", "-t", tmux_session, "-F", "#{window_name}"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        return agent in out.strip().split("\n")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _is_idle(tmux_session: str, agent: str) -> bool:
    """Check if an agent is idle (waiting for input at the ❯ prompt).

    Claude Code v2.1+ shows the ❯ prompt at the bottom even while working
    (users can type ahead). The reliable busy/idle signal is the status bar:
      - "esc to interrupt" appears ONLY when Claude is actively processing.
      - When idle, the status bar shows other info but NOT "esc to interrupt".

    Idle = ❯ prompt present AND "esc to interrupt" NOT in status bar.
    """
    try:
        out = subprocess.check_output(
            ["tmux", "capture-pane", "-t", f"{tmux_session}:{agent}", "-p"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        lines = [l for l in out.split("\n") if l.strip()]
        tail_lines = lines[-10:]

        # The ❯ prompt must be present (Claude Code is running).
        has_prompt = any(l.startswith("❯") for l in tail_lines)
        if not has_prompt:
            return False

        # "esc to interrupt" in the status bar = Claude is actively working.
        # Old spinners (✶ Crunched, etc.) may linger on screen after completion,
        # so we ONLY use the status bar as the busy signal.
        tail_text = "\n".join(tail_lines)
        if "esc to interrupt" in tail_text:
            return False

        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _capture_pane(tmux_session: str, agent: str, lines: int = 0) -> str:
    """Capture tmux pane content. Returns empty string on failure.

    Args:
        lines: If > 0, return only the last N non-empty lines.
               If 0 (default), return full visible pane content.
    """
    try:
        out = subprocess.check_output(
            ["tmux", "capture-pane", "-t", f"{tmux_session}:{agent}", "-p"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if lines > 0:
            non_empty = [l for l in out.split("\n") if l.strip()]
            return "\n".join(non_empty[-lines:])
        return out
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
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
        # Reset time is in the past — this is stale rate limit text, ignore it
        return None

    return reset_dt.timestamp()


def _check_rate_limited(tmux_session: str, agent: str) -> Optional[float]:
    """Check if an agent's terminal shows a rate limit message.

    Only checks the last 5 lines to avoid false positives from stale
    rate limit text still visible in terminal scrollback.

    Returns the reset timestamp if rate limited, None otherwise.
    Returns None for stale rate limit text (reset time in the past).
    """
    out = _capture_pane(tmux_session, agent, lines=5)
    if not out:
        return None

    lower = out.lower()
    if "hit your limit" not in lower and "rate limit" not in lower:
        return None

    reset_ts = _parse_reset_time(out)
    # Only rate-limit if we can parse a FUTURE reset time.
    # If reset time is in the past or unparseable, this is likely stale text
    # left over from a previous rate limit — ignore it.
    return reset_ts


def is_rate_limited() -> bool:
    """Check if ANY agent is currently rate limited."""
    now = time.time()
    return any(info["reset_ts"] > now for info in _agent_rate_limits.values())


def is_agent_rate_limited(agent: str) -> bool:
    """Check if a specific agent is rate limited."""
    info = _agent_rate_limits.get(agent)
    if info is None:
        return False
    if time.time() >= info["reset_ts"]:
        del _agent_rate_limits[agent]
        return False
    return True


def get_rate_limit_info() -> Optional[dict]:
    """Get rate limit info if any agent is limited. Used by API/WebSocket."""
    now = time.time()
    active = {a: info for a, info in _agent_rate_limits.items() if info["reset_ts"] > now}
    if not active:
        return None
    # Return info about the latest rate limit
    max_agent = max(active, key=lambda a: active[a]["reset_ts"])
    max_info = active[max_agent]
    remaining = int(max_info["reset_ts"] - now)
    return {
        "until": max_info["reset_ts"],
        "until_iso": datetime.fromtimestamp(max_info["reset_ts"]).isoformat(),
        "remaining_seconds": remaining,
        "agents": {
            a: {
                "reset_ts": info["reset_ts"],
                "reset_iso": datetime.fromtimestamp(info["reset_ts"]).isoformat(),
                "first_detected": info["first_detected"],
                "first_detected_iso": datetime.fromtimestamp(info["first_detected"]).isoformat(),
            }
            for a, info in active.items()
        },
    }


def _is_agent_process_alive(tmux_session: str, agent: str) -> bool:
    """Check if the Claude Code process is still running in the agent's tmux pane.

    Each agent runs in a tmux pane with zsh as the base shell.
    When Claude Code is running, it's a child process of that zsh.
    If Claude crashes or exits, zsh has no children.
    """
    try:
        pane_pid = subprocess.check_output(
            ["tmux", "list-panes", "-t", f"{tmux_session}:{agent}",
             "-F", "#{pane_pid}"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        ).strip()
        if not pane_pid:
            return False
        # Check if the pane's shell has any child processes
        children = subprocess.check_output(
            ["pgrep", "-P", pane_pid],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        ).strip()
        return bool(children)
    except subprocess.CalledProcessError:
        # pgrep returns exit code 1 if no processes found
        return False
    except subprocess.TimeoutExpired:
        return True  # Assume alive if we can't check


async def _auto_restart_agent(agent: str, root_dir: str, store=None):
    """Auto-restart a crashed agent and send continuation message."""
    now = time.time()
    last_attempt = _auto_restart_cooldown.get(agent, 0)
    if now - last_attempt < AUTO_RESTART_COOLDOWN:
        logger.debug(f"Skipping auto-restart of {agent}: cooldown ({int(AUTO_RESTART_COOLDOWN - (now - last_attempt))}s remaining)")
        return

    _auto_restart_cooldown[agent] = now
    logger.info(f"Auto-restarting crashed agent: {agent}")

    # Send continuation message
    if store:
        msg = (
            f"你的 session 被系统自动重启（检测到进程异常退出）。\n\n"
            f"请执行以下步骤:\n"
            f"1. 检查 MCP 工具是否正常（尝试调用 list_tickets 或 get_inbox）\n"
            f"2. 用 get_inbox(agent_id=\"{agent}\") 检查未读消息\n"
            f"3. 用 list_tickets(assignee=\"{agent}\", status=\"3,4\") 检查待办任务\n"
            f"4. 继续之前的工作"
        )
        await store.insert_message("system", agent, msg)

    restart_script = os.path.join(root_dir, "restart_all_agents.sh")
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", restart_script, agent,
            cwd=root_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode == 0:
            logger.info(f"Auto-restarted {agent} successfully")
        else:
            logger.error(f"Auto-restart {agent} failed: {stderr.decode()}")
    except asyncio.TimeoutError:
        logger.error(f"Auto-restart {agent} timed out")
    except Exception as e:
        logger.error(f"Auto-restart {agent} error: {e}")


def _send_tmux_message(tmux_session: str, agent: str, msg: str):
    """Send a message to an agent's tmux pane (literal text + Enter)."""
    subprocess.run(
        ["tmux", "send-keys", "-l", "-t", f"{tmux_session}:{agent}", msg],
        check=True,
        timeout=_SUBPROCESS_TIMEOUT,
    )
    time.sleep(2)
    subprocess.run(
        ["tmux", "send-keys", "-t", f"{tmux_session}:{agent}", "Enter"],
        check=True,
        timeout=_SUBPROCESS_TIMEOUT,
    )


def _dispatch_agent(tmux_session: str, agent: str):
    msg = (
        f"你有待处理的任务。"
        f"请先用 get_inbox(agent_id=\"{agent}\") 检查是否有未读消息并处理，"
        f"然后查询分配给你的任务（tags 包含 agent:{agent}，status=3,4）并执行。"
    )
    _send_tmux_message(tmux_session, agent, msg)


def _dispatch_agent_messages(tmux_session: str, agent: str, unread_count: int):
    msg = (
        f"你有 {unread_count} 条未读消息。"
        f"请使用 get_inbox(agent_id=\"{agent}\") 查看并处理消息，"
        f"处理完毕后检查待处理任务（tags 包含 agent:{agent}，status=3,4）。"
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


def _dispatch_agent_unattended(tmux_session: str, agent: str, tickets: list[dict]):
    """Dispatch agent about unattended new tickets (status=3) that haven't been picked up."""
    ticket_list = ", ".join(f"#{t['id']}" for t in tickets)
    msg = (
        f"你有 {len(tickets)} 个未处理的新 ticket：{ticket_list}。"
        f"请查看并领取任务（设为进行中并开始工作）。"
        f"先用 get_inbox(agent_id=\"{agent}\") 检查未读消息，"
        f"然后查询分配给你的任务（tags 包含 agent:{agent}，status=3,4）并执行。"
    )
    _send_tmux_message(tmux_session, agent, msg)


def _dispatch_agent_schedule(tmux_session: str, agent: str, prompt: str):
    _send_tmux_message(tmux_session, agent, prompt)


def _dispatch_agent_notifications(tmux_session: str, agent: str, notif_count: int):
    """Dispatch agent about pending notifications (Pub/Sub)."""
    msg = (
        f"你有 {notif_count} 条未读通知。"
        f"请使用 get_notifications(agent_id=\"{agent}\") 查看并处理通知，"
        f"然后检查未读消息（get_inbox）和待处理任务（assignee={agent}，status=3,4）。"
    )
    _send_tmux_message(tmux_session, agent, msg)


async def deferred_dispatch(
    tmux_session: str,
    agent: str,
    ticket_id: int,
    store=None,
    interval: int = DEFERRED_DISPATCH_INTERVAL,
    max_wait: int = DEFERRED_DISPATCH_MAX_WAIT,
) -> str:
    """Retry dispatching an agent until it becomes idle or timeout.

    Used by reassign_ticket when the target agent is busy. Runs as a background
    asyncio task, checking every `interval` seconds for up to `max_wait` seconds.

    Returns the final dispatch result: 'dispatched', 'timeout', 'no_window', or 'error'.
    """
    start = time.time()
    attempt = 0

    while time.time() - start < max_wait:
        attempt += 1
        await asyncio.sleep(interval)

        if not _tmux_window_exists(tmux_session, agent):
            logger.info(f"Deferred dispatch {agent}: no tmux window, giving up")
            return "no_window"

        if _is_idle(tmux_session, agent):
            try:
                _dispatch_agent(tmux_session, agent)
                elapsed = int(time.time() - start)
                logger.info(
                    f"Deferred dispatch {agent}: dispatched after {elapsed}s "
                    f"({attempt} attempts, ticket #{ticket_id})"
                )
                # Log dispatch event if store available
                if store:
                    try:
                        await store.log_dispatch_event(
                            agent, "deferred",
                            f"Deferred dispatch after {elapsed}s ({attempt} retries) for ticket #{ticket_id}",
                        )
                    except Exception:
                        pass  # Logging is best-effort
                return "dispatched"
            except Exception as e:
                logger.warning(f"Deferred dispatch {agent}: dispatch failed: {e}")
                return "error"

        logger.debug(
            f"Deferred dispatch {agent}: still busy "
            f"(attempt {attempt}, {int(time.time() - start)}s elapsed)"
        )

    elapsed = int(time.time() - start)
    logger.info(
        f"Deferred dispatch {agent}: timed out after {elapsed}s "
        f"({attempt} attempts, ticket #{ticket_id})"
    )
    return "timeout"


def schedule_deferred_dispatch(
    tmux_session: str,
    agent: str,
    ticket_id: int,
    store=None,
) -> str:
    """Schedule a deferred dispatch as a background task.

    If a deferred dispatch is already running for this agent, skip it.
    Returns: 'scheduled', 'already_pending', or 'error'.
    """
    # Clean up completed tasks
    done_agents = [
        a for a, task in _deferred_dispatch_tasks.items()
        if task.done()
    ]
    for a in done_agents:
        del _deferred_dispatch_tasks[a]

    # Don't stack multiple deferred dispatches for the same agent
    if agent in _deferred_dispatch_tasks:
        logger.debug(f"Deferred dispatch already pending for {agent}, skipping")
        return "already_pending"

    try:
        task = asyncio.create_task(
            deferred_dispatch(tmux_session, agent, ticket_id, store=store)
        )
        _deferred_dispatch_tasks[agent] = task
        logger.info(f"Scheduled deferred dispatch for {agent} (ticket #{ticket_id})")
        return "scheduled"
    except Exception as e:
        logger.warning(f"Failed to schedule deferred dispatch for {agent}: {e}")
        return "error"


def get_agent_tmux_status(tmux_session: str, agent: str) -> str:
    """Get agent's tmux status: 'idle', 'busy', 'rate_limited', 'crashed', 'no_window', or 'unknown'."""
    if not _tmux_window_exists(tmux_session, agent):
        return "no_window"

    # Check if Claude process is still running
    if not _is_agent_process_alive(tmux_session, agent):
        return "crashed"

    if _is_idle(tmux_session, agent):
        # Check if idle due to rate limit — must verify reset time is in the future
        # (stale rate limit text persists on screen long after the limit expires)
        reset_ts = _check_rate_limited(tmux_session, agent)
        if reset_ts is not None:
            return "rate_limited"
        return "idle"

    # _is_idle returned False → "esc to interrupt" is present → agent is busy.
    # No need to check for specific spinner text; the status bar signal is
    # the single source of truth for busy/idle.
    return "busy"


async def dispatch_cycle(client: SQLiteTaskClient, agents: list[str],
                         tmux_session: str, store=None,
                         staleness_threshold: int = 30,
                         root_dir: Optional[str] = None) -> dict:
    """Run one dispatch cycle. Returns status dict for each agent.

    Args:
        staleness_threshold: Minutes before in_progress tickets are considered stale (0=disabled).
        root_dir: Project root directory.
    """
    # Clean up expired per-agent rate limits
    now = time.time()
    expired = [a for a, info in _agent_rate_limits.items() if info["reset_ts"] <= now]
    for a in expired:
        del _agent_rate_limits[a]
        logger.info(f"Rate limit expired for {a}, resuming dispatch")

    # Check blocked deps first
    unblocked = await client.check_and_unblock_deps()
    for msg in unblocked:
        logger.info(msg)

    # Clean up expired service locks
    if store:
        try:
            expired_locks = await store.cleanup_expired_locks()
            if expired_locks:
                logger.info(f"Cleaned up {expired_locks} expired service lock(s)")
        except Exception as e:
            logger.debug(f"Service lock cleanup failed: {e}")

    # Load schedules from DB (once per cycle, shared across all agents)
    all_schedules = []
    if store:
        try:
            all_schedules = await store.get_all_schedules()
        except Exception as e:
            logger.warning(f"Failed to load schedules: {e}")

    results = {}
    for agent in agents:
        # Skip agent if it's individually rate limited
        if is_agent_rate_limited(agent):
            results[agent] = "rate_limited"
            continue

        # Check for unread notifications (Pub/Sub)
        notif_count = 0
        if store:
            try:
                notif_count = await store.get_unread_notification_count(agent)
            except Exception:
                pass

        # Check for unread messages
        unread_count = 0
        if store:
            unread_count = await store.get_unread_count(agent)

        has_tasks = await client.has_pending_tasks(agent)

        # Collect due schedule prompts from DB
        schedule_prompts = []
        due_schedule_ids = []

        if not notif_count and not unread_count and not has_tasks:
            for sched in all_schedules:
                if sched["agent_id"] != agent:
                    continue
                interval_sec = sched["interval_hours"] * 3600
                last = sched["last_dispatched_at"] or 0
                if now - last >= interval_sec:
                    schedule_prompts.append(sched["prompt"])
                    due_schedule_ids.append(sched["id"])

        schedule_due = bool(schedule_prompts)

        if not notif_count and not unread_count and not has_tasks and not schedule_due:
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
            existing = _agent_rate_limits.get(agent)
            _agent_rate_limits[agent] = {
                "reset_ts": reset_ts,
                "first_detected": existing["first_detected"] if existing else time.time(),
            }
            reset_str = datetime.fromtimestamp(reset_ts).strftime("%Y-%m-%d %H:%M:%S")
            logger.warning(
                f"Rate limit detected on {agent}, skipping until {reset_str}"
            )
            results[agent] = "rate_limited"
            continue

        # Priority: notifications > messages > tasks > schedule
        if notif_count:
            _dispatch_agent_notifications(tmux_session, agent, notif_count)
            results[agent] = f"dispatched_notifications({notif_count})"
            logger.info(f"Dispatched {agent} (notifications: {notif_count})")
            if store:
                try:
                    await store.log_dispatch_event(agent, "notifications", f"{notif_count} unread notifications")
                except Exception:
                    pass
        elif unread_count:
            _dispatch_agent_messages(tmux_session, agent, unread_count)
            results[agent] = f"dispatched_messages({unread_count})"
            logger.info(f"Dispatched {agent} (messages: {unread_count})")
            if store:
                try:
                    await store.log_dispatch_event(agent, "messages", f"{unread_count} unread messages")
                except Exception:
                    pass
        elif has_tasks:
            stale = await client.get_stale_in_progress(agent, staleness_threshold) if staleness_threshold > 0 else []
            unattended = await client.get_unattended_new_tickets(agent, staleness_threshold) if staleness_threshold > 0 else []
            if stale or unattended:
                # Cooldown: don't spam the same stale/unattended reminder every 30s.
                last_stale = _stale_dispatch_cooldown.get(agent, 0)
                if now - last_stale >= STALE_DISPATCH_COOLDOWN:
                    if unattended:
                        # Prioritize unattended new tickets — agent hasn't started them yet
                        _dispatch_agent_unattended(tmux_session, agent, unattended)
                        _stale_dispatch_cooldown[agent] = now
                        results[agent] = f"dispatched_unattended({len(unattended)})"
                        logger.info(f"Dispatched {agent} (unattended new tickets: {[t['id'] for t in unattended]})")
                        if store:
                            try:
                                ticket_ids = [t['id'] for t in unattended]
                                await store.log_dispatch_event(
                                    agent, "unattended",
                                    f"Unattended new tickets: {ticket_ids}",
                                )
                            except Exception:
                                pass
                    elif stale:
                        _dispatch_agent_stale(tmux_session, agent, stale)
                        _stale_dispatch_cooldown[agent] = now
                        results[agent] = f"dispatched_stale({len(stale)})"
                        logger.info(f"Dispatched {agent} (stale tickets: {[t['id'] for t in stale]})")
                        if store:
                            try:
                                ticket_ids = [t['id'] for t in stale]
                                await store.log_dispatch_event(
                                    agent, "staleness",
                                    f"Stale in-progress tickets: {ticket_ids}",
                                )
                            except Exception:
                                pass
                else:
                    results[agent] = "stale_cooldown"
            else:
                _dispatch_agent(tmux_session, agent)
                results[agent] = "dispatched_tasks"
                logger.info(f"Dispatched {agent} (tasks)")
                if store:
                    try:
                        await store.log_dispatch_event(agent, "periodic", "Pending tasks found")
                    except Exception:
                        pass
        elif schedule_due:
            combined_prompt = "\n\n".join(schedule_prompts)
            _dispatch_agent_schedule(tmux_session, agent, combined_prompt)
            results[agent] = "dispatched_schedule"
            logger.info(f"Dispatched {agent} (schedule, {len(schedule_prompts)} trigger(s))")
            if store:
                try:
                    await store.log_dispatch_event(
                        agent, "schedule",
                        f"{len(schedule_prompts)} schedule trigger(s)",
                    )
                except Exception:
                    pass
            # Persist schedule dispatch timestamps in DB
            if store and due_schedule_ids:
                for sid in due_schedule_ids:
                    try:
                        await store.update_schedule_dispatched(sid, now)
                    except Exception as e:
                        logger.warning(f"Failed to update schedule #{sid} dispatch time: {e}")

    # Health check pass: detect and auto-restart crashed agents
    # Skip admin agent — it manages others and should never be auto-restarted.
    if root_dir:
        for agent in agents:
            if agent == "admin":
                continue
            if agent in results and results[agent] in ("rate_limited", "no_window", "auto_restarted"):
                continue
            if not _tmux_window_exists(tmux_session, agent):
                continue
            if not _is_agent_process_alive(tmux_session, agent):
                logger.warning(f"Agent {agent} process not running (crashed/exited), scheduling auto-restart")
                results[agent] = "auto_restarted"
                asyncio.create_task(_auto_restart_agent(agent, root_dir, store))

    return results


async def dispatch_loop(client: SQLiteTaskClient, agents: list[str],
                        tmux_session: str, store=None, interval: int = 30,
                        staleness_threshold: int = 30,
                        root_dir: Optional[str] = None):
    """Run dispatch cycles in a loop."""
    stale_info = f", staleness={staleness_threshold}m" if staleness_threshold else ""
    logger.info(f"Auto-dispatch started, interval={interval}s, agents={agents}{stale_info} (schedules from DB)")

    while True:
        try:
            results = await dispatch_cycle(client, agents, tmux_session,
                                           store=store,
                                           staleness_threshold=staleness_threshold,
                                           root_dir=root_dir)
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
