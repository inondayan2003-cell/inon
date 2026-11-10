"""Address -> map position, using OpenStreetMap's free Nominatim service.

Nominatim's usage policy: at most 1 request per second, an identifying User-Agent,
and cache results. We look up one address when a business is saved, so traffic is tiny.
"""
import threading
import time

import httpx

URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "Nails-app/1.0 (nail salon finder, Israel)"}

_cache: dict[tuple, tuple[float, float] | None] = {}
_lock = threading.Lock()
_last_call = 0.0


def _query(params: dict) -> tuple[float, float] | None:
    global _last_call
    with _lock:  # respect 1 request / second
        wait = 1.0 - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        res = httpx.get(URL, params={**params, "format": "jsonv2", "limit": 1, "countrycodes": "il",
                                     "accept-language": "he"}, headers=HEADERS, timeout=10)
    res.raise_for_status()
    hits = res.json()
    if not hits:
        return None
    return float(hits[0]["lat"]), float(hits[0]["lon"])


def lookup(city: str, street: str, number: str) -> tuple[float, float] | None:
    """Position of 'street number, city' in Israel; None if not found.
    Raises httpx.HTTPError when the service can't be reached."""
    key = (city.strip(), street.strip(), number.strip())
    if key in _cache:
        return _cache[key]
    pos = _query({"street": f"{key[2]} {key[1]}".strip(), "city": key[0], "country": "Israel"})
    if pos is None and key[2]:  # house number unknown to the map: fall back to the street
        pos = _query({"street": key[1], "city": key[0], "country": "Israel"})
    _cache[key] = pos
    return pos
