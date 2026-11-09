"""SQLite storage: users, businesses and their photos."""
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,         -- Firebase user id
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    provider TEXT NOT NULL,       -- google / apple / email / phone
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    owner_uid TEXT NOT NULL REFERENCES users(uid),
    name TEXT NOT NULL,
    phone TEXT NOT NULL,          -- normalized, e.g. 0501234567
    city TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    services TEXT NOT NULL DEFAULT '',   -- comma separated service keys
    price_min INTEGER NOT NULL DEFAULT 0,   -- price range in ILS
    price_max INTEGER NOT NULL DEFAULT 0,
    hours TEXT NOT NULL DEFAULT '{}',    -- JSON: {"0": ["09:00", "19:00"], ...}, 0 = Sunday
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    whatsapp_clicks INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS businesses_geo ON businesses(lat, lng);
CREATE INDEX IF NOT EXISTS businesses_owner ON businesses(owner_uid);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS photos_business ON photos(business_id, position);
"""


def data_dir() -> str:
    return os.environ.get("NAILS_DATA", "data")


def uploads_dir() -> str:
    return os.path.join(data_dir(), "uploads")


@contextmanager
def connect():
    os.makedirs(data_dir(), exist_ok=True)
    conn = sqlite3.connect(os.path.join(data_dir(), "nails.db"), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init() -> None:
    os.makedirs(uploads_dir(), exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
