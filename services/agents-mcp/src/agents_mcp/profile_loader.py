"""Profile loader — scans ``profiles/<name>/profile.md`` files and keeps the
``profile_registry`` table in sync with what's on disk.

The registry table is a discovery cache: it lets the daemon list Profiles and
look one up by name without re-walking the filesystem. The Profile content
itself (system prompt, capability list) lives on disk and is re-read at
session-creation time, so editing a profile.md takes effect on the next
session that uses it without requiring a daemon restart.

Hashing keeps rescans cheap: we sha256 the file content and only re-upsert
when the hash changed. Unchanged files yield ``"unchanged"`` so callers can
report scan results meaningfully.

See: projects/agent-hub/design/agent-orchestration-v1-2026-05-02.md (§2.1).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from agents_mcp.adapters.base import Profile, ProfileParseError

logger = logging.getLogger(__name__)


# Frontmatter delimiter. Standard Jekyll / static-site convention; widely
# understood and matches Claude Code's .claude/agents/<name>.md format.
_DELIM = "---"


@dataclass
class _ParsedFile:
    """Internal: result of parsing a profile.md from raw text. Not exposed."""

    description: str
    runner_type: str
    system_prompt: str
    mcp_servers: tuple[str, ...]
    skills: tuple[str, ...]
    orchestration_tools: bool


def _parse_profile_text(text: str, source_path: str) -> _ParsedFile:
    """Parse a profile.md's text into its frontmatter + body.

    Strict-ish: the file must START with ``---\\n`` and the frontmatter must
    close with another ``---`` on its own line. Anything else raises
    :class:`ProfileParseError`. We intentionally don't try to recover from
    malformed frontmatter — silent acceptance hides typos.
    """
    if not text.startswith(_DELIM):
        raise ProfileParseError(
            source_path,
            f"missing opening frontmatter delimiter '{_DELIM}' on line 1",
        )

    # Strip the opening delimiter line, then find the closing one.
    rest = text[len(_DELIM):]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    else:
        # Opening delimiter wasn't followed by a newline — definitely malformed.
        raise ProfileParseError(
            source_path,
            f"opening '{_DELIM}' must be followed by a newline",
        )

    # Find the closing delimiter — a line that is exactly "---".
    # Search line-by-line so we don't accidentally match "---" inside YAML.
    lines = rest.split("\n")
    close_idx: Optional[int] = None
    for i, line in enumerate(lines):
        # tolerate trailing whitespace / CR
        if line.rstrip("\r ").strip() == _DELIM:
            close_idx = i
            break
    if close_idx is None:
        raise ProfileParseError(
            source_path,
            f"missing closing frontmatter delimiter '{_DELIM}'",
        )

    fm_text = "\n".join(lines[:close_idx])
    body = "\n".join(lines[close_idx + 1:]).lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ProfileParseError(source_path, f"frontmatter YAML error: {exc}")

    if not isinstance(fm, dict):
        raise ProfileParseError(
            source_path,
            f"frontmatter must be a YAML mapping, got {type(fm).__name__}",
        )

    # Required fields.
    for required in ("description", "runner_type"):
        if required not in fm:
            raise ProfileParseError(
                source_path, f"frontmatter missing required field '{required}'"
            )
        if not isinstance(fm[required], str) or not fm[required].strip():
            raise ProfileParseError(
                source_path,
                f"frontmatter field '{required}' must be a non-empty string",
            )

    description = fm["description"].strip()
    runner_type = fm["runner_type"].strip()

    mcp_servers = _coerce_str_list(fm.get("mcp_servers"), source_path, "mcp_servers")
    skills = _coerce_str_list(fm.get("skills"), source_path, "skills")

    orchestration_tools_raw = fm.get("orchestration_tools", False)
    if not isinstance(orchestration_tools_raw, bool):
        raise ProfileParseError(
            source_path,
            f"frontmatter field 'orchestration_tools' must be a boolean, "
            f"got {type(orchestration_tools_raw).__name__}",
        )

    if not body.strip():
        # An empty system prompt is almost certainly a mistake.
        raise ProfileParseError(
            source_path, "system prompt body is empty (nothing after frontmatter)"
        )

    return _ParsedFile(
        description=description,
        runner_type=runner_type,
        system_prompt=body,
        mcp_servers=mcp_servers,
        skills=skills,
        orchestration_tools=orchestration_tools_raw,
    )


def _coerce_str_list(
    value, source_path: str, field_name: str
) -> tuple[str, ...]:
    """Validate a frontmatter list-of-strings field. Missing/None → empty tuple."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProfileParseError(
            source_path,
            f"frontmatter field '{field_name}' must be a list, "
            f"got {type(value).__name__}",
        )
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise ProfileParseError(
                source_path,
                f"frontmatter '{field_name}'[{i}] must be a string, "
                f"got {type(item).__name__}",
            )
        item = item.strip()
        if not item:
            raise ProfileParseError(
                source_path,
                f"frontmatter '{field_name}'[{i}] is empty",
            )
        out.append(item)
    return tuple(out)


