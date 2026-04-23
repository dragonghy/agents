#!/usr/bin/env python3
"""Daily CourtReserve availability check + auto-booking for Sunnyvale pickleball.

Run at 12:00 PT. Queries day+8 (max booking window for residents) for
7:00-9:00 PM slots. On target days (Tue/Fri/Sat), automatically books
a 1-hour slot. Otherwise, just reports availability.

Config (projects/pickleball/.env):
    CR_USER=...         # CourtReserve login email
    CR_PASS=...         # CourtReserve password

Env overrides:
    CR_DAYS_AHEAD=8     # days from today to query
    CR_WINDOW_START=19  # hour (local), inclusive
    CR_WINDOW_END=21    # hour (local), exclusive
    DAEMON_URL=http://localhost:8765
    DRY_RUN=1           # print report, skip booking + Telegram send
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
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
BOOKINGS_FILE = ROOT / "bookings.json"

LOGIN_URL = "https://app.courtreserve.com/Online/Account/LogIn/13233"
PB_URL = "https://app.courtreserve.com/Online/Reservations/Bookings/13233?sId=16984"

# Days of the week to auto-book (Monday=0 ... Sunday=6)
BOOKING_DAYS = {1, 4, 5}  # Tuesday, Friday, Saturday


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
    """CourtReserve returns /Date(unixms)/ in UTC. Sunnyvale is Pacific."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(ms / 1000, tz=ZoneInfo("America/Los_Angeles"))
    except Exception:
        return dt.datetime.utcfromtimestamp(ms / 1000) - dt.timedelta(hours=7)


def parse_cr_date(s: str) -> dt.datetime | None:
    m = re.search(r"/Date\((\d+)\)/", s or "")
    return ms_to_local(int(m.group(1))) if m else None


class TargetNotReached(RuntimeError):
    """Raised when the target date was never loaded by the scheduler."""


# ---------------------------------------------------------------------------
# Bookings ledger — local JSON file tracking successful bookings
# ---------------------------------------------------------------------------

def load_bookings() -> list[dict]:
    """Load bookings ledger from disk."""
    if not BOOKINGS_FILE.exists():
        return []
    try:
        return json.loads(BOOKINGS_FILE.read_text())
    except Exception:
        return []


def save_booking(target_date: dt.date, slot_start: str, slot_end: str) -> None:
    """Append a booking record to the ledger."""
    bookings = load_bookings()
    bookings.append({
        "date": target_date.isoformat(),
        "weekday": target_date.strftime("%A"),
        "start": slot_start,
        "end": slot_end,
        "booked_at": dt.datetime.now().isoformat(),
    })
    BOOKINGS_FILE.write_text(json.dumps(bookings, indent=2) + "\n")
    log(f"saved booking to {BOOKINGS_FILE}")


def has_booking_for_date(target_date: dt.date) -> bool:
    """Check if we already have a booking on the given date."""
    for b in load_bookings():
        if b.get("date") == target_date.isoformat():
            return True
    return False


def friday_of_same_week(target_date: dt.date) -> dt.date:
    """Return the Friday of the same ISO week as target_date."""
    # weekday(): Mon=0 ... Sun=6; Friday=4
    return target_date - dt.timedelta(days=target_date.weekday() - 4)


# ---------------------------------------------------------------------------
# Browser session: login + navigate + scrape
# ---------------------------------------------------------------------------

def _create_browser(pw):
    headless = os.environ.get("HEADLESS", "1") != "0"
    log(f"launching chromium headless={headless}")
    browser = pw.chromium.launch(
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
    return browser, ctx


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


def _login(page: Page) -> None:
    user = os.environ.get("CR_USER")
    pw = os.environ.get("CR_PASS")
    if not user or not pw:
        raise RuntimeError("CR_USER / CR_PASS not set (see .env.example)")
    log("login ...")
    _retry(lambda: page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000))
    page.wait_for_selector("input[name='email']", timeout=15000)
    page.fill("input[name='email']", user)
    page.fill("input[name='password']", pw)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass


