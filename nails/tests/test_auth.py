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
    assert auth_mod.verify(firebase(firebase={"sign_in_provider": "apple.com"})).provider == "apple"
    assert auth_mod.verify(firebase(firebase={"sign_in_provider": "phone"}, phone_number="+972501234567")).phone == "+972501234567"


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


def test_config_exposes_firebase_settings(client, monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "nails-test")
    monkeypatch.setenv("FIREBASE_API_KEY", "public-key")
    cfg = client.get("/api/config").json()
    assert cfg["firebase"]["projectId"] == "nails-test"
    assert cfg["firebase"]["authDomain"] == "nails-test.firebaseapp.com"
