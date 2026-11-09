import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient

# A tiny valid-looking JPEG header is enough for the type check.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAILS_DATA", str(tmp_path))
    for mod in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[mod]
    main = importlib.import_module("app.main")
    with TestClient(main.app) as c:
        yield c


def photos(n, data=JPEG):
    return [("photos", (f"p{i}.jpg", data, "image/jpeg")) for i in range(n)]


def make_business(client, lat=32.0853, lng=34.7818, n=5, **over):
    form = {
        "name": "סטודיו ורוד",
        "phone": "050-123-4567",
        "city": "תל אביב",
        "services": "gel,build",
        "price_min": "100",
        "price_max": "300",
        "lat": str(lat),
        "lng": str(lng),
        **over,
    }
    return client.post("/api/businesses", data=form, files=photos(n))