def _navigate_to_target(page: Page, target_date: dt.date, days_ahead: int,
                         captured: list[dict]) -> bool:
    """Navigate the scheduler to the target date. Returns True if target loaded."""
    log("open pickleball scheduler ...")
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

    return _has_target()


def _extract_slots(captured: list[dict], target_date: dt.date) -> list[dict]:
    """Extract and dedupe slots for the target date from captured XHR data."""
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
            slots.append({
                "start": start,
                "end": end,
                "available_courts": int(slot.get("AvailableCourts", 0) or 0),
                "in_past": bool(slot.get("IsInPast")),
                "closed": bool(slot.get("IsClosed")),
                "court_id": slot.get("CourtId"),
                "raw": slot,  # keep raw data for booking
            })
    slots.sort(key=lambda s: s["start"])

    # Debug: count all captured slot dates
    _counts: Counter = Counter()
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


# ---------------------------------------------------------------------------
# Filtering + slot selection
# ---------------------------------------------------------------------------

def filter_evening(slots: list[dict], start_hour: int, end_hour: int) -> list[dict]:
    return [
        s for s in slots
        if s["start"].hour >= start_hour
        and s["start"].hour < end_hour
        and not s["in_past"]
        and not s["closed"]
        and s["available_courts"] > 0
    ]


def find_best_1h_slot(open_slots: list[dict]) -> dict | None:
    """Find the earliest pair of consecutive 30-min slots forming a 1-hour block.

    CourtReserve uses 30-min intervals. A bookable 1-hour slot means two
    consecutive 30-min slots both have available courts.

    Returns dict {start_time, end_time, slots: [slot1, slot2]} or None.
    """
    if not open_slots:
        return None

    # Sort by start time
    sorted_slots = sorted(open_slots, key=lambda s: s["start"])

    for i in range(len(sorted_slots) - 1):
        s1 = sorted_slots[i]
        s2 = sorted_slots[i + 1]
        # Check consecutive: s1 ends when s2 starts
        if s1["end"] == s2["start"]:
            # Both have availability
            if s1["available_courts"] > 0 and s2["available_courts"] > 0:
                return {
                    "start_time": s1["start"],
                    "end_time": s2["end"],
                    "slots": [s1, s2],
                }
    return None


# ---------------------------------------------------------------------------
# Booking via Playwright
# ---------------------------------------------------------------------------

_SAFE_REASON_RE = re.compile(r"[^a-z0-9]+")


def _slugify_reason(reason: str) -> str:
    """Produce a filesystem-safe slug from a human reason string."""
    slug = _SAFE_REASON_RE.sub("-", (reason or "").lower()).strip("-")
    return (slug or "unknown")[:40]


def _save_screenshot(page: Page, target_date: dt.date, reason: str) -> Path | None:
    """Save a full-page screenshot with a descriptive filename.

    Filename format: ``book-{YYYY-MM-DD}-{reason-slug}-{HHMMSS}.png``.
    Returns the path on success, None on failure. Never raises.
    """
    ts = dt.datetime.now().strftime("%H%M%S")
    ss_path = LOG_DIR / f"book-{target_date.isoformat()}-{_slugify_reason(reason)}-{ts}.png"
    try:
        page.screenshot(path=str(ss_path), full_page=True)
        log(f"screenshot saved [{reason}]: {ss_path}")
        return ss_path
    except Exception as e:
        log(f"screenshot save failed [{reason}]: {e}")
        return None


def _time_label(start_hour: int, start_min: int) -> str:
    """Format 24h hour/min as CourtReserve 12h label, e.g. (19, 0) -> '7:00 PM'."""
    if start_hour >= 12:
        display_hour = start_hour - 12 if start_hour > 12 else 12
        ampm = "PM"
    else:
        display_hour = start_hour if start_hour > 0 else 12
        ampm = "AM"
    return f"{display_hour}:{start_min:02d} {ampm}"


