"""
Zero-token ephemeral key-value memory bus backed by SQLite WAL mode.
"""

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class SwarmBus:
    """
    Zero-token high-performance ephemeral memory bus for swarm inter-agent state.
    Uses SQLite WAL (Write-Ahead Logging) mode for concurrent micro-worker access.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            db_path = Path.home() / ".swarm_memory.db"
        self.db_path = Path(db_path)
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Initialize tables and enable WAL mode for high concurrency."""
        cursor = self.conn.cursor()
        if self.db_path != Path(":memory:"):
            cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ephemeral_bus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL DEFAULT 'default',
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                worker_id TEXT,
                created_at REAL NOT NULL
            );
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bus_channel_key 
            ON ephemeral_bus(channel, key);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bus_worker 
            ON ephemeral_bus(worker_id);
        """)
        self.conn.commit()

    def publish(
        self,
        key: str,
        value: str,
        channel: str = "default",
        worker_id: Optional[str] = None,
    ) -> int:
        """
        Publish a key-value record to a channel on the bus.
        Returns the inserted record ID.
        """
        cursor = self.conn.cursor()
        now = time.time()
        cursor.execute(
            """
            INSERT INTO ephemeral_bus (channel, key, value, worker_id, created_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (channel, key, value, worker_id, now),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get(self, key: str, channel: str = "default") -> Optional[str]:
        """
        Get the most recent value for a given key within a channel.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT value FROM ephemeral_bus
            WHERE channel = ? AND key = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1;
            """,
            (channel, key),
        )
        row = cursor.fetchone()
        return row["value"] if row else None

    def query(
        self,
        channel: Optional[str] = None,
        worker_id: Optional[str] = None,
        key: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query bus entries filtered by channel, worker_id, or key.
        """
        cursor = self.conn.cursor()
        sql = "SELECT id, channel, key, value, worker_id, created_at FROM ephemeral_bus WHERE 1=1"
        params: List[Any] = []

        if channel:
            sql += " AND channel = ?"
            params.append(channel)
        if worker_id:
            sql += " AND worker_id = ?"
            params.append(worker_id)
        if key:
            sql += " AND key = ?"
            params.append(key)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def clear(self, channel: Optional[str] = None) -> int:
        """
        Clear records from the bus. If channel is specified, clear only that channel.
        """
        cursor = self.conn.cursor()
        if channel:
            cursor.execute("DELETE FROM ephemeral_bus WHERE channel = ?;", (channel,))
        else:
            cursor.execute("DELETE FROM ephemeral_bus;")
        count = cursor.rowcount
        self.conn.commit()
        return count

    def close(self) -> None:
        """Close the SQLite database connection."""
        if self.conn:
            self.conn.close()
