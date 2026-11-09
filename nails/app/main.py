"""Nails: find nail salons near you and contact them on WhatsApp."""
import hashlib
import hmac
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .geo import bounding_box, distance_km, normalize_phone, whatsapp_number

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

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


# ---------- helpers ----------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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


def _photo_url(filename: str) -> str:
    return f"/uploads/{filename}"


def _get_business(conn, business_id: int):
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "העסק לא נמצא")
    return row


def _authorize(row, token: str) -> None:
    if not token or not hmac.compare_digest(_hash(token), row["token_hash"]):
        raise HTTPException(403, "אין הרשאה לערוך את העסק הזה")


def _photos(conn, business_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, filename FROM photos WHERE business_id = ? ORDER BY position, id",
        (business_id,),
    ).fetchall()
    return [{"id": r["id"], "url": _photo_url(r["filename"])} for r in rows]


def _public(row, photos: list[dict], dist: float | None = None) -> dict:
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
        "lat": row["lat"],
        "lng": row["lng"],
        "photos": photos,
        "distance_km": round(dist, 1) if dist is not None else None,
        "whatsapp_url": f"/api/businesses/{row['id']}/whatsapp",
    }


# ---------- public API ----------

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

    with db.connect() as conn:
        rows = conn.execute(sql, args).fetchall()
        results = []
        for r in rows:
            dist = distance_km(lat, lng, r["lat"], r["lng"]) if has_loc else None
            if dist is not None and dist > radius_km:
                continue
            results.append((dist, r))
        if has_loc:
            results.sort(key=lambda x: x[0])
        return [_public(r, _photos(conn, r["id"]), dist) for dist, r in results[:100]]


@app.get("/api/businesses/{business_id}")
def get_business(business_id: int, lat: float | None = None, lng: float | None = None):
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        conn.execute("UPDATE businesses SET views = views + 1 WHERE id = ?", (business_id,))
        dist = distance_km(lat, lng, row["lat"], row["lng"]) if lat is not None and lng is not None else None
        return _public(row, _photos(conn, business_id), dist)


@app.get("/api/businesses/{business_id}/whatsapp")
def open_whatsapp(business_id: int):
    """Count the lead, then send the customer to WhatsApp with a ready message."""
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        conn.execute(
            "UPDATE businesses SET whatsapp_clicks = whatsapp_clicks + 1 WHERE id = ?",
            (business_id,),
        )
    url = f"https://wa.me/{whatsapp_number(row['phone'])}?text={quote(WHATSAPP_MESSAGE)}"
    return RedirectResponse(url, status_code=302)


# ---------- owner API ----------

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
    lat: float = Form(...),
    lng: float = Form(...),
    photos: list[UploadFile] = File(...),
):
    norm = normalize_phone(phone)
    if norm is None:
        raise HTTPException(422, "מספר טלפון לא תקין")
    _check_coords(lat, lng)
    service_keys = _services(services)
    _check_prices(price_min, price_max)
    if not (MIN_PHOTOS <= len(photos) <= MAX_PHOTOS):
        raise HTTPException(422, f"צריך להעלות בין {MIN_PHOTOS} ל-{MAX_PHOTOS} תמונות")

    saved = await _save_photos(photos)
    token = secrets.token_urlsafe(24)
    try:
        with db.connect() as conn:
            conn.execute("BEGIN")
            cur = conn.execute(
                "INSERT INTO businesses (name, phone, city, address, description, services,"
                " price_min, price_max, lat, lng, token_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name.strip(), norm, city.strip(), address.strip(), description.strip(),
                 ",".join(service_keys), price_min, price_max, lat, lng, _hash(token)),
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
    return {"id": bid, "token": token}


class BusinessUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=60)
    phone: str | None = None
    city: str | None = Field(None, min_length=2, max_length=40)
    address: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=600)
    services: list[str] | None = None
    price_min: int | None = None
    price_max: int | None = None
    lat: float | None = None
    lng: float | None = None


@app.get("/api/businesses/{business_id}/manage")
def manage(business_id: int, x_edit_token: str = Header("")):
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        _authorize(row, x_edit_token)
        data = _public(row, _photos(conn, business_id))
        data["stats"] = {"views": row["views"], "whatsapp_clicks": row["whatsapp_clicks"]}
        return data


@app.patch("/api/businesses/{business_id}")
def update_business(business_id: int, body: BusinessUpdate, x_edit_token: str = Header("")):
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
    if (body.lat is None) != (body.lng is None):
        raise HTTPException(422, "צריך לשלוח גם lat וגם lng")
    if body.lat is not None:
        _check_coords(body.lat, body.lng)
        fields["lat"], fields["lng"] = body.lat, body.lng

    with db.connect() as conn:
        row = _get_business(conn, business_id)
        _authorize(row, x_edit_token)
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE businesses SET {sets} WHERE id = ?", [*fields.values(), business_id])
        return _public(_get_business(conn, business_id), _photos(conn, business_id))


@app.post("/api/businesses/{business_id}/photos", status_code=201)
async def add_photos(
    business_id: int,
    photos: list[UploadFile] = File(...),
    x_edit_token: str = Header(""),
):
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        _authorize(row, x_edit_token)
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
def delete_photo(business_id: int, photo_id: int, x_edit_token: str = Header("")):
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        _authorize(row, x_edit_token)
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
def delete_business(business_id: int, x_edit_token: str = Header("")):
    with db.connect() as conn:
        row = _get_business(conn, business_id)
        _authorize(row, x_edit_token)
        names = [r["filename"] for r in conn.execute(
            "SELECT filename FROM photos WHERE business_id = ?", (business_id,))]
        conn.execute("DELETE FROM businesses WHERE id = ?", (business_id,))
    _delete_files(names)


# ---------- static ----------

os.makedirs(db.uploads_dir(), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=db.uploads_dir()), name="uploads")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
