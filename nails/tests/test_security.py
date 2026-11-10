import io

from PIL import Image

from .conftest import auth, make_business, photos, register


def _jpeg_with_gps() -> bytes:
    im = Image.new("RGB", (80, 60), (180, 90, 120))
    exif = Image.Exif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (32.0, 5.0, 0.0), "E", (34.0, 46.0, 0.0)   # GPS: Tel Aviv
    exif[0x010F] = "Phone Maker"
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_photo_metadata_is_removed(client):
    raw = _jpeg_with_gps()
    original = Image.open(io.BytesIO(raw)).getexif()
    assert original.get_ifd(0x8825) and original[0x010F] == "Phone Maker"   # GPS + maker inside
    bid = make_business(client, n=5).json()["id"]
    client.post(f"/api/businesses/{bid}/photos", files=[("photos", ("gps.jpg", raw, "image/jpeg"))])
    url = client.get(f"/api/businesses/{bid}").json()["photos"][-1]["url"]
    stored = client.get(url).content
    cleaned = Image.open(io.BytesIO(stored)).getexif()
    assert not cleaned.get_ifd(0x8825) and 0x010F not in cleaned        # nothing left


def test_fake_image_rejected(client):
    fake = b"\xff\xd8\xff\xe0" + b"<script>alert(1)</script>" * 20   # JPEG header, not an image
    r = client.post("/api/me/avatar", files={"photo": ("x.jpg", fake, "image/jpeg")})
    assert r.status_code == 415


def test_big_photos_are_shrunk(client):
    buf = io.BytesIO()
    Image.new("RGB", (5000, 3000), (10, 20, 30)).save(buf, "JPEG")
    r = client.post("/api/me/avatar", files={"photo": ("big.jpg", buf.getvalue(), "image/jpeg")})
    stored = Image.open(io.BytesIO(client.get(r.json()["avatar_url"]).content))
    assert max(stored.size) == 2048


def test_request_size_limit(client):
    r = client.post("/api/me/avatar", content=b"x", headers={"content-length": str(200 * 1024 * 1024),
                                                              "content-type": "application/octet-stream"})
    assert r.status_code == 413


def test_admin_needs_verified_email(client, monkeypatch):
    monkeypatch.setenv("NAILS_ADMIN_EMAILS", "boss@example.com")
    from app import auth as auth_mod
    real = auth_mod._verify_dev

    def unverified(token):
        ident = real(token)
        ident.email_verified = False
        return ident
    h = register(client, "boss")                      # verified (Google-like)
    assert client.get("/api/me", headers=h).json()["is_admin"] is True
    monkeypatch.setattr(auth_mod, "_verify_dev", unverified)   # same email, never confirmed
    assert client.get("/api/me", headers=h).json()["is_admin"] is False
    assert client.get("/api/admin/summary", headers=h).status_code == 403


def test_views_and_leads_count_once_per_person(client):
    bid = make_business(client).json()["id"]
    fan = register(client, "fan")
    for _ in range(5):
        client.get(f"/api/businesses/{bid}", headers=fan)
        client.post(f"/api/businesses/{bid}/lead", headers=fan)
    assert client.get("/api/my/businesses").json()[0]["stats"] | {"saves": 0} == {"views": 1, "whatsapp_clicks": 1, "saves": 0}


def test_creating_businesses_is_rate_limited(client):
    codes = [make_business(client, name=f"עסק {i}").status_code for i in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429


def test_verification_requests_are_rate_limited(client):
    make_business(client)
    selfie = {"selfie": ("s.jpg", photos(1)[0][1][1], "image/jpeg")}
    codes = [client.post("/api/me/verification", files=selfie).status_code for _ in range(4)]
    assert codes[0] == 201 and codes[-1] == 429


def test_dev_tokens_rejected_without_dev_mode(client, monkeypatch):
    monkeypatch.delenv("NAILS_DEV_AUTH")
    assert client.get("/api/me", headers=auth("x", "x@y.z")).status_code == 401


def test_hsts_behind_https_proxy(client):
    r = client.get("/", headers={"x-forwarded-proto": "https"})
    assert "max-age" in r.headers["strict-transport-security"]
