"""אחסון SQLite: מנויים להתראות, היסטוריית עסקאות ומצב האסטרטגיה."""
import json
import os
import sqlite3
from contextlib import closing


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def _conn(self):
        return closing(sqlite3.connect(self.path))

    def _exec(self, sql: str, args=()):
        with self._conn() as c, c:
            return c.execute(sql, args).fetchall()

    def set_subscription(self, chat_id: int, user_id: int, name: str, enabled: bool):
        self._exec("INSERT INTO subscribers (chat_id, user_id, name, enabled) VALUES (?,?,?,?) "
                   "ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled, name=excluded.name",
                   (chat_id, user_id, name, int(enabled)))

    def is_subscribed(self, chat_id: int) -> bool:
        rows = self._exec("SELECT enabled FROM subscribers WHERE chat_id=?", (chat_id,))
        return bool(rows and rows[0][0])

    def subscribers(self) -> list[int]:
        return [r[0] for r in self._exec("SELECT chat_id FROM subscribers WHERE enabled=1")]

    def save_trade(self, trade: dict):
        self._exec("INSERT OR REPLACE INTO trades (id, data) VALUES (?,?)", (trade["id"], json.dumps(trade)))

    def trades(self, limit: int = 50) -> list[dict]:
        rows = self._exec("SELECT data FROM trades ORDER BY id DESC LIMIT ?", (limit,))
        return [json.loads(r[0]) for r in rows]

    def get(self, key: str, default=None):
        rows = self._exec("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def put(self, key: str, value):
        self._exec("INSERT OR REPLACE INTO kv (key, value) VALUES (?,?)", (key, json.dumps(value)))


def trade_stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("status") != "open" and t.get("result_r") is not None]
    if not closed:
        return {"count": 0}
    wins = [t for t in closed if t["result_r"] > 0]
    return {
        "count": len(closed),
        "win_rate": round(100 * len(wins) / len(closed), 1),
        "total_r": round(sum(t["result_r"] for t in closed), 2),
        "avg_r": round(sum(t["result_r"] for t in closed) / len(closed), 2),
    }
