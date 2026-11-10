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
    city TEXT NOT NULL DEFAULT '',
    avatar TEXT NOT NULL DEFAULT '',     -- photo filename in uploads/, '' = initials
    verified INTEGER NOT NULL DEFAULT 0, -- business owner verified by an admin
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
CREATE TABLE IF NOT EXISTS favorites (
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    seen_at TEXT NOT NULL DEFAULT '',    -- last time she opened the business page
    PRIMARY KEY (uid, business_id)
);
CREATE INDEX IF NOT EXISTS favorites_business ON favorites(business_id);
CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    selfie TEXT NOT NULL DEFAULT '',     -- file in private/, deleted once decided
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / approved / rejected
    note TEXT NOT NULL DEFAULT '',       -- reason shown to the user when rejected
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS verifications_status ON verifications(status, id);
"""


def data_dir() -> str:
    return os.environ.get("NAILS_DATA", "data")


def uploads_dir() -> str:
    return os.path.join(data_dir(), "uploads")


def private_dir() -> str:
    """Files that are never served publicly (verification selfies)."""
    return os.path.join(data_dir(), "private")


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
    os.makedirs(private_dir(), exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        _add_missing_columns(conn, "users", {
            "city": "TEXT NOT NULL DEFAULT ''",
            "avatar": "TEXT NOT NULL DEFAULT ''",
            "verified": "INTEGER NOT NULL DEFAULT 0",
            "terms_version": "TEXT NOT NULL DEFAULT ''",    # which terms she agreed to, and when
            "terms_accepted_at": "TEXT NOT NULL DEFAULT ''",
        })
        _add_missing_columns(conn, "businesses", {
            # when photos were last added; '' for older rows (= nothing new)
            "photos_updated_at": "TEXT NOT NULL DEFAULT ''",
            "instagram": "TEXT NOT NULL DEFAULT ''",   # username, without @
            # exact address (address = the composed display line)
            "street": "TEXT NOT NULL DEFAULT ''",
            "house_number": "TEXT NOT NULL DEFAULT ''",
            "apartment": "TEXT NOT NULL DEFAULT ''",
            "entrance": "TEXT NOT NULL DEFAULT ''",
            # owner confirmed the photos are her own work and she may publish them
            "rights_confirmed_at": "TEXT NOT NULL DEFAULT ''",
        })


def _add_missing_columns(conn, table: str, columns: dict[str, str]) -> None:
    """Upgrade databases created by older versions."""
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