# JS helper: find the matching Kendo scheduler event by target start timestamp
# and click its DOM element. Returns a diagnostic dict either way so the caller
# can log exactly what the page looked like.
_CLICK_SLOT_JS = r"""
(params) => {
    const { targetMs, targetHour, targetMin } = params;
    const diag = { success: false };

    const scheduler = document.querySelector("[data-role='scheduler']");
    if (!scheduler) { diag.error = 'no scheduler'; return diag; }

    const $el = (typeof jQuery !== 'undefined') ? jQuery(scheduler) : null;
    const widget = $el ? $el.data('kendoScheduler') : null;
    if (!widget) { diag.error = 'no kendo widget'; return diag; }

    // Strategy A: iterate the dataSource and match by .start timestamp.
    let items = [];
    try { items = widget.dataSource.data() || []; } catch (e) {}
    diag.dataSourceCount = items.length;

    const matches = [];
    for (const it of items) {
        const start = it && it.start ? it.start.getTime() : null;
        if (start === targetMs) {
            matches.push({ uid: it.uid, id: it.id || it.Id });
        }
    }
    diag.strategyAMatches = matches.length;

    for (const m of matches) {
        if (!m.uid) continue;
        const el = document.querySelector(`.k-event[data-uid="${m.uid}"]`);
        if (el) {
            el.scrollIntoView({ block: 'center' });
            el.click();
            diag.success = true;
            diag.strategy = 'A-dataSource';
            diag.uid = m.uid;
            return diag;
        }
    }

    // Strategy B: iterate visible .k-event elements, ask the widget for each.
    const events = Array.from(document.querySelectorAll('.k-event[data-uid]'));
    diag.domEventCount = events.length;
    for (const el of events) {
        const uid = el.getAttribute('data-uid');
        if (!uid) continue;
        let occ = null;
        try { occ = widget.occurrenceByUid(uid); } catch (e) {}
        const start = occ && occ.start ? occ.start.getTime() : null;
        if (start === targetMs) {
            el.scrollIntoView({ block: 'center' });
            el.click();
            diag.success = true;
            diag.strategy = 'B-occurrenceByUid';
            diag.uid = uid;
            return diag;
        }
    }

    // Strategy C: legacy — match the time label row, click its content cell.
    const ampm = targetHour >= 12 ? 'PM' : 'AM';
    const disp = targetHour % 12 === 0 ? 12 : targetHour % 12;
    const label = `${disp}:${String(targetMin).padStart(2,'0')} ${ampm}`;
    diag.legacyLabel = label;

    const timeCells = document.querySelectorAll('.k-scheduler-times td, .k-scheduler-timecolumn td');
    let rowIdx = -1;
    for (let i = 0; i < timeCells.length; i++) {
        const txt = (timeCells[i].textContent || '').replace(/\s+/g, ' ').trim();
        if (txt.toUpperCase().includes(label.toUpperCase())) { rowIdx = i; break; }
    }
    diag.legacyRowIndex = rowIdx;
    if (rowIdx >= 0) {
        const rows = document.querySelectorAll('.k-scheduler-content tr');
        if (rowIdx < rows.length) {
            const cell = rows[rowIdx].querySelector('td');
            if (cell) {
                cell.scrollIntoView({ block: 'center' });
                cell.click();
                diag.success = true;
                diag.strategy = 'C-legacy-row';
                return diag;
            }
        }
    }

    diag.error = 'no strategy matched';
    return diag;
}
"""


