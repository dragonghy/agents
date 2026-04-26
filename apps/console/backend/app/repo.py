"""Resolve paths into the harness repo (databases, briefs, agents.yaml)."""

import os
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Return the harness repo root.

    Resolution order:
    1. AGENTS_REPO_ROOT env var (set by Makefile / CI).
    2. Walk up from this file until a directory containing both
       `.agents-mcp.db` and `.agents-tasks.db` is found.

    Raises FileNotFoundError if neither resolves.
    """
    env = os.environ.get("AGENTS_REPO_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"AGENTS_REPO_ROOT does not exist: {p}")
        return p

    cur = Path(__file__).resolve()
    for parent in [cur, *cur.parents]:
        if (parent / ".agents-mcp.db").exists() and (parent / ".agents-tasks.db").exists():
            return parent

    raise FileNotFoundError(
        "Could not locate harness repo root. Set AGENTS_REPO_ROOT or run from within the repo."
    )


def mcp_db_path() -> Path:
    return repo_root() / ".agents-mcp.db"


def tasks_db_path() -> Path:
    return repo_root() / ".agents-tasks.db"


def briefs_dir() -> Path:
    return repo_root() / "briefs"


def agents_yaml_path() -> Path:
    return repo_root() / "agents.yaml"
