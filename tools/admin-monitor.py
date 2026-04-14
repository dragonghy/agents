"""Admin monitoring script: runs periodically to check system state.

Checks:
1. Active sessions and their ticket status
2. Open PRs that need review
3. Tickets that need attention (status=4 with no active session)
4. System health

Sends report via Telegram outbox — but ONLY when meaningful state has changed
since the last run (deduped via hash in /tmp/admin-monitor-state.json), or when
more than FORCE_SEND_AFTER seconds have elapsed since the last send.

Rationale: Human complained that hourly identical "0 sessions, no PRs, same
tickets" check-ins are token waste (#462). Silence is the default; Telegram
only fires when something actually changes.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

DAEMON = "http://127.0.0.1:8765"
STATE_FILE = "/tmp/admin-monitor-state.json"
# If nothing changed for this long, send a heartbeat anyway so Human knows the
# monitor is still alive. 6 hours.
FORCE_SEND_AFTER = 6 * 3600


def api_get(path):
    try:
        req = urllib.request.Request(f"{DAEMON}/api/v1/{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def api_post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{DAEMON}/api/v1/{path}", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"warn: could not save state: {e}", file=sys.stderr)


def collect_state():
    """Gather raw state. Returns (state_dict, lines_for_report)."""
    state = {}
    lines = []

    # 1. Active sessions
    try:
        windows = subprocess.check_output(
            ["tmux", "list-windows", "-t", "agents", "-F", "#{window_name}"],
            text=True, timeout=5,
        ).strip().split("\n")
        ticket_sessions = sorted(w for w in windows if w.startswith("ticket-"))
        state["sessions"] = ticket_sessions
        lines.append(f"**Sessions**: {len(ticket_sessions)} active")
        for s in ticket_sessions:
            lines.append(f"  - `{s}`")
    except Exception:
        state["sessions"] = None
        lines.append("**Sessions**: unable to check")

    # 2. Open PRs
    try:
        pr_out = subprocess.check_output(
            ["gh", "pr", "list", "--state", "open", "--json", "number,title,mergeStateStatus"],
            text=True, timeout=15,
        )
        prs = json.loads(pr_out)
        state["prs"] = sorted(
            [(p["number"], p.get("mergeStateStatus", "")) for p in prs]
        )
        if prs:
            lines.append(f"\n**Open PRs**: {len(prs)}")
            for pr in prs:
                status = "⚠️ CONFLICT" if pr.get("mergeStateStatus") == "DIRTY" else "✅ clean"
                lines.append(f"  - PR #{pr['number']}: {pr['title'][:50]} ({status})")
        else:
            lines.append("\n**Open PRs**: none")
    except Exception:
        state["prs"] = None
        lines.append("\n**Open PRs**: unable to check")

    # 3. Tickets needing attention
    state["tickets"] = {}
    for status_code, label in [("4", "In Progress"), ("3", "New")]:
        tickets = api_get(f"tickets?status={status_code}&limit=10")
        ticket_list = tickets.get("tickets", [])
        non_human = [t for t in ticket_list if t.get("assignee") != "human"]
        state["tickets"][status_code] = sorted(t["id"] for t in non_human)
        if non_human:
            lines.append(f"\n**{label} tickets** ({len(non_human)}):")
            for t in non_human:
                lines.append(f"  - #{t['id']}: {t['headline'][:50]}")

    # 4. Health
    health = api_get("health")
    state["health_ok"] = health.get("status") == "ok"
    if state["health_ok"]:
        lines.append(f"\n**Health**: ✅ OK")
    else:
        lines.append(f"\n**Health**: ❌ {health}")

    return state, lines


def state_hash(state):
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, default=str).encode()
    ).hexdigest()


def main():
    now_ts = time.time()
    now_str = datetime.now().strftime("%H:%M")

    state, lines = collect_state()
    h = state_hash(state)

    prev = load_state()
    prev_hash = prev.get("hash")
    last_send = prev.get("last_send_ts", 0)

    changed = h != prev_hash
    overdue = (now_ts - last_send) > FORCE_SEND_AFTER

    if not (changed or overdue):
        print(f"[{now_str}] no change since last check-in; skipping Telegram send")
        # Still update timestamp of last poll so we know monitor ran
        prev["last_poll_ts"] = now_ts
        save_state(prev)
        return

    header_note = ""
    if not changed and overdue:
        header_note = " (heartbeat — no changes)"

    report = "\n".join([f"🔍 Admin Check-in ({now_str}){header_note}", ""] + lines)
    print(report)

    result = api_post("human/send", {"body": report, "context_type": "admin_checkin"})
    if "error" not in result:
        print(f"\n→ Sent to Telegram (msg_id={result.get('message_id')})")
        save_state({
            "hash": h,
            "last_send_ts": now_ts,
            "last_poll_ts": now_ts,
        })
    else:
        print(f"\n→ Send failed: {result['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
