"""Nails: find nail salons near you and contact them on WhatsApp."""
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import io

import httpx
from PIL import Image, ImageOps

from . import auth, backup, db, geocode, ratelimit
from .geo import bounding_box, distance_km, normalize_phone, whatsapp_number

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
TZ = ZoneInfo("Asia/Jerusalem")

MIN_PHOTOS = 5
MAX_PHOTOS = 12
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_RADIUS_KM = 100
MAX_PRICE = 5000

SERVICES = {
    "gel": "לק ג'ל",
    "build": "בניית ציפורניים",
    "fill": "מילוי",
    "regular": "לק רגיל",
    "art": "ציור ועיצובים",
    "pedicure": "פדיקור",
    "russian": "מניקור רוסי",
}

WHATSAPP_MESSAGE = "היי! הגעתי אלייך דרך אפליקציית Nails 💅 אשמח לשמוע פרטים ולקבוע תור"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    if auth.dev_auth_enabled():
        print("\n" + "!" * 70 + "\n  NAILS_DEV_AUTH=1: anyone can sign in as anyone. Local development only!\n"
              + "!" * 70 + "\n", flush=True)
    yield


app = FastAPI(title="Nails", lifespan=lifespan)


def _content_security_policy() -> str:
    """Only our own files, plus what Google sign-in (Firebase) needs. No trackers, no ads."""
    auth_domain = auth.firebase_config().get("authDomain", "")
    google = "https://www.gstatic.com https://apis.google.com"
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' {google}",
        "style-src 'self' 'unsafe-inline'",           # style attributes in the markup
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com"
        " https://www.googleapis.com",
        f"frame-src https://{auth_domain} https://accounts.google.com https://apis.google.com" if auth_domain
        else "frame-src https://accounts.google.com",
        "worker-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


MAX_BODY_BYTES = 60 * 1024 * 1024      # a whole business with 12 photos fits easily
TOO_MANY = "יותר מדי פעולות בזמן קצר. נסי שוב בעוד כמה דקות"


def _client_ip(request) -> str:
    return request.client.host if request.client else "?"


@app.middleware("http")
async def security_headers(request, call_next):
    from fastapi.responses import JSONResponse
    if request.url.path.startswith("/api/"):
        size = request.headers.get("content-length")
        if size and size.isdigit() and int(size) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "הקבצים גדולים מדי"}, status_code=413)
        if not ratelimit.limit(f"ip:{_client_ip(request)}", 600, 60):   # flood protection
            return JSONResponse({"detail": TOO_MANY}, status_code=429)
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "geolocation=(self), camera=(self), microphone=(), payment=(), usb=()")
    h.setdefault("X-Frame-Options", "DENY")
    if os.environ.get("NAILS_CSP", "on") != "off":   # escape hatch if a sign-in provider needs more
        h.setdefault("Content-Security-Policy", _content_security_policy())
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")         # personal data is never cached
    if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


# ---------- auth ----------

def identity(authorization: str = Header("")) -> auth.Identity:
    """Signed-in Firebase user (may not have finished registration yet)."""
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    try:
        return auth.verify(token)
    except auth.AuthError:
        raise HTTPException(401, "צריך להתחבר מחדש")


