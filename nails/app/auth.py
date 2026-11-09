"""Sign-in: verifies Firebase Authentication ID tokens.

Firebase handles all sign-in methods (Google, Apple, email + password, phone SMS)
in the browser and gives the app an ID token. The server only checks that token.

Settings (environment variables):
  FIREBASE_PROJECT_ID, FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN, FIREBASE_APP_ID
      Firebase project config (these are public values, not secrets).
  NAILS_DEV_AUTH=1
      Local development only: accept fake "dev:<id>:<email>" tokens so the app can be
      tried without a Firebase project. NEVER enable this on a real server.
"""
import os
import threading
import time
from dataclasses import dataclass

import httpx
import jwt
from cryptography.x509 import load_pem_x509_certificate

CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)

PROVIDERS = {
    "google.com": "google",
    "apple.com": "apple",
    "password": "email",
    "phone": "phone",
    "dev": "dev",
}


class AuthError(Exception):
    pass


@dataclass
class Identity:
    uid: str
    provider: str
    email: str | None = None
    phone: str | None = None
    name: str | None = None


def project_id() -> str:
    return os.environ.get("FIREBASE_PROJECT_ID", "")


def dev_auth_enabled() -> bool:
    return os.environ.get("NAILS_DEV_AUTH") == "1"


def client_config() -> dict:
    """What the browser needs to start sign-in."""
    firebase = None
    if project_id() and os.environ.get("FIREBASE_API_KEY"):
        firebase = {
            "apiKey": os.environ["FIREBASE_API_KEY"],
            "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN", f"{project_id()}.firebaseapp.com"),
            "projectId": project_id(),
            "appId": os.environ.get("FIREBASE_APP_ID", ""),
        }
    return {"firebase": firebase, "dev_auth": dev_auth_enabled()}


# ---------- Google signing keys (cached) ----------

_keys: dict = {}
_keys_expire = 0.0
_keys_lock = threading.Lock()


def _signing_keys() -> dict:
    global _keys, _keys_expire
    with _keys_lock:
        if time.time() < _keys_expire and _keys:
            return _keys
        res = httpx.get(CERTS_URL, timeout=10)
        res.raise_for_status()
        max_age = 3600
        for part in res.headers.get("cache-control", "").split(","):
            part = part.strip()
            if part.startswith("max-age="):
                max_age = int(part.split("=", 1)[1])
        _keys = {
            kid: load_pem_x509_certificate(pem.encode()).public_key()
            for kid, pem in res.json().items()
        }
        _keys_expire = time.time() + max_age
        return _keys


def _verify_firebase(token: str) -> Identity:
    pid = project_id()
    if not pid:
        raise AuthError("sign-in is not configured")
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError as e:
        raise AuthError("bad token") from e
    key = _signing_keys().get(kid)
    if key is None:
        raise AuthError("unknown signing key")
    try:
        claims = jwt.decode(
            token, key, algorithms=["RS256"], audience=pid,
            issuer=f"https://securetoken.google.com/{pid}",
            options={"require": ["exp", "iat", "sub"]}, leeway=30,
        )
    except jwt.PyJWTError as e:
        raise AuthError("invalid or expired token") from e
    if not claims.get("sub"):
        raise AuthError("bad token")
    provider = (claims.get("firebase") or {}).get("sign_in_provider", "")
    return Identity(
        uid=claims["sub"],
        provider=PROVIDERS.get(provider, provider or "unknown"),
        email=claims.get("email"),
        phone=claims.get("phone_number"),
        name=claims.get("name"),
    )


def _verify_dev(token: str) -> Identity:
    # dev:<id>:<email or phone>
    parts = token.split(":", 2)
    if len(parts) != 3 or not parts[1]:
        raise AuthError("bad dev token")
    contact = parts[2]
    return Identity(
        uid=f"dev-{parts[1]}", provider="dev",
        email=contact if "@" in contact else None,
        phone=None if "@" in contact else contact or None,
    )


def verify(token: str) -> Identity:
    if not token:
        raise AuthError("missing token")
    if token.startswith("dev:"):
        if not dev_auth_enabled():
            raise AuthError("dev sign-in is disabled")
        return _verify_dev(token)
    return _verify_firebase(token)