def book_slot_via_ui(
    page: Page, target_date: dt.date, best_slot: dict
) -> tuple[bool, str, list[Path]]:
    """Book a 1-hour slot by interacting with the CourtReserve scheduler UI.

    Flow:
    1. Click the target time event in the Kendo scheduler.
    2. Booking modal appears.
    3. Set duration to 60 min.
    4. Confirm the booking.

    Returns ``(success, reason, screenshots)``. ``reason`` is a human-readable
    short description of the outcome suitable for Telegram. ``screenshots`` is
    a list of local paths for every screenshot captured during the attempt
    (may be empty if playwright screenshotting itself failed).
    """
    start_time = best_slot["start_time"]
    start_hour = start_time.hour
    start_min = start_time.minute
    target_start_ms = int(start_time.timestamp() * 1000)
    time_label = _time_label(start_hour, start_min)
    screenshots: list[Path] = []

    log(
        f"attempting to book {start_time.strftime('%H:%M')}-"
        f"{best_slot['end_time'].strftime('%H:%M')} on {target_date}"
    )
    log(f"looking for time label: {time_label}")

    try:
        # Step 1: click the availability event matching the target start time.
        clicked = page.evaluate(
            _CLICK_SLOT_JS,
            {
                "targetMs": target_start_ms,
                "targetHour": start_hour,
                "targetMin": start_min,
            },
        )
        log(f"slot click result: {clicked}")

        # Python-side fallback: if the in-page strategies all failed, try
        # clicking a Playwright-located .k-event whose bounding text contains
        # the time label. Last-ditch — kept to match legacy behaviour.
        if not clicked or not clicked.get("success"):
            ss = _save_screenshot(page, target_date, "click-fail-primary")
            if ss:
                screenshots.append(ss)

            log("primary click failed, trying Python fallback on .k-event")
            events = page.locator(".k-event").all()
            log(f"found {len(events)} event elements")
            clicked_any = False
            for ev in events:
                try:
                    text = (ev.text_content() or "").replace(" ", "")
                    if time_label.replace(" ", "") in text:
                        ev.click(timeout=3000)
                        clicked_any = True
                        log(f"clicked event via text match: {text[:60]}")
                        break
                except Exception:
                    continue

            if not clicked_any:
                log("all click strategies failed; could not open booking modal")
                ss = _save_screenshot(page, target_date, "click-fail-all")
                if ss:
                    screenshots.append(ss)
                err = (clicked or {}).get("error") or "no strategy matched"
                return (
                    False,
                    f"未能点击 {time_label} 的预定格子 ({err})",
                    screenshots,
                )

        # Step 2: wait for booking modal.
        time.sleep(2)
        modal_selectors = [
            ".modal.show",
            ".k-window",
            "#bookingModal",
            "[class*='booking']",
            "[class*='reservation']",
        ]
        modal_found = False
        for sel in modal_selectors:
            try:
                if page.locator(sel).first.is_visible(timeout=2000):
                    modal_found = True
                    log(f"booking modal found: {sel}")
                    break
            except Exception:
                continue

        if not modal_found:
            log("no booking modal appeared after clicking slot")
            ss = _save_screenshot(page, target_date, "no-modal")
            if ss:
                screenshots.append(ss)
            return False, "点击后未出现预定弹窗", screenshots

        # Step 3: try to set duration to 60 minutes.
        duration_set = _set_duration(page, 60)
        log(f"duration set to 60min: {duration_set}")

        # Step 4: click the book/reserve button.
        book_btn_selectors = [
            "button:has-text('Reserve')",
            "button:has-text('Book')",
            "button:has-text('Confirm')",
            "input[value='Reserve']",
            "input[value='Book']",
            ".btn-primary:has-text('Reserve')",
            ".btn-primary:has-text('Book')",
        ]
        booked = False
        for sel in book_btn_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=3000)
                    log(f"clicked booking button: {sel}")
                    booked = True
                    break
            except Exception:
                continue

        if not booked:
            log("could not find booking button in modal")
            ss = _save_screenshot(page, target_date, "no-book-button")
            if ss:
                screenshots.append(ss)
            return False, "预定弹窗中找不到 Reserve/Book 按钮", screenshots

        # Step 5: wait and check for confirmation / error.
        time.sleep(3)

        success_indicators = [
            ".alert-success",
            ":has-text('successfully')",
            ":has-text('confirmed')",
            ":has-text('booked')",
        ]
        confirmed = False
        for sel in success_indicators:
            try:
                if page.locator(sel).first.is_visible(timeout=2000):
                    confirmed = True
                    log(f"booking confirmed: {sel}")
                    break
            except Exception:
                continue

        # Check for explicit errors before falling back to "modal gone = ok".
        error_reason = ""
        if not confirmed:
            error_indicators = [
                ".alert-danger",
                ".alert-error",
                ":has-text('error')",
                ":has-text('failed')",
            ]
            for sel in error_indicators:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1000):
                        error_text = (el.text_content() or "").strip()
                        log(f"booking error: {error_text[:200]}")
                        error_reason = error_text[:200]
                        break
                except Exception:
                    continue

            if not error_reason:
                modal_gone = True
                for sel in modal_selectors:
                    try:
                        if page.locator(sel).first.is_visible(timeout=500):
                            modal_gone = False
                            break
                    except Exception:
                        continue
                if modal_gone:
                    log("modal closed without error — treating as success")
                    confirmed = True

        # Always record a post-attempt screenshot for evidence.
        ss = _save_screenshot(
            page, target_date, "book-confirmed" if confirmed else "book-unconfirmed"
        )
        if ss:
            screenshots.append(ss)

        if confirmed:
            return True, "预定成功", screenshots
        return (
            False,
            f"未看到成功提示 ({error_reason or 'no success/error signal'})",
            screenshots,
        )

    except Exception as e:
        log(f"booking failed with exception: {e}")
        traceback.print_exc()
        ss = _save_screenshot(page, target_date, "exception")
        if ss:
            screenshots.append(ss)
        return False, f"预定过程异常: {e}", screenshots