def current_user(ident: auth.Identity = Depends(identity)) -> dict:
    """Signed-in AND registered user."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE uid = ?", (ident.uid,)).fetchone()
    if row is None:
        raise HTTPException(403, "not_registered")
    return dict(row)


def _is_admin(user) -> bool:
    """Admin = an email in NAILS_ADMIN_EMAILS that Google confirmed (a password account
    opened with someone else's unconfirmed address never qualifies)."""
    return (bool(user["email"]) and bool(user["email_verified"])
            and user["email"].lower() in auth.admin_emails())


def _user_out(row, conn=None) -> dict:
    out = {k: row[k] for k in ("uid", "name", "email", "phone", "provider", "city")}
    out["avatar_url"] = f"/uploads/{row['avatar']}" if row["avatar"] else None
    out["verified"] = bool(row["verified"])
    out["is_admin"] = _is_admin(row)
    out["terms_current"] = row["terms_version"] == TERMS_VERSION
    out["verification"] = None
    if conn is not None:
        v = conn.execute(
            "SELECT status, note, created_at FROM verifications WHERE uid = ? ORDER BY id DESC LIMIT 1",
            (row["uid"],),
        ).fetchone()
        out["verification"] = dict(v) if v else None
    return out


def _get_user(conn, uid: str) -> dict:
    return _user_out(conn.execute("SELECT * FROM users WHERE uid = ?", (uid,)).fetchone(), conn)


def _throttle(user: dict, action: str, count: int, seconds: int) -> None:
    if not ratelimit.limit(f"{action}:{user['uid']}", count, seconds):
        raise HTTPException(429, TOO_MANY)


def admin_user(user: dict = Depends(current_user)) -> dict:
    if not _is_admin(user):
        raise HTTPException(403, "אין הרשאת ניהול")
    return user


@app.get("/api/config")
def config():
    return auth.client_config()


@app.get("/api/me")
def me(ident: auth.Identity = Depends(identity)):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE uid = ?", (ident.uid,)).fetchone()
        if row is None:
            # 404 tells the app to show the "what's your name" step.
            raise HTTPException(404, "not_registered")
        conn.execute("UPDATE users SET last_login = datetime('now'), email_verified = ? WHERE uid = ?",
                     (int(ident.email_verified), ident.uid))
        return _get_user(conn, ident.uid)


TERMS_VERSION = "2026-11"   # bump when the terms or privacy policy change materially


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    city: str = Field("", max_length=40)
    accepted_terms: bool = False   # required when the account is created


@app.post("/api/me")
def register(body: RegisterIn, ident: auth.Identity = Depends(identity)):
    """Create the account on first sign-in (or update name and city)."""
    if not ratelimit.limit(f"register:{ident.uid}", 30, 3600):
        raise HTTPException(429, TOO_MANY)
    with db.connect() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE uid = ?", (ident.uid,)).fetchone()
        if not exists and not body.accepted_terms:
            raise HTTPException(422, "כדי להירשם צריך לאשר את תנאי השימוש ומדיניות הפרטיות")
        conn.execute(
            "INSERT INTO users (uid, name, email, phone, provider, city) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(uid) DO UPDATE SET name = excluded.name, city = excluded.city,"
            " email = COALESCE(excluded.email, users.email),"
            " phone = COALESCE(excluded.phone, users.phone), last_login = datetime('now')",
            (ident.uid, body.name.strip(), ident.email, ident.phone, ident.provider, body.city.strip()),
        )
        conn.execute("UPDATE users SET email_verified = ? WHERE uid = ?", (int(ident.email_verified), ident.uid))
        if body.accepted_terms:
            conn.execute("UPDATE users SET terms_version = ?, terms_accepted_at = datetime('now') WHERE uid = ?",
                         (TERMS_VERSION, ident.uid))
        return _get_user(conn, ident.uid)


@app.delete("/api/me", status_code=204)
def delete_account(user: dict = Depends(current_user)):
    """Delete the account with everything it owns: businesses, their photos, the profile picture."""
    with db.connect() as conn:
        files = [r["filename"] for r in conn.execute(
            "SELECT p.filename FROM photos p JOIN businesses b ON b.id = p.business_id"
            " WHERE b.owner_uid = ?", (user["uid"],))]
        selfies = [r["selfie"] for r in conn.execute(
            "SELECT selfie FROM verifications WHERE uid = ? AND selfie != ''", (user["uid"],))]
        conn.execute("DELETE FROM verifications WHERE uid = ?", (user["uid"],))
        conn.execute("BEGIN")
        conn.execute("DELETE FROM businesses WHERE owner_uid = ?", (user["uid"],))  # photos cascade
        conn.execute("DELETE FROM users WHERE uid = ?", (user["uid"],))
        conn.execute("COMMIT")
    _delete_files(files + ([user["avatar"]] if user["avatar"] else []))
    _delete_files(selfies, db.private_dir())


@app.post("/api/me/avatar")
async def set_avatar(photo: UploadFile = File(...), user: dict = Depends(current_user)):
    """Profile picture (replaces the previous one)."""
    _throttle(user, "avatar", 20, 3600)
    [name] = await _save_photos([photo])
    with db.connect() as conn:
        conn.execute("UPDATE users SET avatar = ? WHERE uid = ?", (name, user["uid"]))
        out = _get_user(conn, user["uid"])
    if user["avatar"]:
        _delete_files([user["avatar"]])
    return out


@app.delete("/api/me/avatar")
def remove_avatar(user: dict = Depends(current_user)):
    with db.connect() as conn:
        conn.execute("UPDATE users SET avatar = '' WHERE uid = ?", (user["uid"],))
        out = _get_user(conn, user["uid"])
    if user["avatar"]:
        _delete_files([user["avatar"]])
    return out


# ---------- helpers ----------

def _services(raw: str) -> list[str]:
    keys = [s.strip() for s in raw.split(",") if s.strip()]
    bad = [k for k in keys if k not in SERVICES]
    if bad:
        raise HTTPException(422, f"שירות לא מוכר: {', '.join(bad)}")
    return list(dict.fromkeys(keys))


def _check_prices(price_min: int, price_max: int) -> None:
    if not (0 < price_min <= MAX_PRICE and 0 < price_max <= MAX_PRICE):
        raise HTTPException(422, f"המחירים צריכים להיות בין 1 ל-{MAX_PRICE} ₪")
    if price_min > price_max:
        raise HTTPException(422, "המחיר ההתחלתי גבוה מהמחיר המקסימלי")


_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _hours(raw) -> dict[str, list[str]]:
    """Validate opening hours: {"0".."6": ["HH:MM", "HH:MM"]}, 0 = Sunday. Missing day = closed."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except json.JSONDecodeError:
            raise HTTPException(422, "שעות פעילות לא תקינות")
    if not isinstance(raw, dict):
        raise HTTPException(422, "שעות פעילות לא תקינות")
    out: dict[str, list[str]] = {}
    for day, span in raw.items():
        if day not in {str(d) for d in range(7)}:
            raise HTTPException(422, "יום לא תקין בשעות הפעילות")
        if span is None:
            continue
        if (not isinstance(span, list) or len(span) != 2
                or not all(isinstance(t, str) and _TIME.match(t) for t in span)):
            raise HTTPException(422, "שעה לא תקינה בשעות הפעילות")
        if span[0] >= span[1]:
            raise HTTPException(422, "שעת הסגירה צריכה להיות אחרי שעת הפתיחה")
        out[day] = span
    if not out:
        raise HTTPException(422, "צריך לבחור לפחות יום פעילות אחד")
    return dict(sorted(out.items()))


def _open_now(hours: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ)
    span = hours.get(str((now.weekday() + 1) % 7))  # Python Monday=0 -> Sunday=0
    return bool(span) and span[0] <= now.strftime("%H:%M") < span[1]


def _instagram(raw: str) -> str:
    """Accepts @name, name or an instagram.com link; returns the username ('' = none)."""
    v = raw.strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?instagram\.com/([^/?#]+)", v, re.I)
    if m:
        v = m.group(1)
    v = v.lstrip("@").strip()
    if v and not re.fullmatch(r"[A-Za-z0-9._]{1,30}", v):
        raise HTTPException(422, "שם המשתמש באינסטגרם לא תקין")
    return v


def _address_line(street: str, number: str, apartment: str, entrance: str) -> str:
    """'הרצל 12, כניסה ב, דירה 4'"""
    line = f"{street} {number}".strip()
    if entrance:
        line += f", כניסה {entrance}"
    if apartment:
        line += f", דירה {apartment}"
    return line


def _locate(city: str, street: str, number: str) -> tuple[float, float]:
    """Map position of an address, or a clear error the owner can fix."""
    if not street or not number:
        raise HTTPException(422, "צריך למלא רחוב ומספר בית, או לבחור 'אני בעסק עכשיו'")
    try:
        pos = geocode.lookup(city, street, number)
    except httpx.HTTPError:
        raise HTTPException(503, "לא הצלחנו לבדוק את הכתובת כרגע. נסי שוב בעוד רגע")
    if pos is None:
        raise HTTPException(422, "לא מצאנו את הכתובת במפה. בדקי את שם העיר והרחוב")
    return pos


def _check_coords(lat: float, lng: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(422, "מיקום לא תקין")


def _image_ext(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


Image.MAX_IMAGE_PIXELS = 50_000_000     # refuse "decompression bomb" images
MAX_SIDE = 2048


def _clean_image(data: bytes) -> bytes:
    """Re-draw the photo as a fresh JPEG. This drops all hidden metadata (EXIF, including
    the GPS position phones store), and anything that isn't really an image fails here."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)          # keep the orientation the phone intended
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.getchannel("A"))
                im = bg
            else:
                im = im.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=86, optimize=True, progressive=True)
            return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(415, "הקובץ לא נראה כמו תמונה תקינה")


