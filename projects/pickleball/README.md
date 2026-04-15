# Pickleball Daily Check

Scheduled job that checks CourtReserve (Lifetime Activities Sunnyvale, org 13233)
for pickleball availability 8 days out in the 7-9 PM window, and notifies Human
via the agents-mcp daemon Telegram outbound endpoint when something opens up.

Background: built on top of the POC in ticket #457. Ticket #477 tracks
productization.

## Files

- `daily_check.py` — main script. Reads `.env`, scrapes CourtReserve via Playwright,
  filters evening slots, POSTs to the daemon if available.
- `run_cron.sh` — wrapper used by cron. Sets a sane `PATH` and redirects
  output to `logs/cron-YYYY-MM-DD.log`.
- `.env.example` — template for credentials.
- `.env` — actual credentials (gitignored).
- `logs/` — cron stdout/stderr (gitignored).

## Setup

```bash
cd projects/pickleball
cp .env.example .env
# Fill in CR_USER / CR_PASS from 1Password "Sunnyvale pickleball court"
```

Playwright chromium must be installed (once):

```bash
python3 -m playwright install chromium
```

## Running manually

```bash
# Dry run: no Telegram send, just print the report
DRY_RUN=1 python3 daily_check.py

# Real run
python3 daily_check.py
```

## Cron install

macOS crontab entry (12:00 Pacific daily):

```
0 12 * * * /Users/huayang/code/agents/projects/pickleball/run_cron.sh
```

Install with `crontab -e` (append the line). Verify with `crontab -l`.

The wrapper script handles PATH, working dir, and log rotation per day.

## Behavior

- Only notifies when at least one court is available in the window — silent
  otherwise, to avoid cron noise.
- On scrape failure, sends an error notification (unless `DRY_RUN=1`).
- Log each run to `logs/cron.log`.

## Notes / gotchas

- CourtReserve sits behind Cloudflare; the POC found that headless Chromium gets
  blocked unless the webdriver flag is scrubbed and a real UA is set. Both are
  applied in `daily_check.py`. If the site upgrades detection, set `HEADLESS=0`
  and run under a user session (or xvfb).
- Residents can book up to 8 days out, and the day+8 window opens at 12:00 PT.
  Running `daily_check.py` *before* noon will fail with `TargetNotReached`
  because the scheduler only shows day+7 until then; that's intentional and
  triggers a warning notification rather than a silent "all booked".
  `CR_DAYS_AHEAD` defaults to 8.
- `/Date(unixms)/` in CourtReserve responses is UTC; we convert via
  `zoneinfo("America/Los_Angeles")` so DST transitions are correct.
