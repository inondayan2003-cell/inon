"""Sign-in: verifies Firebase Authentication ID tokens.

Firebase handles all sign-in methods (Google, Apple, email + password, phone SMS)
in the browser and gives the app an ID token. The server only checks that token.

Settings:
  firebase-config.json (next to README)
      The Firebase web-app config (public values, not secrets).
  FIREBASE_PROJECT_ID, FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN, FIREBASE_APP_ID
      Optional environment variables that override the file.
  NAILS_SIGNIN_METHODS=google,email
      Which sign-in methods the app offers (google, email, apple, phone).
      Default: google,email (both free). apple and phone cost money, so they are off.
  NAILS_DEV_AUTH=1
      Local development only: accept fake "dev:<id>:<email>" tokens so the app can be
      tried without a Firebase project. NEVER enable this on a real server.
"""
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

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


CONFIG_FILE = Path(__file__).resolve().parent.parent / "firebase-config.json"


def _file_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def firebase_config() -> dict:
    """File values, overridden by environment variables."""
    cfg = _file_config()
    for key, env in (("projectId", "FIREBASE_PROJECT_ID"), ("apiKey", "FIREBASE_API_KEY"),
                     ("authDomain", "FIREBASE_AUTH_DOMAIN"), ("appId", "FIREBASE_APP_ID")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    if cfg.get("projectId") and not cfg.get("authDomain"):
        cfg["authDomain"] = f"{cfg['projectId']}.firebaseapp.com"
    return cfg


def project_id() -> str:
    return firebase_config().get("projectId", "")


ALL_METHODS = ("google", "email", "apple", "phone")


def enabled_methods() -> list[str]:
    raw = os.environ.get("NAILS_SIGNIN_METHODS", "google,email")
    wanted = {m.strip().lower() for m in raw.split(",")}
    return [m for m in ALL_METHODS if m in wanted]


def admin_emails() -> set[str]:
    """Accounts that can open the admin screen (comma separated emails)."""
    return {e.strip().lower() for e in os.environ.get("NAILS_ADMIN_EMAILS", "").split(",") if e.strip()}


def dev_auth_enabled() -> bool:
    return os.environ.get("NAILS_DEV_AUTH") == "1"


def client_config() -> dict:
    """What the browser needs to start sign-in."""
    cfg = firebase_config()
    firebase = None
    if cfg.get("projectId") and cfg.get("apiKey"):
        firebase = {k: cfg.get(k, "") for k in ("apiKey", "authDomain", "projectId", "appId")}
    return {
        "firebase": firebase, "dev_auth": dev_auth_enabled(), "methods": enabled_methods(),
        # Shown on the contact page; empty until the owner sets them.
        "support_email": os.environ.get("NAILS_SUPPORT_EMAIL", ""),
        "support_phone": os.environ.get("NAILS_SUPPORT_PHONE", "0528326523"),
        # Who runs the service (shown on the contact page and in the terms); empty = hidden.
        "operator": {
            "name": os.environ.get("NAILS_OPERATOR_NAME", ""),
            "id": os.environ.get("NAILS_OPERATOR_ID", ""),          # עוסק / ח.פ. number
            "address": os.environ.get("NAILS_OPERATOR_ADDRESS", ""),
        },
    }


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
    ident = _verify_firebase(token)
    if ident.provider not in enabled_methods():
        raise AuthError("sign-in method is not enabled")
    return ident
