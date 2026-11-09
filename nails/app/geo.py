"""Distance helpers and phone/WhatsApp formatting."""
import math
import re

EARTH_KM = 6371.0


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """Cheap pre-filter for SQL: (min_lat, max_lat, min_lng, max_lng)."""
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def normalize_phone(raw: str) -> str | None:
    """Israeli phone -> local form '05XXXXXXXX' / '0XXXXXXXX'. None if invalid."""
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+972"):
        digits = "0" + digits[4:]
    elif digits.startswith("972"):
        digits = "0" + digits[3:]
    if re.fullmatch(r"0\d{8,9}", digits):
        return digits
    return None


def whatsapp_number(phone: str) -> str:
    """'0501234567' -> '972501234567' (format wa.me expects)."""
    return "972" + phone[1:]