async def _save_photos(files: list[UploadFile], folder: str | None = None) -> list[str]:
    """Validate, clean and store uploaded images. Returns stored filenames."""
    saved: list[str] = []
    try:
        for f in files:
            data = await f.read(MAX_PHOTO_BYTES + 1)
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, "תמונה גדולה מדי (עד 10MB)")
            if _image_ext(data[:16]) is None:
                raise HTTPException(415, "אפשר להעלות רק תמונות JPG / PNG / WEBP")
            clean = _clean_image(data)
            name = f"{uuid.uuid4().hex}.jpg"
            with open(os.path.join(folder or db.uploads_dir(), name), "wb") as out:
                out.write(clean)
            saved.append(name)
    except BaseException:
        _delete_files(saved, folder)
        raise
    return saved


def _delete_files(names: list[str], folder: str | None = None) -> None:
    for n in names:
        try:
            os.remove(os.path.join(folder or db.uploads_dir(), n))
        except FileNotFoundError:
            pass


NOW = "strftime('%Y-%m-%d %H:%M:%f', 'now')"  # millisecond timestamps, so order is exact

# Every business row also carries whether its owner is verified.
BIZ_SELECT = ("SELECT *, (SELECT verified FROM users u WHERE u.uid = businesses.owner_uid)"
              " AS owner_verified FROM businesses")


