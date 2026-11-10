import json

from app.geo import distance_km, normalize_phone, whatsapp_number

from .conftest import JPEG, auth, make_business, photos, register

TLV = (32.0853, 34.7818)
RAMAT_GAN = (32.0684, 34.8248)   # ~4.5 km from TLV
JERUSALEM = (31.7683, 35.2137)   # ~54 km from TLV


def test_geo_helpers():
    assert 4 < distance_km(*TLV, *RAMAT_GAN) < 5
    assert normalize_phone("+972 50-123-4567") == "0501234567"
    assert normalize_phone("123") is None
    assert whatsapp_number("0501234567") == "972501234567"


def test_requires_five_photos(client):
    assert make_business(client, n=4).status_code == 422


def test_rejects_non_images(client):
    r = client.post("/api/businesses", data={
        "name": "xyz", "phone": "0501234567", "city": "חיפה", "price_min": "100",
        "price_max": "200", "hours": json.dumps({"0": ["09:00", "17:00"]}),
        "lat": "32.8", "lng": "35.0", "photos_rights": "true",
    }, files=photos(5, data=b"not an image at all"))
    assert r.status_code == 415


def test_rejects_bad_phone(client):
    assert make_business(client, phone="12").status_code == 422


def test_create_and_search_by_radius(client):
    a = make_business(client, *RAMAT_GAN, name="רמת גן נייל").json()
    make_business(client, *JERUSALEM, name="ירושלים נייל")

    near = client.get("/api/businesses", params={"lat": TLV[0], "lng": TLV[1], "radius_km": 10}).json()
    assert [b["name"] for b in near] == ["רמת גן נייל"]
    assert near[0]["id"] == a["id"]
    assert 4 < near[0]["distance_km"] < 5
    assert len(near[0]["photos"]) == 5

    far = client.get("/api/businesses", params={"lat": TLV[0], "lng": TLV[1], "radius_km": 100}).json()
    assert [b["name"] for b in far] == ["רמת גן נייל", "ירושלים נייל"]  # sorted by distance


def test_filter_by_service(client):
    make_business(client, services="gel")
    make_business(client, services="pedicure", name="פדיקור פלוס")
    r = client.get("/api/businesses", params={"service": "pedicure"}).json()
    assert [b["name"] for b in r] == ["פדיקור פלוס"]


def test_whatsapp_link_and_lead_counting(client):
    bid = make_business(client).json()["id"]
    customer = register(client, "noa")
    b = client.get(f"/api/businesses/{bid}", headers=customer).json()
    assert b["whatsapp_url"].startswith("https://wa.me/972501234567?text=")
    assert client.post(f"/api/businesses/{bid}/lead", headers=customer).status_code == 204
    client.post(f"/api/businesses/{bid}/lead")  # owner's own clicks are not counted
    stats = client.get("/api/my/businesses").json()[0]["stats"]
    assert stats == {"views": 1, "whatsapp_clicks": 1, "saves": 0}


def test_only_owner_can_edit(client):
    bid = make_business(client).json()["id"]
    other = register(client, "noa")
    assert client.patch(f"/api/businesses/{bid}", json={"name": "חדש"}, headers=other).status_code == 403
    assert client.delete(f"/api/businesses/{bid}", headers=other).status_code == 403
    r = client.patch(f"/api/businesses/{bid}", json={"name": "חדש", "services": ["art"]})
    assert r.status_code == 200
    assert r.json()["name"] == "חדש"
    assert r.json()["services"] == ["art"]


def test_my_businesses_lists_only_mine(client):
    make_business(client, name="שלי")
    make_business(client, name="של נועה", headers=register(client, "noa"))
    assert [b["name"] for b in client.get("/api/my/businesses").json()] == ["שלי"]


def test_photos_keep_minimum(client):
    bid = make_business(client).json()["id"]
    first = client.get(f"/api/businesses/{bid}").json()["photos"][0]["id"]
    assert client.delete(f"/api/businesses/{bid}/photos/{first}").status_code == 422
    added = client.post(f"/api/businesses/{bid}/photos", files=photos(1))
    assert added.status_code == 201 and len(added.json()) == 6
    assert client.delete(f"/api/businesses/{bid}/photos/{first}").status_code == 200


def test_uploaded_photo_is_served(client):
    bid = make_business(client).json()["id"]
    url = client.get(f"/api/businesses/{bid}").json()["photos"][0]["url"]
    r = client.get(url)
    assert r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff"


def test_delete_business(client):
    bid = make_business(client).json()["id"]
    assert client.delete(f"/api/businesses/{bid}").status_code == 204
    assert client.get(f"/api/businesses/{bid}").status_code == 404


# ---------- prices ----------

def test_price_range_required_and_validated(client):
    assert make_business(client, price_min="300", price_max="100").status_code == 422
    assert make_business(client, price_min="0", price_max="100").status_code == 422


