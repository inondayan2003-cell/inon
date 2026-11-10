"""Restore Nails from a backup archive.

    sudo systemctl stop nails            # stop the app first
    python scripts/restore_backup.py data/backups/nails-2026-11-10_0000.tar.gz
    sudo systemctl start nails

The current data folder is kept as data.before-restore-<time>, so nothing is lost by restoring.
Options: --data DIR (default: $NAILS_DATA or ./data)
"""
import argparse
import datetime as dt
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path


def restore(archive: Path, data: Path) -> Path | None:
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        if "nails.db" not in names:
            raise SystemExit("this file is not a Nails backup (no nails.db inside)")
        staging = data.parent / f".restore-{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        tar.extractall(staging, filter="data")      # refuses absolute paths and ../ tricks
    ok = sqlite3.connect(staging / "nails.db").execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        shutil.rmtree(staging)
        raise SystemExit(f"the database in the backup is damaged: {ok}")
    kept = None
    if data.exists():
        kept = data.parent / f"{data.name}.before-restore-{dt.datetime.now():%Y%m%d-%H%M%S}"
        data.rename(kept)
    staging.rename(data)
    if kept and (kept / "backups").exists():          # keep the backup history in place
        shutil.move(str(kept / "backups"), str(data / "backups"))
    return kept


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive", type=Path)
    ap.add_argument("--data", type=Path, default=Path(os.environ.get("NAILS_DATA", "data")))
    a = ap.parse_args()
    kept = restore(a.archive.resolve(), a.data.resolve())
    print(f"restored {a.archive.name} into {a.data}")
    if kept:
        print(f"the previous data was kept in {kept}")


if __name__ == "__main__":
    sys.exit(main())