def _set_duration(page: Page, minutes: int) -> bool:
    """Try to set booking duration in the modal."""
    # CourtReserve may use a dropdown, input, or radio for duration
    duration_selectors = [
        "select[name*='duration' i]",
        "select[name*='Duration' i]",
        "#Duration",
        "#duration",
        "select[id*='duration' i]",
    ]
    for sel in duration_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1000):
                # Try to select by value (minutes as string)
                try:
                    el.select_option(value=str(minutes))
                    return True
                except Exception:
                    pass
                # Try by label
                try:
                    el.select_option(label=f"{minutes} min")
                    return True
                except Exception:
                    pass
                try:
                    el.select_option(label=f"{minutes} minutes")
                    return True
                except Exception:
                    pass
                try:
                    el.select_option(label="1 hour")
                    return True
                except Exception:
                    pass
        except Exception:
            continue

    # Maybe it's a Kendo dropdown
    try:
        # Look for a duration-related Kendo dropdown
        result = page.evaluate("""() => {
            const selects = document.querySelectorAll('[data-role="dropdownlist"]');
            for (const s of selects) {
                const id = (s.id || '').toLowerCase();
                const name = (s.getAttribute('name') || '').toLowerCase();
                if (id.includes('duration') || name.includes('duration')) {
                    const widget = $(s).data('kendoDropDownList');
                    if (widget) {
                        // Find the 60-minute option
                        const ds = widget.dataSource.data();
                        for (let i = 0; i < ds.length; i++) {
                            const val = ds[i].Value || ds[i].value || ds[i].Id || '';
                            const text = ds[i].Text || ds[i].text || ds[i].Name || '';
                            if (val == '60' || text.includes('60') || text.includes('1 hour')) {
                                widget.select(i);
                                widget.trigger('change');
                                return true;
                            }
                        }
                    }
                }
            }
            return false;
        }""")
        if result:
            return True
    except Exception:
        pass

    log("could not find duration selector — may default to 30min or 60min")
    return False


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(target_date: dt.date, open_slots: list[dict], window: str) -> str:
    weekday = target_date.strftime("%A")
    header = f"\U0001f3be Pickleball {target_date.strftime('%Y-%m-%d')} ({weekday}) {window}"
    if not open_slots:
        return f"{header}\n\u5168\u90e8\u8ba2\u6ee1 \U0001f6ab"
    lines = [header, ""]
    for s in open_slots:
        t1 = s["start"].strftime("%H:%M")
        t2 = s["end"].strftime("%H:%M")
        lines.append(f"\u2022 {t1}\u2013{t2}  \u7a7a\u95f2\u7403\u573a: {s['available_courts']}")
    lines.append("")
    lines.append("https://app.courtreserve.com/Online/Reservations/Bookings/13233?sId=16984")
    return "\n".join(lines)


