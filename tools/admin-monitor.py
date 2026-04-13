"""Admin monitoring script: runs periodically to check system state.

Checks:
1. Active sessions and their ticket status
2. Open PRs that need review
3. Tickets that need attention (status=4 with no active session)
4. System health

Sends report via Telegram outbox.
"""
import json
import subprocess
import sys
import urllib.request
from datetime import datetime

DAEMON = "http://127.0.0.1:8765"


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


def main():
    now = datetime.now().strftime("%H:%M")
    lines = [f"🔍 Admin Check-in ({now})", ""]

    # 1. Active sessions
    try:
        windows = subprocess.check_output(
            ["tmux", "list-windows", "-t", "agents", "-F", "#{window_name}"],
            text=True, timeout=5,
        ).strip().split("\n")
        ticket_sessions = [w for w in windows if w.startswith("ticket-")]
        lines.append(f"**Sessions**: {len(ticket_sessions)} active")
        for s in ticket_sessions:
            lines.append(f"  - `{s}`")
    except Exception:
        lines.append("**Sessions**: unable to check")

    # 2. Open PRs
    try:
        pr_out = subprocess.check_output(
            ["gh", "pr", "list", "--state", "open", "--json", "number,title,mergeStateStatus"],
            text=True, timeout=15,
        )
        prs = json.loads(pr_out)
        if prs:
            lines.append(f"\n**Open PRs**: {len(prs)}")
            for pr in prs:
                status = "⚠️ CONFLICT" if pr.get("mergeStateStatus") == "DIRTY" else "✅ clean"
                lines.append(f"  - PR #{pr['number']}: {pr['title'][:50]} ({status})")
        else:
            lines.append("\n**Open PRs**: none")
    except Exception:
        lines.append("\n**Open PRs**: unable to check")

    # 3. Tickets needing attention
    for status_code, label in [("4", "In Progress"), ("3", "New")]:
        tickets = api_get(f"tickets?status={status_code}&limit=10")
        ticket_list = tickets.get("tickets", [])
        non_human = [t for t in ticket_list if t.get("assignee") != "human"]
        if non_human:
            lines.append(f"\n**{label} tickets** ({len(non_human)}):")
            for t in non_human:
                lines.append(f"  - #{t['id']}: {t['headline'][:50]}")

    # 4. Health
    health = api_get("health")
    if health.get("status") == "ok":
        lines.append(f"\n**Health**: ✅ OK")
    else:
        lines.append(f"\n**Health**: ❌ {health}")

    report = "\n".join(lines)
    print(report)

    # Send via Telegram
    result = api_post("human/send", {"body": report, "context_type": "admin_checkin"})
    if "error" not in result:
        print(f"\n→ Sent to Telegram (msg_id={result.get('message_id')})")


if __name__ == "__main__":
    main()