def _get_business(conn, business_id: int):
    row = conn.execute(f"{BIZ_SELECT} WHERE id = ?", (business_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "העסק לא נמצא")
    return row


def _owned_business(conn, business_id: int, user: dict):
    row = _get_business(conn, business_id)
    if row["owner_uid"] != user["uid"]:
        raise HTTPException(403, "אין הרשאה לערוך את העסק הזה")
    return row


def _photos(conn, business_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, filename FROM photos WHERE business_id = ? ORDER BY position, id",
        (business_id,),
    ).fetchall()
    return [{"id": r["id"], "url": f"/uploads/{r['filename']}"} for r in rows]


def _public(row, photos: list[dict], dist: float | None = None) -> dict:
    hours = json.loads(row["hours"] or "{}")
    return {
        "id": row["id"],
        "name": row["name"],
        "phone": row["phone"],
        "city": row["city"],
        "address": row["address"],
        "street": row["street"],
        "house_number": row["house_number"],
        "apartment": row["apartment"],
        "entrance": row["entrance"],
        "description": row["description"],
        "instagram": row["instagram"],
        "services": [s for s in row["services"].split(",") if s],
        "price_min": row["price_min"],
        "price_max": row["price_max"],
        "hours": hours,
        "open_now": _open_now(hours),
        "lat": row["lat"],
        "lng": row["lng"],
        "photos": photos,
        "distance_km": round(dist, 1) if dist is not None else None,
        "verified": bool(row["owner_verified"]),
        "whatsapp_url": f"https://wa.me/{whatsapp_number(row['phone'])}?text={quote(WHATSAPP_MESSAGE)}",
    }


# ---------- browsing (signed-in users) ----------

@app.get("/api/services")
def list_services():
    return [{"key": k, "label": v} for k, v in SERVICES.items()]


@app.get("/api/businesses")
def search(
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = Query(10, gt=0, le=MAX_RADIUS_KM),
    service: str | None = None,
    q: str | None = Query(None, max_length=60),
    max_price: int | None = Query(None, gt=0),
    open_now: bool = False,
    _user: dict = Depends(current_user),
):
    sql = f"{BIZ_SELECT} WHERE 1=1"
    args: list = []
    has_loc = lat is not None and lng is not None
    if has_loc:
        _check_coords(lat, lng)
        a, b, c, d = bounding_box(lat, lng, radius_km)
        sql += " AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?"
        args += [a, b, c, d]
    if service:
        if service not in SERVICES:
            raise HTTPException(422, "שירות לא מוכר")
        sql += " AND (',' || services || ',') LIKE ?"
        args.append(f"%,{service},%")
    if max_price is not None:  # the business's cheapest treatment fits the budget
        sql += " AND price_min <= ?"
        args.append(max_price)
    if q and q.strip():
        sql += " AND (name LIKE ? OR city LIKE ? OR description LIKE ?)"
        like = f"%{q.strip()}%"
        args += [like, like, like]
    sql += " ORDER BY created_at DESC, id DESC LIMIT 500"

    now = datetime.now(TZ)
    with db.connect() as conn:
        results = []
        for r in conn.execute(sql, args).fetchall():
            dist = distance_km(lat, lng, r["lat"], r["lng"]) if has_loc else None
            if dist is not None and dist > radius_km:
                continue
            if open_now and not _open_now(json.loads(r["hours"] or "{}"), now):
                continue
            results.append((dist, r))
        if has_loc:
            results.sort(key=lambda x: x[0])
        return [_public(r, _photos(conn, r["id"]), dist) for dist, r in results[:100]]


@app.get("/api/businesses/{business_id}")
def get_business(business_id: int, lat: float | None = None, lng: float | None = None,
                 user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        if row["owner_uid"] != user["uid"] and ratelimit.once(f"view:{user['uid']}:{business_id}", 3600):
            conn.execute("UPDATE businesses SET views = views + 1 WHERE id = ?", (business_id,))
        conn.execute(f"UPDATE favorites SET seen_at = {NOW} WHERE uid = ? AND business_id = ?",  # nosec B608: NOW is a constant
                     (user["uid"], business_id))
        dist = distance_km(lat, lng, row["lat"], row["lng"]) if lat is not None and lng is not None else None
        return _public(row, _photos(conn, business_id), dist)


@app.post("/api/businesses/{business_id}/lead", status_code=204)
def whatsapp_lead(business_id: int, user: dict = Depends(current_user)):
    """Called when a customer taps the WhatsApp button (counts the enquiry)."""
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        if row["owner_uid"] != user["uid"] and ratelimit.once(f"lead:{user['uid']}:{business_id}", 600):
            conn.execute(
                "UPDATE businesses SET whatsapp_clicks = whatsapp_clicks + 1 WHERE id = ?",
                (business_id,),
            )


# ---------- business owners ----------

@app.get("/api/my/businesses")
def my_businesses(user: dict = Depends(current_user)):
    with db.connect() as conn:
        rows = conn.execute(
            f"{BIZ_SELECT} WHERE owner_uid = ? ORDER BY id", (user["uid"],)
        ).fetchall()
        out = []
        for r in rows:
            b = _public(r, _photos(conn, r["id"]))
            saves = conn.execute("SELECT COUNT(*) FROM favorites WHERE business_id = ?", (r["id"],)).fetchone()[0]
            b["stats"] = {"views": r["views"], "whatsapp_clicks": r["whatsapp_clicks"], "saves": saves}
            out.append(b)
        return out


@app.post("/api/businesses", status_code=201)
async def create_business(
    name: str = Form(..., min_length=2, max_length=60),
    phone: str = Form(...),
    city: str = Form(..., min_length=2, max_length=40),
    street: str = Form("", max_length=60),
    house_number: str = Form("", max_length=10),
    apartment: str = Form("", max_length=10),
    entrance: str = Form("", max_length=10),
    description: str = Form("", max_length=600),
    instagram: str = Form("", max_length=100),
    services: str = Form(""),
    price_min: int = Form(...),
    price_max: int = Form(...),
    hours: str = Form(...),
    lat: float | None = Form(None),     # from the phone's location; otherwise found from the address
    lng: float | None = Form(None),
    photos: list[UploadFile] = File(...),
    photos_rights: bool = Form(False),   # "the photos are my own work and I may publish them"
    user: dict = Depends(current_user),
):
    _throttle(user, "create", 10, 3600)
    norm = normalize_phone(phone)
    if norm is None:
        raise HTTPException(422, "מספר טלפון לא תקין")
    city, street, house_number = city.strip(), street.strip(), house_number.strip()
    apartment, entrance = apartment.strip(), entrance.strip()
    service_keys = _services(services)
    _check_prices(price_min, price_max)
    hours_ok = _hours(hours)
    insta = _instagram(instagram)
    if not (MIN_PHOTOS <= len(photos) <= MAX_PHOTOS):
        raise HTTPException(422, f"צריך להעלות בין {MIN_PHOTOS} ל-{MAX_PHOTOS} תמונות")
    if not photos_rights:
        raise HTTPException(422, "צריך לאשר שהתמונות הן של עבודות שלך ושמותר לך לפרסם אותן")
    if (lat is None) != (lng is None):
        raise HTTPException(422, "צריך לשלוח גם lat וגם lng")
    if lat is None:
        lat, lng = _locate(city, street, house_number)
    _check_coords(lat, lng)

    saved = await _save_photos(photos)
    try:
        with db.connect() as conn:
            conn.execute("BEGIN")
            cur = conn.execute(
                "INSERT INTO businesses (owner_uid, name, phone, city, address, street, house_number,"
                " apartment, entrance, description, services, price_min, price_max, hours, lat, lng,"
                " instagram, rights_confirmed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (user["uid"], name.strip(), norm, city,
                 _address_line(street, house_number, apartment, entrance), street, house_number,
                 apartment, entrance, description.strip(), ",".join(service_keys), price_min,
                 price_max, json.dumps(hours_ok), lat, lng, insta),
            )
            bid = cur.lastrowid
            conn.executemany(
                "INSERT INTO photos (business_id, filename, position) VALUES (?, ?, ?)",
                [(bid, n, i) for i, n in enumerate(saved)],
            )
            conn.execute(f"UPDATE businesses SET photos_updated_at = {NOW} WHERE id = ?", (bid,))  # nosec B608: NOW is a constant
            conn.execute("COMMIT")
    except BaseException:
        _delete_files(saved)
        raise
    return {"id": bid}


class BusinessUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=60)
    phone: str | None = None
    city: str | None = Field(None, min_length=2, max_length=40)
    street: str | None = Field(None, max_length=60)
    house_number: str | None = Field(None, max_length=10)
    apartment: str | None = Field(None, max_length=10)
    entrance: str | None = Field(None, max_length=10)
    description: str | None = Field(None, max_length=600)
    instagram: str | None = Field(None, max_length=100)
    services: list[str] | None = None
    price_min: int | None = None
    price_max: int | None = None
    hours: dict | None = None
    lat: float | None = None
    lng: float | None = None