def format_booking_result(target_date: dt.date, best_slot: dict | None,
                          success: bool, reason: str = "",
                          screenshots: list[Path] | None = None) -> str:
    weekday = target_date.strftime("%A")
    screenshots = screenshots or []
    if success and best_slot:
        t1 = best_slot["start_time"].strftime("%H:%M")
        t2 = best_slot["end_time"].strftime("%H:%M")
        return (
            f"\u2705 Pickleball \u5df2\u9884\u5b9a\n"
            f"\U0001f4c5 {target_date.strftime('%Y-%m-%d')} ({weekday})\n"
            f"\u23f0 {t1}\u2013{t2}\n"
            f"\U0001f3be Sunnyvale pickleball court"
        )
    if best_slot:
        t1 = best_slot["start_time"].strftime("%H:%M")
        t2 = best_slot["end_time"].strftime("%H:%M")
        lines = [
            f"\u26a0\ufe0f Pickleball \u9884\u5b9a\u5931\u8d25",
            f"\U0001f4c5 {target_date.strftime('%Y-%m-%d')} ({weekday})",
            f"\u23f0 \u5c1d\u8bd5\u9884\u5b9a {t1}\u2013{t2}",
            f"\u539f\u56e0: {reason or '\u672a\u77e5\u9519\u8bef'}",
        ]
    else:
        lines = [
            f"\u26a0\ufe0f Pickleball \u65e0\u53ef\u7528\u65f6\u6bb5",
            f"\U0001f4c5 {target_date.strftime('%Y-%m-%d')} ({weekday})",
            f"7-9PM \u65e0\u8fde\u7eed 1 \u5c0f\u65f6\u7a7a\u95f2\u65f6\u6bb5",
        ]
    if screenshots:
        lines.append(f"\U0001f4f8 \u622a\u56fe ({len(screenshots)}):")
        for p in screenshots:
            lines.append(f"  {p}")
    lines.append(
        "\U0001f517 https://app.courtreserve.com/Online/Reservations/Bookings/13233?sId=16984"
    )
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def should_book(target_date: dt.date) -> tuple[bool, str]:
    """Decide whether to auto-book for the target date.

    Returns (should_book, reason).
    """
    weekday = target_date.weekday()  # Mon=0 ... Sun=6
    day_name = target_date.strftime("%A")

    if weekday not in BOOKING_DAYS:
        return False, f"{day_name} is not a booking day (Tue/Fri/Sat only)"

    # Already booked this date?
    if has_booking_for_date(target_date):
        return False, f"already booked for {target_date}"

    # Saturday special case: skip if Friday of same week is already booked
    if weekday == 5:  # Saturday
        fri = friday_of_same_week(target_date)
        if has_booking_for_date(fri):
            return False, f"Saturday skip: Friday {fri} already booked"

    return True, f"{day_name} is a booking day"


