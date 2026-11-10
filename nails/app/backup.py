"""Nightly backup of everything the app stores: the database and all photos.

    python -m app.backup             make a backup now (the server's timer runs this at 00:00)
    python -m app.backup --list      show the backups on this server

What it does:
1. Copies the database with SQLite's online-backup API (safe while the app is running)
   and checks the copy with PRAGMA integrity_check.
2. Packs the copy + data/uploads + data/private into data/backups/nails-YYYY-MM-DD_HHMM.tar.gz
3. Keeps the newest NAILS_BACKUP_KEEP archives on the server (default 7) and deletes older ones.
4. If NAILS_BACKUP_UPLOAD_URL is set (an Oracle Object Storage pre-authenticated "write" link
   that ends with /), uploads the archive there too, so a copy survives losing the server.
5. Writes data/backups/last.json, which the admin screen shows.

Restore: scripts/restore_backup.py
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from . import db

TZ = ZoneInfo("Asia/Jerusalem")


def backups_dir() -> Path:
    return Path(db.data_dir()) / "backups"


def status_file() -> Path:
    return backups_dir() / "last.json"


def _write_status(**info) -> dict:
    backups_dir().mkdir(parents=True, exist_ok=True)
    info["at"] = dt.datetime.now(TZ).isoformat(timespec="seconds")
    status_file().write_text(json.dumps(info, ensure_ascii=False))
    return info


def last_status() -> dict | None:
    try:
        return json.loads(status_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _copy_database(target: Path) -> None:
    src = sqlite3.connect(Path(db.data_dir()) / "nails.db")
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)                       # consistent snapshot, even mid-write
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"database copy failed the integrity check: {ok}")
    finally:
        dst.close()
        src.close()


def _prune(keep: int) -> list[str]:
    archives = sorted(backups_dir().glob("nails-*.tar.gz"))
    old = archives[:-keep] if keep > 0 else []
    for p in old:
        p.unlink()
    return [p.name for p in old]


def _upload(archive: Path, base_url: str) -> None:
    url = base_url.rstrip("/") + "/" + archive.name
    with archive.open("rb") as f:
        res = httpx.put(url, content=f, timeout=300, headers={"Content-Type": "application/gzip"})
    res.raise_for_status()


def run() -> dict:
    db.init()
    backups_dir().mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(TZ).strftime("%Y-%m-%d_%H%M")
    archive = backups_dir() / f"nails-{stamp}.tar.gz"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db_copy = Path(tmp) / "nails.db"
            _copy_database(db_copy)
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(db_copy, arcname="nails.db")
                for folder in ("uploads", "private"):
                    path = Path(db.data_dir()) / folder
                    if path.exists():
                        tar.add(path, arcname=folder)
        with tarfile.open(archive) as tar:           # make sure the archive reads back
            names = tar.getnames()
        photos = sum(1 for n in names if n.startswith("uploads/") and "." in n.rsplit("/", 1)[-1])
        uploaded = False
        url = os.environ.get("NAILS_BACKUP_UPLOAD_URL", "")
        if url:
            _upload(archive, url)
            uploaded = True
        removed = _prune(int(os.environ.get("NAILS_BACKUP_KEEP", "7")))
        return _write_status(ok=True, file=archive.name, size=archive.stat().st_size, photos=photos,
                             offsite=uploaded, removed=removed)
    except Exception as e:  # recorded so the admin screen shows the failure
        archive.unlink(missing_ok=True)
        _write_status(ok=False, error=f"{type(e).__name__}: {e}")
        raise


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for p in sorted(backups_dir().glob("nails-*.tar.gz")):
            print(f"{p.name}  {p.stat().st_size / 1024 / 1024:.1f} MB")
        return 0
    try:
        info = run()
    except Exception as e:
        print(f"BACKUP FAILED: {e}", file=sys.stderr)
        return 1
    print(f"backup ok: {info['file']} ({info['size'] / 1024 / 1024:.1f} MB, {info['photos']} photos,"
          f" offsite={'yes' if info['offsite'] else 'no'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
