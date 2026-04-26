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
# and trigger the booking flow for it. Returns a diagnostic dict either way so
# the caller can log exactly what the page looked like and which strategy fired.
#
# IMPORTANT: in CourtReserve's agenda/list view, clicking the wrapping
# `.k-event[data-uid]` element is a no-op — the actual booking trigger is the
# inner "Reserve" anchor/button. We try several entry points so the same code
# works whether the scheduler is rendered as a grid or as an agenda list.
_CLICK_SLOT_JS = r"""
(params) => {
    const { targetMs, targetHour, targetMin } = params;
    const diag = { success: false, attempted: [] };

    const scheduler = document.querySelector("[data-role='scheduler']");
    if (!scheduler) { diag.error = 'no scheduler'; return diag; }

    const $el = (typeof jQuery !== 'undefined') ? jQuery(scheduler) : null;
    const widget = $el ? $el.data('kendoScheduler') : null;
    if (!widget) { diag.error = 'no kendo widget'; return diag; }

    try { diag.viewName = widget.view() && widget.view().name; } catch (e) {}

    // Helper: dispatch a full mouse-event sequence (mousedown→mouseup→click)
    // so handlers bound at pointerdown still fire.
    const fireMouseSequence = (el) => {
        const rect = el.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const opts = { bubbles: true, cancelable: true, clientX: cx, clientY: cy, button: 0, view: window };
        try { el.dispatchEvent(new MouseEvent('mousedown', opts)); } catch (e) {}
        try { el.dispatchEvent(new MouseEvent('mouseup', opts)); } catch (e) {}
        try { el.dispatchEvent(new MouseEvent('click', opts)); } catch (e) {}
    };

    // Helper: search a root element for an inner Reserve/Book trigger.
    const findReserveTrigger = (root) => {
        if (!root) return null;
        const candidates = root.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"]');
        for (const c of candidates) {
            const txt = ((c.textContent || c.value || '') + '').replace(/\s+/g, ' ').trim().toLowerCase();
            if (!txt) continue;
            if (txt === 'reserve' || txt === 'book' || txt === 'reserve now' ||
                txt.startsWith('reserve ') || txt.startsWith('book ')) {
                return c;
            }
        }
        return null;
    };

    // Helper: count visible Reserve-like triggers anywhere on the page (for diag).
    try {
        const all = document.querySelectorAll('a, button, [role="button"]');
        let n = 0;
        for (const c of all) {
            const txt = ((c.textContent || '') + '').replace(/\s+/g, ' ').trim().toLowerCase();
            if (txt === 'reserve' || txt === 'book') n++;
        }
        diag.reserveTriggerCount = n;
    } catch (e) {}

    // ---- Match the target slot by Unix-ms start timestamp via dataSource ----
    let items = [];
    try { items = widget.dataSource.data() || []; } catch (e) {}
    diag.dataSourceCount = items.length;

    const matches = [];
    for (const it of items) {
        const start = it && it.start ? it.start.getTime() : null;
        if (start === targetMs) {
            matches.push({ uid: it.uid, id: it.id || it.Id, model: it });
        }
    }
    diag.strategyAMatches = matches.length;

    const ampm = targetHour >= 12 ? 'PM' : 'AM';
    const disp = targetHour % 12 === 0 ? 12 : targetHour % 12;
    const label = `${disp}:${String(targetMin).padStart(2,'0')} ${ampm}`;
    diag.label = label;

    // Each strategy is a closure returning {success, detail?, error?}.
    const strategies = {
        'A1-reserve-anchor': () => {
            for (const m of matches) {
                if (!m.uid) continue;
                const wrapper = document.querySelector(`.k-event[data-uid="${m.uid}"]`);
                if (!wrapper) continue;
                const trigger = findReserveTrigger(wrapper);
                if (!trigger) continue;
                wrapper.scrollIntoView({ block: 'center' });
                trigger.scrollIntoView({ block: 'center' });
                trigger.click();
                fireMouseSequence(trigger);
                return { success: true, detail: { uid: m.uid } };
            }
            return { success: false, error: 'no .k-event wrapper with Reserve anchor' };
        },
        'A2-editEvent': () => {
            for (const m of matches) {
                if (!m.uid) continue;
                try {
                    widget.editEvent(m.uid);
                    return { success: true, detail: { uid: m.uid, via: 'editEvent' } };
                } catch (e) {}
                try {
                    widget.trigger('edit', { event: m.model });
                    return { success: true, detail: { uid: m.uid, via: 'trigger-edit' } };
                } catch (e) {}
            }
            return { success: false, error: 'editEvent/trigger-edit threw or no matches' };
        },
        'A3-mouse-sequence': () => {
            for (const m of matches) {
                if (!m.uid) continue;
                const el = document.querySelector(`.k-event[data-uid="${m.uid}"]`);
                if (!el) continue;
                el.scrollIntoView({ block: 'center' });
                fireMouseSequence(el);
                el.click();
                return { success: true, detail: { uid: m.uid } };
            }
            return { success: false, error: 'no .k-event wrapper for mouse sequence' };
        },
        'B-occurrenceByUid': () => {
            const events = Array.from(document.querySelectorAll('.k-event[data-uid]'));
            for (const el of events) {
                const uid = el.getAttribute('data-uid');
                if (!uid) continue;
                let occ = null;
                try { occ = widget.occurrenceByUid(uid); } catch (e) {}
                const start = occ && occ.start ? occ.start.getTime() : null;
                if (start !== targetMs) continue;
                const trigger = findReserveTrigger(el);
                if (trigger) {
                    trigger.scrollIntoView({ block: 'center' });
                    try { trigger.click(); fireMouseSequence(trigger); } catch (e) {}
                    return { success: true, detail: { uid, via: 'anchor' } };
                }
                el.scrollIntoView({ block: 'center' });
                fireMouseSequence(el);
                el.click();
                return { success: true, detail: { uid, via: 'mouse' } };
            }
            return { success: false, error: 'no occurrenceByUid match' };
        },
        'C-legacy-row': () => {
            const timeCells = document.querySelectorAll(
                '.k-scheduler-times td, .k-scheduler-timecolumn td'
            );
            let rowIdx = -1;
            for (let i = 0; i < timeCells.length; i++) {
                const txt = (timeCells[i].textContent || '').replace(/\s+/g, ' ').trim();
                if (txt.toUpperCase().includes(label.toUpperCase())) { rowIdx = i; break; }
            }
            if (rowIdx < 0) return { success: false, error: 'no time-column row' };
            const rows = document.querySelectorAll('.k-scheduler-content tr');
            if (rowIdx >= rows.length) return { success: false, error: 'rowIdx oob' };
            const cell = rows[rowIdx].querySelector('td');
            if (!cell) return { success: false, error: 'no content cell' };
            cell.scrollIntoView({ block: 'center' });
            fireMouseSequence(cell);
            cell.click();
            return { success: true, detail: { rowIdx } };
        },
        'D-agenda-reserve': () => {
            const reserveAnchors = Array.from(
                document.querySelectorAll('a, button, [role="button"]')
            ).filter((c) => {
                const t = ((c.textContent || '') + '').replace(/\s+/g, ' ').trim().toLowerCase();
                return t === 'reserve' || t === 'book';
            });
            for (const a of reserveAnchors) {
                let row = a;
                for (let i = 0; i < 6 && row && row !== document.body; i++) {
                    const txt = (row.textContent || '').replace(/\s+/g, ' ').toUpperCase();
                    if (txt.includes(label.toUpperCase())) {
                        a.scrollIntoView({ block: 'center' });
                        try { a.click(); fireMouseSequence(a); } catch (e) {}
                        return { success: true, detail: { hop: i } };
                    }
                    row = row.parentElement;
                }
            }
            return { success: false, error: 'no agenda Reserve anchor for label' };
        },
    };

    const which = (params && params.strategy) || null;
    if (!which) {
        // Backwards-compatible mode: try all strategies in order, return on first
        // that "succeeds" (which is what the old single-shot code did). The
        // caller's modal-poll will tell us if this actually worked.
        const order = ['A1-reserve-anchor', 'A2-editEvent', 'A3-mouse-sequence',
                       'B-occurrenceByUid', 'C-legacy-row', 'D-agenda-reserve'];
        for (const name of order) {
            const r = strategies[name]();
            diag.attempted.push({ strategy: name, ...r });
            if (r.success) {
                diag.success = true;
                diag.strategy = name;
                if (r.detail) Object.assign(diag, r.detail);
                return diag;
            }
        }
        diag.error = 'no strategy matched';
        return diag;
    }

    // Targeted mode: caller picks one strategy. This is what enables the
    // outer Python retry loop where each strategy is verified by checking
    // whether the booking modal appeared.
    if (!(which in strategies)) {
        diag.error = `unknown strategy: ${which}`;
        return diag;
    }
    const r = strategies[which]();
    diag.attempted.push({ strategy: which, ...r });
    if (r.success) {
        diag.success = true;
        diag.strategy = which;
        if (r.detail) Object.assign(diag, r.detail);
    } else {
        diag.error = r.error || 'strategy returned false';
    }
    return diag;
}
"""