def test_price_shown_and_filtered(client):
    make_business(client, name="זול", price_min="60", price_max="150")
    make_business(client, name="יקר", price_min="250", price_max="500")
    all_ = client.get("/api/businesses").json()
    assert {(b["name"], b["price_min"], b["price_max"]) for b in all_} == {("זול", 60, 150), ("יקר", 250, 500)}
    cheap = client.get("/api/businesses", params={"max_price": 200}).json()
    assert [b["name"] for b in cheap] == ["זול"]


def test_owner_updates_prices(client):
    bid = make_business(client).json()["id"]
    assert client.patch(f"/api/businesses/{bid}", json={"price_min": 90}).status_code == 422
    r = client.patch(f"/api/businesses/{bid}", json={"price_min": 90, "price_max": 400})
    assert (r.json()["price_min"], r.json()["price_max"]) == (90, 400)


# ---------- opening hours ----------

def test_hours_validation(client):
    bad = [
        {},                                   # no open day
        {"7": ["09:00", "17:00"]},            # bad day
        {"0": ["9:00", "17:00"]},             # bad time format
        {"0": ["18:00", "09:00"]},            # closes before it opens
        {"0": ["09:00"]},
    ]
    for hours in bad:
        assert make_business(client, hours=json.dumps(hours)).status_code == 422, hours


def test_hours_saved_and_closed_days_dropped(client):
    hours = {"0": ["09:00", "19:00"], "5": ["09:00", "14:00"], "6": None}
    bid = make_business(client, hours=json.dumps(hours)).json()["id"]
    b = client.get(f"/api/businesses/{bid}").json()
    assert b["hours"] == {"0": ["09:00", "19:00"], "5": ["09:00", "14:00"]}
    r = client.patch(f"/api/businesses/{bid}", json={"hours": {"1": ["10:00", "20:00"]}})
    assert r.json()["hours"] == {"1": ["10:00", "20:00"]}


def test_open_now_logic():
    from datetime import datetime

    from app.main import _open_now
    hours = {"0": ["09:00", "19:00"]}               # Sunday only
    sunday = datetime(2026, 11, 8, 10, 0)            # 2026-11-08 is a Sunday
    assert _open_now(hours, sunday)
    assert not _open_now(hours, sunday.replace(hour=8, minute=59))
    assert not _open_now(hours, sunday.replace(hour=19, minute=0))
    assert not _open_now(hours, datetime(2026, 11, 9, 10, 0))  # Monday


def test_open_now_filter(client):
    make_business(client, name="תמיד פתוח")
    never = {str(d): ["00:00", "00:01"] for d in range(7)}
    make_business(client, name="כמעט תמיד סגור", hours=json.dumps(never))
    r = client.get("/api/businesses", params={"open_now": "true"}).json()
    names = [b["name"] for b in r]
    assert "תמיד פתוח" in names and "כמעט תמיד סגור" not in names


# ---------- instagram & main photo ----------

def test_instagram_forms(client):
    for raw, expected in [("@nail.studio_1", "nail.studio_1"), ("https://www.instagram.com/lia.nails/?hl=he", "lia.nails"),
                          ("instagram.com/abc", "abc"), ("", "")]:
        bid = make_business(client, instagram=raw).json()["id"]
        assert client.get(f"/api/businesses/{bid}").json()["instagram"] == expected
    assert make_business(client, instagram="not valid!").status_code == 422
    r = client.patch(f"/api/businesses/{bid}", json={"instagram": "@new_name"})
    assert r.json()["instagram"] == "new_name"


def test_set_main_photo(client):
    bid = make_business(client).json()["id"]
    ids = [p["id"] for p in client.get(f"/api/businesses/{bid}").json()["photos"]]
    r = client.post(f"/api/businesses/{bid}/photos/{ids[3]}/main")
    assert [p["id"] for p in r.json()] == [ids[3], ids[0], ids[1], ids[2], ids[4]]
    assert client.get("/api/businesses").json()[0]["photos"][0]["id"] == ids[3]   # the card cover
    other = register(client, "noa")
    assert client.post(f"/api/businesses/{bid}/photos/{ids[0]}/main", headers=other).status_code == 403
    assert client.post(f"/api/businesses/{bid}/photos/99999/main").status_code == 404


# ---------- security headers & 404 ----------

def test_security_headers(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "fonts.googleapis.com" not in csp            # fonts are self-hosted
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/businesses").headers["cache-control"] == "no-store"


def test_html_404_for_unknown_pages(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "הדף הזה לא נמצא" in r.text
    assert client.get("/api/no-such-thing").status_code == 404


def test_fonts_are_served_locally(client):
    assert "@font-face" in client.get("/fonts/fonts.css").text
    assert client.get("/fonts/heebo-hebrew-400-normal.woff2").status_code == 200


def test_photo_rights_confirmation_required(client):
    assert make_business(client, photos_rights="false").status_code == 422
