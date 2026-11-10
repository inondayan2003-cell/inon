import io
import tarfile
from pathlib import Path

import pytest

from .conftest import make_business, register


@pytest.fixture
def data(client, tmp_path):
    make_business(client, name="עסק לגיבוי")
    return tmp_path


def test_backup_contains_database_and_photos(client, data):
    from app import backup
    info = backup.run()
    assert info["ok"] and info["photos"] == 5 and info["offsite"] is False
    archive = data / "backups" / info["file"]
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "nails.db" in names and sum(n.startswith("uploads/") for n in names) >= 5


def test_restore_round_trip(client, data):
    from app import backup
    archive = data / "backups" / backup.run()["file"]
    bid = client.get("/api/businesses").json()[0]["id"]
    client.delete(f"/api/businesses/{bid}")                       # "something happened"
    assert client.get("/api/businesses").json() == []

    import importlib.util
    spec = importlib.util.spec_from_file_location("restore", Path(__file__).parent.parent / "scripts" / "restore_backup.py")
    restore = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restore)
    kept = restore.restore(archive, data)
    assert kept and kept.exists()                                  # old data kept aside
    names = [b["name"] for b in client.get("/api/businesses").json()]
    assert names == ["עסק לגיבוי"]
    photo = client.get("/api/businesses").json()[0]["photos"][0]["url"]
    assert client.get(photo).status_code == 200                    # photos are back too
    assert (data / "backups" / archive.name).exists()              # history still there


def test_keeps_only_the_newest(client, data, monkeypatch):
    from app import backup
    monkeypatch.setenv("NAILS_BACKUP_KEEP", "2")
    for i in range(4):
        (data / "backups").mkdir(exist_ok=True)
        (data / "backups" / f"nails-2026-01-0{i + 1}_0000.tar.gz").write_bytes(b"old")
    backup.run()
    left = sorted(p.name for p in (data / "backups").glob("nails-*.tar.gz"))
    assert len(left) == 2 and left[0] == "nails-2026-01-04_0000.tar.gz"


def test_offsite_upload(client, data, monkeypatch):
    from app import backup
    sent = {}

    class Ok:
        def raise_for_status(self): pass

    def fake_put(url, content, **kw):
        sent["url"], sent["size"] = url, len(content.read())
        return Ok()
    monkeypatch.setattr(backup.httpx, "put", fake_put)
    monkeypatch.setenv("NAILS_BACKUP_UPLOAD_URL", "https://objectstorage.example/p/TOKEN/o/")
    info = backup.run()
    assert info["offsite"] and sent["url"].endswith("/o/" + info["file"]) and sent["size"] > 0


def test_failure_is_recorded(client, data, monkeypatch):
    from app import backup

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(backup, "_copy_database", broken)
    with pytest.raises(OSError):
        backup.run()
    assert backup.last_status()["ok"] is False and "disk full" in backup.last_status()["error"]


def test_admin_sees_last_backup(client, data, monkeypatch):
    from app import backup
    monkeypatch.setenv("NAILS_ADMIN_EMAILS", "boss@example.com")
    boss = register(client, "boss")
    assert client.get("/api/admin/summary", headers=boss).json()["backup"] is None
    backup.run()
    last = client.get("/api/admin/summary", headers=boss).json()["backup"]
    assert last["ok"] and last["file"].startswith("nails-")
