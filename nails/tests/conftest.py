import importlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

# A tiny valid-looking JPEG header is enough for the type check.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64

# Open every day 00:00-23:59 so "open now" never depends on when tests run.
ALWAYS_OPEN = {str(d): ["00:00", "23:59"] for d in range(7)}


def auth(uid="dana", contact="dana@example.com"):
    return {"Authorization": f"Bearer dev:{uid}:{contact}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAILS_DATA", str(tmp_path))
    monkeypatch.setenv("NAILS_DEV_AUTH", "1")
    for mod in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    main = importlib.import_module("app.main")
    with TestClient(main.app) as c:
        # default signed-in, registered user
        c.headers.update(auth())
        assert c.post("/api/me", json={"name": "דנה", "accepted_terms": True}).status_code == 200
        yield c


def register(client, uid, name="משתמשת"):
    h = auth(uid, f"{uid}@example.com")
    assert client.post("/api/me", json={"name": name, "accepted_terms": True}, headers=h).status_code == 200
    return h


def photos(n, data=JPEG):
    return [("photos", (f"p{i}.jpg", data, "image/jpeg")) for i in range(n)]


def make_business(client, lat=32.0853, lng=34.7818, n=5, headers=None, **over):
    form = {
        "name": "סטודיו ורוד",
        "phone": "050-123-4567",
        "city": "תל אביב",
        "services": "gel,build",
        "price_min": "100",
        "price_max": "300",
        "hours": json.dumps(ALWAYS_OPEN),
        "photos_rights": "true",
        "lat": str(lat),
        "lng": str(lng),
        **over,
    }
    return client.post("/api/businesses", data=form, files=photos(n), headers=headers)