def load_profile(name: str, profiles_dir: Path) -> Profile:
    """Read ``profiles_dir/<name>/profile.md`` and return a Profile.

    Pure file IO + parsing — does not touch the store. Use this when you have
    a session about to start and want the latest Profile content.

    Raises:
        FileNotFoundError: profile.md doesn't exist.
        ProfileParseError: file present but malformed.
    """
    path = profiles_dir / name / "profile.md"
    text = path.read_text(encoding="utf-8")
    parsed = _parse_profile_text(text, str(path))
    file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Profile(
        name=name,
        description=parsed.description,
        runner_type=parsed.runner_type,
        system_prompt=parsed.system_prompt,
        file_path=str(path.resolve()),
        file_hash=file_hash,
        mcp_servers=parsed.mcp_servers,
        skills=parsed.skills,
        orchestration_tools=parsed.orchestration_tools,
    )


class ProfileLoader:
    """Walks ``profiles_dir`` and keeps the ``profile_registry`` table in sync.

    Construct with the top-level ``profiles/`` directory and an
    :class:`agents_mcp.store.AgentStore`. Call :meth:`scan` on daemon boot and
    on file-watch events.

    Hash-aware: re-running ``scan()`` over an unchanged tree is essentially
    free (no DB writes). This keeps ``loaded_at`` stable so we can tell
    "this profile was actually re-loaded" from "we just looked at it again".
    """

    def __init__(self, profiles_dir: Path, store):
        # store is typed loosely so we don't import AgentStore at module level
        # (avoids a circular import — store.py is heavy, this module is light).
        self.profiles_dir = Path(profiles_dir)
        self.store = store

    async def scan(self) -> list[tuple[str, str]]:
        """Discover every ``<name>/profile.md`` and reconcile the registry.

        Returns a list of ``(name, action)`` tuples in the order encountered.
        ``action`` is one of:

        - ``"loaded"`` — Profile was new (no row in registry).
        - ``"updated"`` — Profile existed and the file hash changed.
        - ``"unchanged"`` — Profile existed and the file hash matched.
        - ``"errored"`` — file failed to parse; it is logged and skipped.

        ``"errored"`` rows are NOT upserted; the previous registry entry (if
        any) stays untouched. This is intentional: a malformed edit shouldn't
        bork the running daemon's view of a Profile.
        """
        if not self.profiles_dir.exists():
            logger.warning(
                "Profile loader: profiles_dir does not exist: %s", self.profiles_dir
            )
            return []

        results: list[tuple[str, str]] = []
        # Iterate deterministically so test assertions are stable.
        for entry in sorted(self.profiles_dir.iterdir()):
            if not entry.is_dir():
                continue
            md_path = entry / "profile.md"
            if not md_path.is_file():
                continue
            name = entry.name
            try:
                action = await self._scan_one(name, md_path)
            except ProfileParseError as exc:
                logger.error("Profile loader: skipping %s: %s", name, exc.reason)
                results.append((name, "errored"))
                continue
            except Exception:
                logger.exception(
                    "Profile loader: unexpected error scanning %s", md_path
                )
                results.append((name, "errored"))
                continue
            results.append((name, action))
        return results

    async def _scan_one(self, name: str, md_path: Path) -> str:
        text = md_path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        existing = await self.store.get_profile_registry(name)
        if existing and existing.get("file_hash") == file_hash:
            return "unchanged"

        # Parse only on insert/update — saves work for the unchanged path.
        parsed = _parse_profile_text(text, str(md_path))
        await self.store.upsert_profile_registry(
            name=name,
            description=parsed.description,
            runner_type=parsed.runner_type,
            file_path=str(md_path.resolve()),
            file_hash=file_hash,
        )
        return "loaded" if existing is None else "updated"


__all__ = ["ProfileLoader", "load_profile", "Profile", "ProfileParseError"]
