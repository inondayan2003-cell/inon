"""Fill a local server with demo businesses (placeholder images) for trying the app.

The server must run with NAILS_DEV_AUTH=1 (local development only).

Usage:  python scripts/seed_demo.py [http://localhost:8000]
Needs:  pip install pillow httpx
"""
import io
import json
import random
import sys

import httpx
from PIL import Image, ImageDraw

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

DEMO = [
    ("סטודיו ורוד", "תל אביב", 32.0790, 34.7806, "gel,art", "בניית ציפורניים ועיצובים בהתאמה אישית ✨"),
    ("נייל בר רמת גן", "רמת גן", 32.0684, 34.8248, "gel,build,fill", "מניקור ג'ל ובנייה, אווירה רגועה וקפה טוב"),
    ("ליה ציפורניים", "גבעתיים", 32.0722, 34.8125, "russian,gel", "מניקור רוסי מדויק, 6 שנות ניסיון"),
    ("ציפורני זהב", "חולון", 32.0158, 34.7874, "build,art,pedicure", "סטודיו פרטי, חניה בשפע"),
    ("סטודיו זוהר", "הרצליה", 32.1624, 34.8447, "gel,pedicure,regular", "לק ג'ל, פדיקור רפואי וטיפוח"),
    ("נוי ציפורניים", "ירושלים", 31.7683, 35.2137, "gel,build", "בנייה באקריל וג'ל, מחירים הוגנים"),
]

PALETTES = [
    [(245, 183, 200), (176, 58, 100)], [(250, 220, 190), (201, 164, 106)],
    [(200, 210, 245), (90, 100, 180)], [(240, 200, 230), (150, 60, 140)],
    [(255, 225, 225), (220, 80, 90)], [(220, 240, 230), (60, 140, 110)],
]


def photo(seed: int) -> bytes:
    rnd = random.Random(seed)
    top, bottom = rnd.choice(PALETTES)
    img = Image.new("RGB", (600, 800))
    d = ImageDraw.Draw(img)
    for y in range(800):
        t = y / 800
        d.line([(0, y), (600, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    for i in range(5):  # five "nails"
        x = 70 + i * 100
        h = rnd.randint(170, 240)
        color = tuple(rnd.randint(120, 255) for _ in range(3))
        d.rounded_rectangle([x, 300 - h // 3, x + 70, 300 + h], radius=35, fill=color, outline=(255, 255, 255), width=4)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


HOURS = json.dumps({**{str(d): ["09:00", "19:00"] for d in range(5)}, "5": ["09:00", "14:00"]})

for n, (name, city, lat, lng, services, desc) in enumerate(DEMO):
    files = [("photos", (f"{i}.jpg", photo(n * 10 + i), "image/jpeg")) for i in range(5)]
    owner = {"Authorization": f"Bearer dev:owner{n}:owner{n}@example.com"}
    httpx.post(f"{BASE}/api/me", json={"name": f"בעלת עסק {n}"}, headers=owner).raise_for_status()
    r = httpx.post(f"{BASE}/api/businesses", headers=owner, data={
        "name": name, "phone": f"05{n}1234567"[:10], "city": city, "description": desc,
        "services": services, "price_min": 80 + n * 20, "price_max": 250 + n * 40, "hours": HOURS, "lat": lat, "lng": lng,
    }, files=files)
    r.raise_for_status()
    print(f"{name}: id={r.json()['id']}")