# Order of strategies tried by ``book_slot_via_ui``. Each is verified by
# polling for the booking modal; if the modal doesn't appear, we fall through
# to the next strategy. See _CLICK_SLOT_JS for what each does.
_CLICK_STRATEGIES: tuple[str, ...] = (
    "A1-reserve-anchor",
    "A2-editEvent",
    "A3-mouse-sequence",
    "B-occurrenceByUid",
    "C-legacy-row",
    "D-agenda-reserve",
)


# JS helper: dump just enough page state to debug a no-modal failure offline.
# Returns (a) the kendoScheduler view name, (b) outerHTML of the scheduler
# subtree, (c) full document.documentElement.outerHTML. Caller writes (b)/(c)
# to logs and includes (a) in the diagnostic message.
_DUMP_DOM_JS = r"""
() => {
    const scheduler = document.querySelector("[data-role='scheduler']");
    let viewName = null;
    let schedulerHtml = null;
    try {
        const $el = (typeof jQuery !== 'undefined') ? jQuery(scheduler) : null;
        const widget = $el ? $el.data('kendoScheduler') : null;
        if (widget) viewName = widget.view() && widget.view().name;
        if (scheduler) schedulerHtml = scheduler.outerHTML;
    } catch (e) {}
    return {
        viewName,
        schedulerHtml,
        documentHtml: document.documentElement.outerHTML,
        url: location.href,
        title: document.title,
    };
}
"""


