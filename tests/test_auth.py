import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from app.auth import validate_init_data

TOKEN = "123:ABC"


def _signed(fields: dict) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


def test_valid_and_tampered():
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 42, "first_name": "ענון"})}
    data = _signed(fields)
    assert validate_init_data(data, TOKEN)["id"] == 42
    assert validate_init_data(data.replace("42", "43"), TOKEN) is None
    assert validate_init_data(data, "999:XYZ") is None


def test_expired():
    fields = {"auth_date": str(int(time.time()) - 200000), "user": json.dumps({"id": 1})}
    assert validate_init_data(_signed(fields), TOKEN) is None