@app.patch("/api/businesses/{business_id}")
def update_business(business_id: int, body: BusinessUpdate, user: dict = Depends(current_user)):
    _throttle(user, "edit", 60, 3600)
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.phone is not None:
        norm = normalize_phone(body.phone)
        if norm is None:
            raise HTTPException(422, "מספר טלפון לא תקין")
        fields["phone"] = norm
    for key in ("city", "street", "house_number", "apartment", "entrance", "description"):
        val = getattr(body, key)
        if val is not None:
            fields[key] = val.strip()
    if body.instagram is not None:
        fields["instagram"] = _instagram(body.instagram)
    if body.services is not None:
        fields["services"] = ",".join(_services(",".join(body.services)))
    if (body.price_min is None) != (body.price_max is None):
        raise HTTPException(422, "צריך לשלוח גם מחיר מינימום וגם מקסימום")
    if body.price_min is not None:
        _check_prices(body.price_min, body.price_max)
        fields["price_min"], fields["price_max"] = body.price_min, body.price_max
    if body.hours is not None:
        fields["hours"] = json.dumps(_hours(body.hours))
    if (body.lat is None) != (body.lng is None):
        raise HTTPException(422, "צריך לשלוח גם lat וגם lng")
    if body.lat is not None:
        _check_coords(body.lat, body.lng)
        fields["lat"], fields["lng"] = body.lat, body.lng

    with db.connect() as conn:
        row = _owned_business(conn, business_id, user)
        merged = {k: fields.get(k, row[k]) for k in ("city", "street", "house_number", "apartment", "entrance")}
        if any(k in fields for k in merged):
            fields["address"] = _address_line(merged["street"], merged["house_number"],
                                              merged["apartment"], merged["entrance"])
            moved = any(fields.get(k, row[k]) != row[k] for k in ("city", "street", "house_number"))
            if moved and "lat" not in fields:  # new address and no pin from the phone: find it
                fields["lat"], fields["lng"] = _locate(merged["city"], merged["street"], merged["house_number"])
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE businesses SET {sets} WHERE id = ?", [*fields.values(), business_id])  # nosec B608: column names come from a fixed list in code; values are parameters
        return _public(_get_business(conn, business_id), _photos(conn, business_id))


