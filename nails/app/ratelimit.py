"""Small in-memory rate limits (one server process, so memory is enough).

limit(key, count, seconds) -> False when `key` already used `count` times in the last `seconds`.
once(key, seconds)          -> True only the first time in each window (for counting views/leads).
"""
import threading
import time
from collections import deque

_hits: dict[str, deque] = {}
_lock = threading.Lock()
_last_sweep = 0.0


def _sweep(now: float) -> None:
    """Forget old keys now and then so memory stays small."""
    global _last_sweep
    if now - _last_sweep < 300:
        return
    _last_sweep = now
    for k in [k for k, q in _hits.items() if not q or now - q[-1] > 86400]:
        del _hits[k]


def limit(key: str, count: int, seconds: float) -> bool:
    now = time.monotonic()
    with _lock:
        _sweep(now)
        q = _hits.setdefault(key, deque())
        while q and now - q[0] > seconds:
            q.popleft()
        if len(q) >= count:
            return False
        q.append(now)
        return True


def once(key: str, seconds: float) -> bool:
    return limit(key, 1, seconds)


def reset() -> None:
    with _lock:
        _hits.clear()
