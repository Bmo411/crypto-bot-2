"""
TradingBot V5 — Async SQLite Database Manager

Manages the aiosqlite connection with WAL mode for concurrent reads.
Provides a context-manager interface for safe transactions.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import aiosqlite

log = logging.getLogger("storage.database")


class Database:
    """Async SQLite connection manager with WAL mode."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open the database connection and configure for production use."""
        # Ensure data directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self._db_path)

        # WAL mode — allows concurrent reads while writing
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # Performance tuning
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        await self._conn.execute("PRAGMA busy_timeout=5000")   # 5s wait on lock
        await self._conn.execute("PRAGMA foreign_keys=ON")

        # Row factory for dict-like access
        self._conn.row_factory = aiosqlite.Row

        log.info(f"Database connected: {self._db_path} (WAL mode)")

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            log.info("Database connection closed")

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the active connection. Raises if not connected."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        """Execute a single SQL statement with lock."""
        async with self._lock:
            cursor = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cursor

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """Execute a batch of SQL statements."""
        async with self._lock:
            await self.conn.executemany(sql, params_list)
            await self.conn.commit()

    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Fetch a single row as a dict."""
        cursor = await self.conn.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """Fetch all matching rows as dicts."""
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def insert(self, sql: str, params: tuple = ()) -> int:
        """Execute an INSERT and return the last row id."""
        async with self._lock:
            cursor = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cursor.lastrowid  # type: ignore