_MODAL_SELECTORS: tuple[str, ...] = (
    ".modal.show",
    ".k-window",
    "#bookingModal",
    "[class*='booking']",
    "[class*='reservation']",
)


def _modal_visible(page: Page, timeout_ms: int = 1000) -> str | None:
    """Return the first matching modal selector that is currently visible."""
    for sel in _MODAL_SELECTORS:
        try:
            if page.locator(sel).first.is_visible(timeout=timeout_ms):
                return sel
        except Exception:
            continue
    return None


def _wait_for_modal(page: Page, total_seconds: float = 5.0) -> str | None:
    """Poll for a booking modal up to total_seconds; return matching selector or None."""
    deadline = time.monotonic() + total_seconds
    while time.monotonic() < deadline:
        sel = _modal_visible(page, timeout_ms=200)
        if sel:
            return sel
        time.sleep(0.25)
    return None


def _dump_dom(page: Page, target_date: dt.date, reason: str) -> Path | None:
    """Save the page's full DOM and scheduler subtree for offline analysis.

    Filename mirrors the screenshot convention: ``dom-{YYYY-MM-DD}-{reason}-{HHMMSS}.html``.
    Returns the path on success, None on failure. Never raises.
    """
    ts = dt.datetime.now().strftime("%H%M%S")
    out = LOG_DIR / f"dom-{target_date.isoformat()}-{_slugify_reason(reason)}-{ts}.html"
    try:
        info = page.evaluate(_DUMP_DOM_JS) or {}
        view = info.get("viewName") or "unknown"
        html = (
            f"<!-- dump for {target_date} reason={reason} view={view} -->\n"
            f"<!-- url: {info.get('url')} -->\n"
            f"<!-- title: {info.get('title')} -->\n"
            f"<!-- ===== scheduler subtree ===== -->\n"
            f"{info.get('schedulerHtml') or '<!-- no scheduler -->'}\n"
            f"<!-- ===== full document ===== -->\n"
            f"{info.get('documentHtml') or ''}\n"
        )
        out.write_text(html, encoding="utf-8")
        log(f"dom dump saved [{reason}]: {out} (view={view})")
        return out
    except Exception as e:
        log(f"dom dump failed [{reason}]: {e}")
        return None