@app.post("/api/businesses/{business_id}/photos", status_code=201)
async def add_photos(business_id: int, photos: list[UploadFile] = File(...),
                     user: dict = Depends(current_user)):
    _throttle(user, "photos", 40, 3600)
    with db.connect() as conn:
        _owned_business(conn, business_id, user)
        count = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE business_id = ?", (business_id,)
        ).fetchone()[0]
    if count + len(photos) > MAX_PHOTOS:
        raise HTTPException(422, f"אפשר עד {MAX_PHOTOS} תמונות לעסק")
    saved = await _save_photos(photos)
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO photos (business_id, filename, position) VALUES (?, ?, ?)",
            [(business_id, n, count + i) for i, n in enumerate(saved)],
        )
        conn.execute(f"UPDATE businesses SET photos_updated_at = {NOW} WHERE id = ?", (business_id,))  # nosec B608: NOW is a constant
        return _photos(conn, business_id)


@app.post("/api/businesses/{business_id}/photos/{photo_id}/main")
def set_main_photo(business_id: int, photo_id: int, user: dict = Depends(current_user)):
    """Move a photo to the front: it becomes the cover on the business card."""
    with db.connect() as conn:
        _owned_business(conn, business_id, user)
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM photos WHERE business_id = ? ORDER BY position, id", (business_id,))]
        if photo_id not in ids:
            raise HTTPException(404, "התמונה לא נמצאה")
        ids.remove(photo_id)
        conn.execute("BEGIN")
        conn.executemany("UPDATE photos SET position = ? WHERE id = ?",
                         [(pos, pid) for pos, pid in enumerate([photo_id, *ids])])
        conn.execute("COMMIT")
        return _photos(conn, business_id)


