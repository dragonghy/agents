"""PR Monitor: auto-close tickets when their linked PR merges.

Polls GitHub (via `gh pr list`) every N minutes for merged PRs across one or
more configured repos. For each newly-merged PR:

1. Extracts `#NNN` references from the PR title + body (excluding the PR's
   own number).
2. For each referenced ID that exists in our ticket DB:
   - If ticket is already Done (status=0) → skip.
   - If ticket has any non-Done children → post a flagging comment, do not
     auto-close (requirement #3 of ticket #487).
   - Else → transition ticket to Done (status=0) and add a comment recording
     the PR URL, merge timestamp, and author.
3. Marks the PR as processed in a JSON state file so we never double-process
   it across daemon restarts.

Why polling and not a webhook? Simpler: no public endpoint, no secret
management, and `gh` is already authenticated on the daemon host. A 10-minute
delay on ticket close is acceptable for a bookkeeping feature.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# Matches `#NNN` — a bare ticket reference. GitHub also recognizes `GH-NNN`
# and `owner/repo#NNN` but we don't need those here.
_HASH_REF_RE = re.compile(r"#(\d{1,6})\b")

# Default: only look at PRs merged in the last 7 days. Anything older is
# considered "already reconciled" and we skip it on first boot to avoid
# posting comments on long-settled tickets.
_DEFAULT_LOOKBACK_DAYS = 7


# ─────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ─────────────────────────────────────────────────────────────────────────────


def extract_ticket_ids(
    title: str, body: str, pr_number: int
) -> list[int]:
    """Extract candidate ticket IDs from a PR's title and body.

    Strategy: find all `#NNN` references across title+body, dedupe, exclude
    the PR's own number. We return EVERY `#NNN` rather than filtering by
    closing keywords — the caller verifies against the ticket DB, and a
    reference that doesn't match a real ticket just gets dropped.

    Args:
        title: PR title.
        body:  PR body (may be None/empty).
        pr_number: This PR's own number (excluded from results).

    Returns:
        Sorted list of unique ticket IDs (ints) mentioned in the PR.
    """
    text = f"{title or ''}\n{body or ''}"
    ids: set[int] = set()
    for m in _HASH_REF_RE.finditer(text):
        n = int(m.group(1))
        if n != pr_number and n > 0:
            ids.add(n)
    return sorted(ids)


# ─────────────────────────────────────────────────────────────────────────────
# gh CLI wrapper
# ─────────────────────────────────────────────────────────────────────────────


def fetch_merged_prs(
    repo: str,
    since: datetime,
    *,
    limit: int = 50,
    gh_bin: str = "gh",
    timeout: int = 30,
) -> list[dict]:
    """Return list of merged PRs in `repo` merged on/after `since`.

    Each entry is the JSON object returned by `gh pr list --json`:
        number, title, body, mergedAt (ISO), author.login, url

    Raises:
        RuntimeError: if `gh` exits non-zero.
    """
    since_date = since.strftime("%Y-%m-%d")
    cmd = [
        gh_bin, "pr", "list",
        "--repo", repo,
        "--state", "merged",
        "--search", f"merged:>={since_date}",
        "--json", "number,title,body,mergedAt,author,url",
        "--limit", str(limit),
    ]
    logger.debug("pr_monitor: %s", " ".join(cmd))
    try:
        out = subprocess.check_output(
            cmd, text=True, timeout=timeout, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"gh pr list failed for {repo}: {e.stderr.strip() if e.stderr else e}"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(f"`gh` CLI not found (install GitHub CLI): {e}") from e
    data = json.loads(out)
    # Flatten author.login so the rest of the code doesn't have to deal with
    # the nested structure.
    for pr in data:
        author = pr.get("author") or {}
        pr["authorLogin"] = author.get("login") or "unknown"
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Processed-PR state (JSON file, keyed by "{repo}#{number}")
# ─────────────────────────────────────────────────────────────────────────────


class ProcessedPRStore:
    """Persists which (repo, pr_number) pairs we've already reconciled.

    Format on disk:
        {
          "dragonghy/agents#12": {
            "processed_at": "2026-04-23T14:15:00Z",
            "action": "closed|skipped|flagged",
            "ticket_ids": [483]
          },
          ...
        }
    """

    def __init__(self, path: str):
        self.path = path
        self._data: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(repo: str, pr_number: int) -> str:
        return f"{repo}#{pr_number}"

    def _load(self) -> None:
        try:
            with open(self.path) as f:
                self._data = json.load(f)
        except FileNotFoundError:
            self._data = {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("pr_monitor: state file unreadable (%s); starting fresh", e)
            self._data = {}

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def has(self, repo: str, pr_number: int) -> bool:
        return self._key(repo, pr_number) in self._data

    def mark(
        self,
        repo: str,
        pr_number: int,
        *,
        action: str,
        ticket_ids: list[int],
    ) -> None:
        self._data[self._key(repo, pr_number)] = {
            "processed_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "action": action,
            "ticket_ids": ticket_ids,
        }
        self._save()

    def seed_existing(self, prs: Iterable[dict], repo: str) -> int:
        """Mark all currently-known PRs as processed without acting on them.

        Used on first boot so we don't retroactively close tickets whose PRs
        merged long ago. Returns the count of PRs seeded.
        """
        seeded = 0
        for pr in prs:
            num = pr.get("number")
            if num is None:
                continue
            if self.has(repo, int(num)):
                continue
            self._data[self._key(repo, int(num))] = {
                "processed_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "action": "seeded",
                "ticket_ids": [],
            }
            seeded += 1
        if seeded:
            self._save()
        return seeded


# ─────────────────────────────────────────────────────────────────────────────
# Core processing
# ─────────────────────────────────────────────────────────────────────────────


def _format_merge_comment(pr: dict, repo: str) -> str:
    """Compose the ticket comment for an auto-close."""
    merged_at = pr.get("mergedAt", "")
    # Convert 2026-04-23T14:03:07Z → 2026-04-23 14:03 UTC for humans
    pretty = merged_at
    try:
        dt = datetime.strptime(merged_at, "%Y-%m-%dT%H:%M:%SZ")
        pretty = dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        pass
    return (
        f"## Auto-closed by PR merge\n"
        f"- **PR**: [{repo}#{pr['number']}]({pr.get('url', '')}) — "
        f"*{pr.get('title', '').strip()}*\n"
        f"- **Merged**: {pretty} by @{pr.get('authorLogin', 'unknown')}\n"
        f"- **Source**: agents-mcp pr_monitor\n"
    )


def _format_flagged_comment(pr: dict, repo: str, open_children: list[dict]) -> str:
    """Compose comment when we decline to auto-close because of open children."""
    child_lines = "\n".join(
        f"  - #{c['id']} ({c.get('headline', '')}) — status={c.get('status', '?')}"
        for c in open_children
    )
    return (
        f"## PR merged but auto-close skipped\n"
        f"- **PR**: [{repo}#{pr['number']}]({pr.get('url', '')}) merged, "
        f"but this ticket has open children:\n"
        f"{child_lines}\n"
        f"- **Action needed**: admin should close this manually once children "
        f"are done, or demote it to a milestone if that's the intent.\n"
        f"- **Source**: agents-mcp pr_monitor"
    )


async def process_merged_pr(
    client,
    pr: dict,
    repo: str,
    *,
    author_id: str = "pr-monitor",
) -> dict:
    """Reconcile one merged PR against linked tickets.

    Returns a summary dict:
        {
          "pr_number": int,
          "action": "closed" | "flagged" | "noop",
          "ticket_ids": [int, ...],  # IDs we acted on
          "details": [ {id, action, reason?}, ... ],
        }

    `client` is an SQLiteTaskClient. We use `get_ticket`, `get_children`,
    `update_ticket`, `add_comment`.
    """
    pr_number = int(pr["number"])
    linked = extract_ticket_ids(pr.get("title", ""), pr.get("body", ""), pr_number)

    summary: dict[str, Any] = {
        "pr_number": pr_number,
        "action": "noop",
        "ticket_ids": [],
        "details": [],
    }

    if not linked:
        return summary

    any_closed = False
    any_flagged = False

    for tid in linked:
        detail: dict[str, Any] = {"id": tid}
        try:
            ticket = await client.get_ticket(tid)
        except Exception as e:
            detail["action"] = "error"
            detail["reason"] = f"get_ticket failed: {e}"
            summary["details"].append(detail)
            continue

        if not ticket:
            # The #NNN reference doesn't match a real ticket — skip silently.
            detail["action"] = "skip"
            detail["reason"] = "ticket not found"
            summary["details"].append(detail)
            continue

        status = ticket.get("status")
        # Normalize: status may come back as int or string.
        try:
            status_int = int(status) if status is not None and status != "" else None
        except (ValueError, TypeError):
            status_int = None

        if status_int == 0:
            detail["action"] = "skip"
            detail["reason"] = "already done"
            summary["details"].append(detail)
            continue

        # Check for open children. A child counts as "open" if its status
        # is anything other than 0 (Done) or -1 (Archived).
        try:
            children = await client.get_children(tid)
        except Exception as e:
            children = []
            logger.warning("pr_monitor: get_children(%s) failed: %s", tid, e)

        open_children = []
        for c in children:
            try:
                cs = int(c.get("status")) if c.get("status") not in ("", None) else None
            except (ValueError, TypeError):
                cs = None
            if cs not in (0, -1):
                open_children.append(c)

        if open_children:
            try:
                await client.add_comment(
                    "ticket",
                    tid,
                    _format_flagged_comment(pr, repo, open_children),
                    author=author_id,
                )
            except Exception as e:
                logger.warning("pr_monitor: add_comment failed on #%s: %s", tid, e)
            detail["action"] = "flagged"
            detail["reason"] = f"{len(open_children)} open children"
            summary["details"].append(detail)
            summary["ticket_ids"].append(tid)
            any_flagged = True
            continue

        # Ready to auto-close.
        try:
            await client.update_ticket(tid, status=0)
            await client.add_comment(
                "ticket",
                tid,
                _format_merge_comment(pr, repo),
                author=author_id,
            )
        except Exception as e:
            detail["action"] = "error"
            detail["reason"] = f"close failed: {e}"
            summary["details"].append(detail)
            continue

        detail["action"] = "closed"
        summary["details"].append(detail)
        summary["ticket_ids"].append(tid)
        any_closed = True

    if any_closed:
        summary["action"] = "closed"
    elif any_flagged:
        summary["action"] = "flagged"

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch loop
# ─────────────────────────────────────────────────────────────────────────────


async def pr_monitor_cycle(
    client,
    store: ProcessedPRStore,
    repos: list[str],
    *,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    author_id: str = "pr-monitor",
    _fetch=fetch_merged_prs,
) -> dict:
    """Run one cycle across all configured repos. Returns summary."""
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    summary = {
        "cycle_time": time.time(),
        "repos": len(repos),
        "prs_seen": 0,
        "prs_processed": 0,
        "tickets_closed": 0,
        "tickets_flagged": 0,
        "errors": [],
    }

    for repo in repos:
        try:
            prs = _fetch(repo, since)
        except Exception as e:
            logger.warning("pr_monitor: fetch failed for %s: %s", repo, e)
            summary["errors"].append({"repo": repo, "error": str(e)})
            continue

        summary["prs_seen"] += len(prs)

        for pr in prs:
            num = int(pr.get("number", 0))
            if num == 0:
                continue
            if store.has(repo, num):
                continue

            try:
                pr_summary = await process_merged_pr(
                    client, pr, repo, author_id=author_id
                )
            except Exception as e:
                logger.exception("pr_monitor: process failed for %s#%s", repo, num)
                summary["errors"].append(
                    {"repo": repo, "pr": num, "error": str(e)}
                )
                continue

            store.mark(
                repo,
                num,
                action=pr_summary["action"],
                ticket_ids=pr_summary["ticket_ids"],
            )
            summary["prs_processed"] += 1
            if pr_summary["action"] == "closed":
                summary["tickets_closed"] += len(pr_summary["ticket_ids"])
                logger.info(
                    "pr_monitor: closed %d ticket(s) via %s#%d: %s",
                    len(pr_summary["ticket_ids"]),
                    repo, num, pr_summary["ticket_ids"],
                )
            elif pr_summary["action"] == "flagged":
                summary["tickets_flagged"] += len(pr_summary["ticket_ids"])
                logger.info(
                    "pr_monitor: flagged %d ticket(s) via %s#%d (open children)",
                    len(pr_summary["ticket_ids"]), repo, num,
                )

    return summary


async def pr_monitor_loop(
    client,
    store_path: str,
    repos: list[str],
    *,
    interval_seconds: int = 600,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    seed_on_start: bool = True,
    author_id: str = "pr-monitor",
    _fetch=fetch_merged_prs,
):
    """Run PR-monitor cycles continuously."""
    if not repos:
        logger.info("pr_monitor: no repos configured; loop will not run")
        return

    proc_store = ProcessedPRStore(store_path)

    # First-boot seed: mark existing merged PRs as processed so we don't
    # retroactively close tickets for old merges. Only seed if the state
    # file is empty.
    if seed_on_start and not proc_store._data:
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        total_seeded = 0
        for repo in repos:
            try:
                existing = _fetch(repo, since)
            except Exception as e:
                logger.warning("pr_monitor: seed fetch failed for %s: %s", repo, e)
                continue
            total_seeded += proc_store.seed_existing(existing, repo)
        logger.info(
            "pr_monitor: seeded %d existing merged PR(s) across %d repo(s)",
            total_seeded, len(repos),
        )

    logger.info(
        "pr_monitor: loop started (repos=%s, interval=%ds, lookback=%dd)",
        repos, interval_seconds, lookback_days,
    )

    while True:
        try:
            result = await pr_monitor_cycle(
                client, proc_store, repos,
                lookback_days=lookback_days,
                author_id=author_id,
                _fetch=_fetch,
            )
            if result["prs_processed"] or result["errors"]:
                logger.info(
                    "pr_monitor: cycle done — seen=%d processed=%d closed=%d "
                    "flagged=%d errors=%d",
                    result["prs_seen"], result["prs_processed"],
                    result["tickets_closed"], result["tickets_flagged"],
                    len(result["errors"]),
                )
        except Exception as e:
            logger.error("pr_monitor: cycle raised: %s", e)

        await asyncio.sleep(interval_seconds)
