import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth as auth_mod

from .conftest import auth


def test_everything_requires_sign_in(client):
    client.headers.pop("Authorization")
    assert client.get("/api/businesses").status_code == 401
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/config").status_code == 200   # needed to show the sign-in screen
    assert client.get("/api/services").status_code == 200


def test_new_user_must_register_first(client):
    h = auth("newbie", "+972501112222")
    assert client.get("/api/me", headers=h).status_code == 404
    assert client.get("/api/businesses", headers=h).status_code == 403
    r = client.post("/api/me", json={"name": "מיכל"}, headers=h)
    assert r.status_code == 200
    assert r.json()["phone"] == "+972501112222" and r.json()["provider"] == "dev"
    assert client.get("/api/me", headers=h).json()["name"] == "מיכל"
    assert client.get("/api/businesses", headers=h).status_code == 200


def test_name_is_required(client):
    assert client.post("/api/me", json={"name": "a"}, headers=auth("x", "x@y.z")).status_code == 422


def test_dev_tokens_rejected_when_dev_mode_off(client, monkeypatch):
    monkeypatch.delenv("NAILS_DEV_AUTH")
    assert client.get("/api/me").status_code == 401


# ---------- real Firebase token verification (with a test key) ----------

@pytest.fixture
def firebase(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "nails-test")
    monkeypatch.setattr(auth_mod, "_signing_keys", lambda: {"k1": key.public_key()})

    def make(**over):
        now = int(time.time())
        claims = {
            "iss": "https://securetoken.google.com/nails-test", "aud": "nails-test",
            "sub": "uid-123", "iat": now, "exp": now + 3600, "auth_time": now,
            "email": "noa@gmail.com", "name": "Noa", "firebase": {"sign_in_provider": "google.com"},
            **over,
        }
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})
    return make


def test_firebase_token_accepted(firebase):
    ident = auth_mod.verify(firebase())
    assert (ident.uid, ident.provider, ident.email, ident.name) == ("uid-123", "google", "noa@gmail.com", "Noa")
    assert auth_mod.verify(firebase(firebase={"sign_in_provider": "password"})).provider == "email"


def test_only_enabled_methods_accepted(firebase, monkeypatch):
    apple = firebase(firebase={"sign_in_provider": "apple.com"})
    phone = firebase(firebase={"sign_in_provider": "phone"}, phone_number="+972501234567")
    for token in (apple, phone):  # off by default (they cost money)
        with pytest.raises(auth_mod.AuthError):
            auth_mod.verify(token)
    monkeypatch.setenv("NAILS_SIGNIN_METHODS", "google,email,apple,phone")
    assert auth_mod.verify(apple).provider == "apple"
    assert auth_mod.verify(phone).phone == "+972501234567"


def test_config_lists_methods(client, monkeypatch):
    assert client.get("/api/config").json()["methods"] == ["google", "email"]
    monkeypatch.setenv("NAILS_SIGNIN_METHODS", "email, phone")
    assert client.get("/api/config").json()["methods"] == ["email", "phone"]


@pytest.mark.parametrize("over", [
    {"aud": "other-project"},
    {"iss": "https://securetoken.google.com/other-project"},
    {"exp": int(time.time()) - 3600},
    {"sub": ""},
])
def test_firebase_token_rejected(firebase, over):
    with pytest.raises(auth_mod.AuthError):
        auth_mod.verify(firebase(**over))


def test_firebase_token_with_unknown_key_rejected(firebase):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode({"sub": "x"}, other, algorithm="RS256", headers={"kid": "nope"})
    with pytest.raises(auth_mod.AuthError):
        auth_mod.verify(token)


def test_config_reads_project_file(client):
    fb = client.get("/api/config").json()["firebase"]
    assert fb["projectId"] == "nails-cb7e0"
    assert fb["authDomain"] == "nails-cb7e0.firebaseapp.com"
    assert fb["apiKey"] and fb["appId"]


def test_config_env_overrides_file(client, monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "nails-test")
    monkeypatch.setenv("FIREBASE_API_KEY", "public-key")
    monkeypatch.setenv("FIREBASE_AUTH_DOMAIN", "")
    fb = client.get("/api/config").json()["firebase"]
    assert (fb["projectId"], fb["apiKey"]) == ("nails-test", "public-key")


# ---------- profile: city and picture ----------

from .conftest import JPEG, auth as auth_header  # noqa: E402


def test_register_with_city(client):
    h = auth_header("maya", "maya@example.com")
    r = client.post("/api/me", json={"name": "מאיה", "city": "חיפה"}, headers=h).json()
    assert (r["name"], r["city"], r["avatar_url"]) == ("מאיה", "חיפה", None)
    r = client.post("/api/me", json={"name": "מאיה לוי", "city": ""}, headers=h).json()
    assert (r["name"], r["city"]) == ("מאיה לוי", "")


def test_avatar_upload_replace_remove(client, tmp_path):
    r = client.post("/api/me/avatar", files={"photo": ("a.jpg", JPEG, "image/jpeg")})
    first = r.json()["avatar_url"]
    assert r.status_code == 200 and first.startswith("/uploads/")
    assert client.get(first).content == JPEG
    second = client.post("/api/me/avatar", files={"photo": ("b.jpg", JPEG, "image/jpeg")}).json()["avatar_url"]
    assert second != first and client.get(first).status_code == 404   # old picture deleted
    assert client.get("/api/me").json()["avatar_url"] == second
    assert client.delete("/api/me/avatar").json()["avatar_url"] is None
    assert client.get(second).status_code == 404


def test_avatar_must_be_image(client):
    r = client.post("/api/me/avatar", files={"photo": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_old_users_table_gets_new_columns(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("NAILS_DATA", str(tmp_path))
    conn = sqlite3.connect(tmp_path / "nails.db")
    conn.execute("CREATE TABLE users (uid TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT, phone TEXT,"
                 " provider TEXT NOT NULL, created_at TEXT, last_login TEXT)")
    conn.close()
    from app import db
    db.init()
    with db.connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
    assert {"city", "avatar"} <= cols