@app.delete("/api/businesses/{business_id}/photos/{photo_id}")
def delete_photo(business_id: int, photo_id: int, user: dict = Depends(current_user)):
    with db.connect() as conn:
        _owned_business(conn, business_id, user)
        photo = conn.execute(
            "SELECT filename FROM photos WHERE id = ? AND business_id = ?", (photo_id, business_id)
        ).fetchone()
        if photo is None:
            raise HTTPException(404, "התמונה לא נמצאה")
        count = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE business_id = ?", (business_id,)
        ).fetchone()[0]
        if count <= MIN_PHOTOS:
            raise HTTPException(422, f"חייבות להישאר לפחות {MIN_PHOTOS} תמונות")
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
        _delete_files([photo["filename"]])
        return _photos(conn, business_id)


@app.delete("/api/businesses/{business_id}", status_code=204)
def delete_business(business_id: int, user: dict = Depends(current_user)):
    with db.connect() as conn:
        _owned_business(conn, business_id, user)
        names = [r["filename"] for r in conn.execute(
            "SELECT filename FROM photos WHERE business_id = ?", (business_id,))]
        conn.execute("DELETE FROM businesses WHERE id = ?", (business_id,))
    _delete_files(names)


# ---------- favorites (saved businesses, kept in the account) ----------

@app.get("/api/favorites/ids")
def favorite_ids(user: dict = Depends(current_user)):
    with db.connect() as conn:
        return [r[0] for r in conn.execute(
            "SELECT business_id FROM favorites WHERE uid = ? ORDER BY created_at DESC, rowid DESC",
            (user["uid"],))]


@app.get("/api/favorites")
def favorites(lat: float | None = None, lng: float | None = None, user: dict = Depends(current_user)):
    """Saved businesses, newest first; `new_photos` = photos added since she last opened the page."""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT b.*, f.seen_at FROM ({BIZ_SELECT}) b JOIN favorites f ON f.business_id = b.id"  # nosec B608: constant query text
            " WHERE f.uid = ? ORDER BY f.created_at DESC, f.rowid DESC", (user["uid"],),
        ).fetchall()
        out = []
        for r in rows:
            dist = distance_km(lat, lng, r["lat"], r["lng"]) if lat is not None and lng is not None else None
            b = _public(r, _photos(conn, r["id"]), dist)
            b["new_photos"] = bool(r["photos_updated_at"]) and r["photos_updated_at"] > r["seen_at"]
            out.append(b)
        return out


@app.put("/api/favorites/{business_id}", status_code=204)
def add_favorite(business_id: int, user: dict = Depends(current_user)):
    _throttle(user, "fav", 200, 3600)
    with db.connect() as conn:
        _get_business(conn, business_id)
        conn.execute(
            f"INSERT OR IGNORE INTO favorites (uid, business_id, seen_at) VALUES (?, ?, {NOW})",
            (user["uid"], business_id),
        )


@app.delete("/api/favorites/{business_id}", status_code=204)
def remove_favorite(business_id: int, user: dict = Depends(current_user)):
    with db.connect() as conn:
        conn.execute("DELETE FROM favorites WHERE uid = ? AND business_id = ?", (user["uid"], business_id))


# ---------- business owner verification ----------

