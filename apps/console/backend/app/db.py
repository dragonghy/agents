"""Read-only async SQLite helpers.

Both databases are opened with `?mode=ro` URI flags, which physically prevents
any write attempts at the SQLite level. Combined with WAL on the writer side,
this lets the daemon write while we read concurrently without blocking.
"""

import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator


@asynccontextmanager
async def ro_connect(path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Open a SQLite connection in read-only URI mode."""
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    uri = f"file:{path}?mode=ro"
    async with aiosqlite.connect(uri, uri=True) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def fetch_all(path: Path, sql: str, params: tuple = ()) -> list[dict]:
    async with ro_connect(path) as db:
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def fetch_one(path: Path, sql: str, params: tuple = ()) -> dict | None:
    async with ro_connect(path) as db:
        async with db.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
