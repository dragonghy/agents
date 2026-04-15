#!/usr/bin/env python3
"""Daily CourtReserve availability check for Sunnyvale pickleball.

Run at 12:00 PT. Queries day+8 (max booking window for residents) for
7:00-9:00 PM slots. If any courts are available, notifies Human via
the agents-mcp daemon Telegram outbound endpoint.

Config (projects/pickleball/.env):
    CR_USER=...         # CourtReserve login email
    CR_PASS=...         # CourtReserve password

Env overrides:
    CR_DAYS_AHEAD=8     # days from today to query
    CR_WINDOW_START=19  # hour (local), inclusive
    CR_WINDOW_END=21    # hour (local), exclusive
    DAEMON_URL=http://localhost:8765
    DRY_RUN=1           # print report, skip Telegram send
    HEADLESS=1          # run chromium headless (default); set to 0 for debugging
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGIN_URL = "https://app.courtreserve.com/Online/Account/LogIn/13233"
PB_URL = "https://app.courtreserve.com/Online/Reservations/Bookings/13233?sId=16984"


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def log(msg: str) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)


def ms_to_local(ms: int) -> dt.datetime:
    """CourtReserve returns /Date(unixms)/ in UTC. Sunnyvale is Pacific.

    Use Python's zoneinfo to get DST-correct offset instead of hardcoding -7h.
    """
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(ms / 1000, tz=ZoneInfo("America/Los_Angeles"))
    except Exception:
        return dt.datetime.utcfromtimestamp(ms / 1000) - dt.timedelta(hours=7)


def parse_cr_date(s: str) -> dt.datetime | None:
    m = re.search(r"/Date\((\d+)\)/", s or "")
    return ms_to_local(int(m.group(1))) if m else None


class TargetNotReached(RuntimeError):
    """Raised when the target date was never loaded by the scheduler.

    Usually means the booking window hasn't opened yet (CourtReserve
    releases day+8 at 12:00 PT; running earlier only sees day+7).
    """


def run_scrape(target_date: dt.date, days_ahead: int) -> list[dict]:
    """Return list of slot dicts for target_date.

    Each slot: {start, end, available_courts, in_past, closed}
    Raises TargetNotReached if the scheduler never loaded the target date.
    """
    user = os.environ.get("CR_USER")
    pw = os.environ.get("CR_PASS")
    if not user or not pw:
        raise RuntimeError("CR_USER / CR_PASS not set (see .env.example)")

    headless = os.environ.get("HEADLESS", "1") != "0"
    log(f"launching chromium headless={headless}")

    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            viewport={"width": 1500, "height": 950},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

        def on_response(resp):
            url = resp.url
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" in ct and "ReadConsolidated" in url:
                try:
                    captured.append({"url": url, "json": resp.json()})
                except Exception:
                    pass

        page.on("response", on_response)

        def _retry(fn, tries=3, delay=3):
            last = None
            for t in range(tries):
                try:
                    return fn()
                except Exception as e:
                    last = e
                    log(f"  retry {t + 1}/{tries}: {e}")
                    time.sleep(delay)
            raise last

        log("login …")
        _retry(lambda: page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000))
        page.wait_for_selector("input[name='email']", timeout=15000)
        page.fill("input[name='email']", user)
        page.fill("input[name='password']", pw)
        page.locator("button[type='submit'], input[type='submit']").first.click()
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        log("open pickleball scheduler …")
        _retry(lambda: page.goto(PB_URL, wait_until="domcontentloaded", timeout=45000))
        try:
            page.wait_for_selector("[data-role='scheduler']", timeout=15000)
        except Exception as e:
            log(f"scheduler selector timeout: {e}")
        time.sleep(4)

        def _has_target():
            for c in captured:
                j = c.get("json") or {}
                for slot in (j.get("Data") or []):
                    s = parse_cr_date(slot.get("Start") or "")
                    if s and s.date() == target_date:
                        return True
            return False

        def _click_next():
            try:
                page.locator("[title='Next']").first.click(timeout=2500)
                return True
            except Exception:
                try:
                    page.locator(".k-i-arrow-60-right").first.click(timeout=2500)
                    return True
                except Exception:
                    return False

        # Click "Next" until we see the target date in captures, up to a bounded
        # number of clicks (Next is flaky and sometimes re-fires an XHR for the
        # current day, so we can't rely on a fixed click count).
        max_clicks = days_ahead + 8
        for i in range(max_clicks):
            if _has_target():
                break
            if not _click_next():
                log(f"cannot click Next at iteration {i}")
                break
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            time.sleep(1.2)

        # Final buffer wait for in-flight XHR.
        for _ in range(20):
            if _has_target():
                break
            time.sleep(0.5)
        target_loaded = _has_target()
        if not target_loaded:
            log(f"ERROR: target {target_date} not in captures after wait")
        time.sleep(1)
        browser.close()

    if not target_loaded:
        raise TargetNotReached(
            f"scheduler never loaded {target_date}. Booking window likely "
            f"not yet open (CourtReserve releases day+{days_ahead} at 12:00 PT)."
        )

    # Pick slots whose local start date == target_date.
    # Dedupe by (Id, Start) — CR reuses Id=0 for availability blocks so Id alone
    # collapses multiple days.
    slots: list[dict] = []
    seen: set = set()
    for c in captured:
        j = c.get("json") or {}
        if not isinstance(j, dict) or "Data" not in j:
            continue
        for slot in j["Data"]:
            start = parse_cr_date(slot.get("Start") or "")
            end = parse_cr_date(slot.get("End") or "")
            if not start or start.date() != target_date:
                continue
            key = (slot.get("Id"), slot.get("Start"), slot.get("CourtId"))
            if key in seen:
                continue
            seen.add(key)
            slots.append(
                {
                    "start": start,
                    "end": end,
                    "available_courts": int(slot.get("AvailableCourts", 0) or 0),
                    "in_past": bool(slot.get("IsInPast")),
                    "closed": bool(slot.get("IsClosed")),
                }
            )
    slots.sort(key=lambda s: s["start"])
    # Debug: count all captured slot dates
    from collections import Counter as _C
    _counts = _C()
    for c in captured:
        j = c.get("json") or {}
        if not isinstance(j, dict) or "Data" not in j:
            continue
        for slot in j["Data"]:
            s = parse_cr_date(slot.get("Start") or "")
            if s:
                _counts[s.date()] += 1
    log(f"captured {len(captured)} ReadConsolidated XHR")
    log(f"dates seen: {dict(sorted(_counts.items()))}")
    log(f"slots for target {target_date}: {len(slots)}")
    return slots


def filter_evening(slots: list[dict], start_hour: int, end_hour: int) -> list[dict]:
    return [
        s
        for s in slots
        if s["start"].hour >= start_hour
        and s["start"].hour < end_hour
        and not s["in_past"]
        and not s["closed"]
        and s["available_courts"] > 0
    ]


def format_report(target_date: dt.date, open_slots: list[dict], window: str) -> str:
    weekday = target_date.strftime("%A")
    header = f"🎾 Pickleball {target_date.strftime('%Y-%m-%d')} ({weekday}) {window}"
    if not open_slots:
        return f"{header}\n全部订满 🚫"
    lines = [header, ""]
    for s in open_slots:
        t1 = s["start"].strftime("%H:%M")
        t2 = s["end"].strftime("%H:%M")
        lines.append(f"• {t1}–{t2}  空闲球场: {s['available_courts']}")
    lines.append("")
    lines.append("https://app.courtreserve.com/Online/Reservations/Bookings/13233?sId=16984")
    return "\n".join(lines)


def notify_human(body: str) -> None:
    daemon = os.environ.get("DAEMON_URL", "http://localhost:8765")
    url = f"{daemon}/api/v1/human/send"
    payload = json.dumps({"body": body, "context_type": "pickleball_daily"}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            log(f"telegram sent: {data}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"daemon {e.code}: {e.read().decode()}")


def main() -> int:
    load_env()
    days_ahead = int(os.environ.get("CR_DAYS_AHEAD", "8"))
    start_hour = int(os.environ.get("CR_WINDOW_START", "19"))
    end_hour = int(os.environ.get("CR_WINDOW_END", "21"))
    dry_run = os.environ.get("DRY_RUN", "0") == "1"

    target_date = dt.date.today() + dt.timedelta(days=days_ahead)
    window = f"{start_hour:02d}:00–{end_hour:02d}:00"
    log(f"target={target_date} window={window} dry_run={dry_run}")

    try:
        slots = run_scrape(target_date, days_ahead)
    except TargetNotReached as e:
        log(f"scrape: {e}")
        if not dry_run:
            notify_human(
                f"⚠️ Pickleball 每日检查: 未能载入 {target_date} 的时段（预订窗口可能尚未开放）。"
                f"\n请检查是否在 12:00 PT 之后运行。"
                f"\n(projects/pickleball/daily_check.py)"
            )
        return 2
    except Exception as e:
        log(f"scrape failed: {e}")
        traceback.print_exc()
        if not dry_run:
            notify_human(
                f"⚠️ Pickleball 每日检查失败: {e}\n(projects/pickleball/daily_check.py)"
            )
        return 1

    open_slots = filter_evening(slots, start_hour, end_hour)
    log(f"open slots in window: {len(open_slots)}")

    report = format_report(target_date, open_slots, window)
    log("report:\n" + report)

    if dry_run:
        log("DRY_RUN=1, skipping Telegram send")
        return 0

    # Only notify when there's good news. Silent when nothing open (cron noise).
    if open_slots:
        notify_human(report)
    else:
        log("no open slots; skipping notification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
