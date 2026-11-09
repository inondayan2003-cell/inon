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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, db
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
    yield


app = FastAPI(title="Nails", lifespan=lifespan)


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


def _user_out(row) -> dict:
    return {k: row[k] for k in ("uid", "name", "email", "phone", "provider")}


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
        conn.execute("UPDATE users SET last_login = datetime('now') WHERE uid = ?", (ident.uid,))
    return _user_out(row)


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)


@app.post("/api/me")
def register(body: RegisterIn, ident: auth.Identity = Depends(identity)):
    """Create the account on first sign-in (or update the name)."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (uid, name, email, phone, provider) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(uid) DO UPDATE SET name = excluded.name,"
            " email = COALESCE(excluded.email, users.email),"
            " phone = COALESCE(excluded.phone, users.phone), last_login = datetime('now')",
            (ident.uid, body.name.strip(), ident.email, ident.phone, ident.provider),
        )
        row = conn.execute("SELECT * FROM users WHERE uid = ?", (ident.uid,)).fetchone()
    return _user_out(row)


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


async def _save_photos(files: list[UploadFile]) -> list[str]:
    """Validate and store uploaded images. Returns stored filenames."""
    saved: list[str] = []
    try:
        for f in files:
            data = await f.read(MAX_PHOTO_BYTES + 1)
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, "תמונה גדולה מדי (עד 10MB)")
            ext = _image_ext(data[:16])
            if ext is None:
                raise HTTPException(415, "אפשר להעלות רק תמונות JPG / PNG / WEBP")
            name = f"{uuid.uuid4().hex}.{ext}"
            with open(os.path.join(db.uploads_dir(), name), "wb") as out:
                out.write(data)
            saved.append(name)
    except BaseException:
        _delete_files(saved)
        raise
    return saved


def _delete_files(names: list[str]) -> None:
    for n in names:
        try:
            os.remove(os.path.join(db.uploads_dir(), n))
        except FileNotFoundError:
            pass


def _get_business(conn, business_id: int):
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
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
        "description": row["description"],
        "services": [s for s in row["services"].split(",") if s],
        "price_min": row["price_min"],
        "price_max": row["price_max"],
        "hours": hours,
        "open_now": _open_now(hours),
        "lat": row["lat"],
        "lng": row["lng"],
        "photos": photos,
        "distance_km": round(dist, 1) if dist is not None else None,
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
    sql = "SELECT * FROM businesses WHERE 1=1"
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
        if row["owner_uid"] != user["uid"]:
            conn.execute("UPDATE businesses SET views = views + 1 WHERE id = ?", (business_id,))
        dist = distance_km(lat, lng, row["lat"], row["lng"]) if lat is not None and lng is not None else None
        return _public(row, _photos(conn, business_id), dist)


@app.post("/api/businesses/{business_id}/lead", status_code=204)
def whatsapp_lead(business_id: int, user: dict = Depends(current_user)):
    """Called when a customer taps the WhatsApp button (counts the enquiry)."""
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        if row["owner_uid"] != user["uid"]:
            conn.execute(
                "UPDATE businesses SET whatsapp_clicks = whatsapp_clicks + 1 WHERE id = ?",
                (business_id,),
            )


# ---------- business owners ----------

@app.get("/api/my/businesses")
def my_businesses(user: dict = Depends(current_user)):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM businesses WHERE owner_uid = ? ORDER BY id", (user["uid"],)
        ).fetchall()
        out = []
        for r in rows:
            b = _public(r, _photos(conn, r["id"]))
            b["stats"] = {"views": r["views"], "whatsapp_clicks": r["whatsapp_clicks"]}
            out.append(b)
        return out


@app.post("/api/businesses", status_code=201)
async def create_business(
    name: str = Form(..., min_length=2, max_length=60),
    phone: str = Form(...),
    city: str = Form(..., min_length=2, max_length=40),
    address: str = Form("", max_length=100),
    description: str = Form("", max_length=600),
    services: str = Form(""),
    price_min: int = Form(...),
    price_max: int = Form(...),
    hours: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...),
    photos: list[UploadFile] = File(...),
    user: dict = Depends(current_user),
):
    norm = normalize_phone(phone)
    if norm is None:
        raise HTTPException(422, "מספר טלפון לא תקין")
    _check_coords(lat, lng)
    service_keys = _services(services)
    _check_prices(price_min, price_max)
    hours_ok = _hours(hours)
    if not (MIN_PHOTOS <= len(photos) <= MAX_PHOTOS):
        raise HTTPException(422, f"צריך להעלות בין {MIN_PHOTOS} ל-{MAX_PHOTOS} תמונות")

    saved = await _save_photos(photos)
    try:
        with db.connect() as conn:
            conn.execute("BEGIN")
            cur = conn.execute(
                "INSERT INTO businesses (owner_uid, name, phone, city, address, description,"
                " services, price_min, price_max, hours, lat, lng)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user["uid"], name.strip(), norm, city.strip(), address.strip(),
                 description.strip(), ",".join(service_keys), price_min, price_max,
                 json.dumps(hours_ok), lat, lng),
            )
            bid = cur.lastrowid
            conn.executemany(
                "INSERT INTO photos (business_id, filename, position) VALUES (?, ?, ?)",
                [(bid, n, i) for i, n in enumerate(saved)],
            )
            conn.execute("COMMIT")
    except BaseException:
        _delete_files(saved)
        raise
    return {"id": bid}


class BusinessUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=60)
    phone: str | None = None
    city: str | None = Field(None, min_length=2, max_length=40)
    address: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=600)
    services: list[str] | None = None
    price_min: int | None = None
    price_max: int | None = None
    hours: dict | None = None
    lat: float | None = None
    lng: float | None = None


@app.patch("/api/businesses/{business_id}")
def update_business(business_id: int, body: BusinessUpdate, user: dict = Depends(current_user)):
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.phone is not None:
        norm = normalize_phone(body.phone)
        if norm is None:
            raise HTTPException(422, "מספר טלפון לא תקין")
        fields["phone"] = norm
    for key in ("city", "address", "description"):
        val = getattr(body, key)
        if val is not None:
            fields[key] = val.strip()
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
        _owned_business(conn, business_id, user)
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE businesses SET {sets} WHERE id = ?", [*fields.values(), business_id])
        return _public(_get_business(conn, business_id), _photos(conn, business_id))


@app.post("/api/businesses/{business_id}/photos", status_code=201)
async def add_photos(business_id: int, photos: list[UploadFile] = File(...),
                     user: dict = Depends(current_user)):
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


# ---------- static ----------

os.makedirs(db.uploads_dir(), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=db.uploads_dir()), name="uploads")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