@app.post("/api/me/verification", status_code=201)
async def request_verification(selfie: UploadFile = File(...), user: dict = Depends(current_user)):
    """A selfie for the admin to compare with the profile; kept privately and deleted once decided."""
    _throttle(user, "verify", 3, 86400)
    if user["verified"]:
        raise HTTPException(409, "החשבון כבר מאומת")
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM verifications WHERE uid = ? AND status = 'pending'",
                        (user["uid"],)).fetchone():
            raise HTTPException(409, "כבר שלחת בקשה, והיא בבדיקה")
        if not conn.execute("SELECT 1 FROM businesses WHERE owner_uid = ?", (user["uid"],)).fetchone():
            raise HTTPException(422, "אימות מיועד לבעלות עסקים. קודם צריך להוסיף עסק")
    [name] = await _save_photos([selfie], db.private_dir())
    with db.connect() as conn:
        conn.execute("INSERT INTO verifications (uid, selfie) VALUES (?, ?)", (user["uid"], name))
        return _get_user(conn, user["uid"])


# ---------- admin ----------

@app.get("/api/admin/summary")
def admin_summary(_admin: dict = Depends(admin_user)):
    with db.connect() as conn:
        pending = conn.execute("SELECT COUNT(*) FROM verifications WHERE status = 'pending'").fetchone()[0]
    return {"pending_verifications": pending, "backup": backup.last_status()}


@app.get("/api/admin/verifications")
def admin_verifications(status: str = Query("pending", pattern="^(pending|approved|rejected)$"),
                        _admin: dict = Depends(admin_user)):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT v.*, u.name, u.email, u.phone, u.city, u.avatar, u.verified FROM verifications v"
            " JOIN users u ON u.uid = v.uid WHERE v.status = ? ORDER BY v.id DESC LIMIT 100",
            (status,),
        ).fetchall()
        out = []
        for r in rows:
            businesses = conn.execute(
                "SELECT id, name, city FROM businesses WHERE owner_uid = ? ORDER BY id", (r["uid"],)
            ).fetchall()
            out.append({
                "id": r["id"], "uid": r["uid"], "status": r["status"], "note": r["note"],
                "created_at": r["created_at"], "decided_at": r["decided_at"],
                "user": {"name": r["name"], "email": r["email"], "phone": r["phone"], "city": r["city"],
                         "verified": bool(r["verified"]),
                         "avatar_url": f"/uploads/{r['avatar']}" if r["avatar"] else None},
                "businesses": [dict(b) for b in businesses],
                "has_selfie": bool(r["selfie"]),
            })
        return out


@app.get("/api/admin/verifications/{vid}/selfie")
def admin_selfie(vid: int, _admin: dict = Depends(admin_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT selfie FROM verifications WHERE id = ?", (vid,)).fetchone()
    if row is None or not row["selfie"]:
        raise HTTPException(404, "התמונה לא נמצאה")
    return FileResponse(os.path.join(db.private_dir(), row["selfie"]),
                        headers={"Cache-Control": "no-store"})


class DecisionIn(BaseModel):
    approve: bool
    note: str = Field("", max_length=300)


@app.post("/api/admin/verifications/{vid}")
def admin_decide(vid: int, body: DecisionIn, _admin: dict = Depends(admin_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM verifications WHERE id = ?", (vid,)).fetchone()
        if row is None:
            raise HTTPException(404, "הבקשה לא נמצאה")
        if row["status"] != "pending":
            raise HTTPException(409, "כבר טיפלת בבקשה הזאת")
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE verifications SET status = ?, note = ?, selfie = '', decided_at = datetime('now')"
            " WHERE id = ?",
            ("approved" if body.approve else "rejected", body.note.strip(), vid),
        )
        if body.approve:
            conn.execute("UPDATE users SET verified = 1 WHERE uid = ?", (row["uid"],))
        conn.execute("COMMIT")
    _delete_files([row["selfie"]], db.private_dir())  # the selfie is only needed for the decision
    return {"id": vid, "status": "approved" if body.approve else "rejected"}


@app.post("/api/admin/users/{uid}/unverify")
def admin_unverify(uid: str, _admin: dict = Depends(admin_user)):
    with db.connect() as conn:
        conn.execute("UPDATE users SET verified = 0 WHERE uid = ?", (uid,))
    return {"uid": uid, "verified": False}


# ---------- static ----------

os.makedirs(db.uploads_dir(), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=db.uploads_dir()), name="uploads")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