def book_slot_via_ui(
    page: Page, target_date: dt.date, best_slot: dict
) -> tuple[bool, str, list[Path]]:
    """Book a 1-hour slot by interacting with the CourtReserve scheduler UI.

    Flow:
    1. Try each click strategy in order; after each, poll for the booking
       modal. First strategy whose click produces a modal wins.
    2. If a modal appears, set duration to 60 min and click the book button.
    3. On total failure, dump screenshots + a DOM snapshot for offline debug.

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
        # Step 1: iterate strategies — each one's click is verified by polling
        # for the booking modal. PR #13 had the bug that "click returned" was
        # treated as success; now we require the modal to actually open.
        modal_sel: str | None = None
        last_diag: dict = {}
        per_strategy_wait = float(os.environ.get("CR_CLICK_WAIT_S", "3.0"))
        for strategy in _CLICK_STRATEGIES:
            diag = page.evaluate(
                _CLICK_SLOT_JS,
                {
                    "targetMs": target_start_ms,
                    "targetHour": start_hour,
                    "targetMin": start_min,
                    "strategy": strategy,
                },
            ) or {}
            last_diag = diag
            log(f"slot click [{strategy}]: {diag}")
            if not diag.get("success"):
                continue
            modal_sel = _wait_for_modal(page, total_seconds=per_strategy_wait)
            if modal_sel:
                log(f"modal opened via {strategy}: {modal_sel}")
                break
            log(f"strategy {strategy} clicked but no modal — trying next")

        if not modal_sel:
            # Python-side last-ditch: replicate the legacy text-match click on
            # any visible .k-event element with the time label embedded.
            log("all in-page strategies failed, trying Python fallback on .k-event")
            ss = _save_screenshot(page, target_date, "click-fail-primary")
            if ss:
                screenshots.append(ss)
            events = page.locator(".k-event").all()
            log(f"found {len(events)} .k-event elements")
            for ev in events:
                try:
                    text = (ev.text_content() or "").replace(" ", "")
                    if time_label.replace(" ", "") in text:
                        ev.click(timeout=3000)
                        log(f"clicked event via text match: {text[:60]}")
                        modal_sel = _wait_for_modal(page, total_seconds=per_strategy_wait)
                        if modal_sel:
                            break
                except Exception:
                    continue

        if not modal_sel:
            log("all click strategies failed; could not open booking modal")
            ss = _save_screenshot(page, target_date, "no-modal")
            if ss:
                screenshots.append(ss)
            dom = _dump_dom(page, target_date, "no-modal")
            err = last_diag.get("error") or "all strategies tried, no modal"
            attempts = last_diag.get("attempted") or []
            view = last_diag.get("viewName") or "?"
            extra_paths = f" dom={dom}" if dom else ""
            return (
                False,
                f"未弹出预定弹窗 [view={view} attempts={len(attempts)} last={err}]{extra_paths}",
                screenshots,
            )
        log(f"booking modal found: {modal_sel}")

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
                for sel in _MODAL_SELECTORS:
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