def main() -> int:
    load_env()
    days_ahead = int(os.environ.get("CR_DAYS_AHEAD", "8"))
    start_hour = int(os.environ.get("CR_WINDOW_START", "19"))
    end_hour = int(os.environ.get("CR_WINDOW_END", "21"))
    dry_run = os.environ.get("DRY_RUN", "0") == "1"

    target_date = dt.date.today() + dt.timedelta(days=days_ahead)
    window = f"{start_hour:02d}:00\u2013{end_hour:02d}:00"
    log(f"target={target_date} window={window} dry_run={dry_run}")

    # Decide if we should book
    do_book, book_reason = should_book(target_date)
    log(f"auto-book: {do_book} ({book_reason})")

    captured: list[dict] = []

    try:
        with sync_playwright() as p:
            browser, ctx = _create_browser(p)
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

            # Login
            _login(page)

            # Navigate to target date
            target_loaded = _navigate_to_target(page, target_date, days_ahead, captured)
            if not target_loaded:
                log(f"ERROR: target {target_date} not in captures after wait")
                browser.close()
                raise TargetNotReached(
                    f"scheduler never loaded {target_date}. Booking window likely "
                    f"not yet open (CourtReserve releases day+{days_ahead} at 12:00 PT)."
                )

            # Extract slots
            slots = _extract_slots(captured, target_date)
            open_slots = filter_evening(slots, start_hour, end_hour)
            log(f"open slots in window: {len(open_slots)}")

            # Report
            report = format_report(target_date, open_slots, window)
            log("report:\n" + report)

            # Booking logic
            booking_result = None
            if do_book and not dry_run:
                best = find_best_1h_slot(open_slots)
                if best:
                    log(f"best 1h slot: {best['start_time'].strftime('%H:%M')}-{best['end_time'].strftime('%H:%M')}")
                    success, reason, shots = book_slot_via_ui(page, target_date, best)
                    if success:
                        save_booking(
                            target_date,
                            best["start_time"].strftime("%H:%M"),
                            best["end_time"].strftime("%H:%M"),
                        )
                        booking_result = format_booking_result(
                            target_date, best, True, screenshots=shots
                        )
                    else:
                        booking_result = format_booking_result(
                            target_date, best, False, reason=reason, screenshots=shots
                        )
                else:
                    log("no suitable 1h slot found in window")
                    booking_result = format_booking_result(target_date, None, False)
            elif do_book and dry_run:
                best = find_best_1h_slot(open_slots)
                if best:
                    log(f"DRY_RUN: would book {best['start_time'].strftime('%H:%M')}-{best['end_time'].strftime('%H:%M')}")
                else:
                    log("DRY_RUN: no suitable 1h slot found")

            time.sleep(1)
            browser.close()

    except TargetNotReached as e:
        log(f"scrape: {e}")
        if not dry_run:
            notify_human(
                f"\u26a0\ufe0f Pickleball \u6bcf\u65e5\u68c0\u67e5: \u672a\u80fd\u8f7d\u5165 {target_date} \u7684\u65f6\u6bb5\uff08\u9884\u8ba2\u7a97\u53e3\u53ef\u80fd\u5c1a\u672a\u5f00\u653e\uff09\u3002"
                f"\n\u8bf7\u68c0\u67e5\u662f\u5426\u5728 12:00 PT \u4e4b\u540e\u8fd0\u884c\u3002"
                f"\n(projects/pickleball/daily_check.py)"
            )
        return 2
    except Exception as e:
        log(f"scrape failed: {e}")
        traceback.print_exc()
        if not dry_run:
            notify_human(
                f"\u26a0\ufe0f Pickleball \u6bcf\u65e5\u68c0\u67e5\u5931\u8d25: {e}\n(projects/pickleball/daily_check.py)"
            )
        return 1

    if dry_run:
        log("DRY_RUN=1, skipping Telegram send")
        return 0

    # Send notifications
    if booking_result:
        # Booking was attempted — send booking result
        notify_human(booking_result)
    elif open_slots:
        # Non-booking day with open slots — notify
        notify_human(report)
    else:
        # Nothing open, non-booking day — stay silent
        log("no open slots; skipping notification")

    return 0


if __name__ == "__main__":
    sys.exit(main())
