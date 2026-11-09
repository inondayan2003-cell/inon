from app.geo import distance_km, normalize_phone, whatsapp_number

from .conftest import JPEG, make_business, photos

TLV = (32.0853, 34.7818)
RAMAT_GAN = (32.0684, 34.8248)   # ~4.5 km from TLV
JERUSALEM = (31.7683, 35.2137)   # ~54 km from TLV


def test_geo_helpers():
    assert 4 < distance_km(*TLV, *RAMAT_GAN) < 5
    assert normalize_phone("+972 50-123-4567") == "0501234567"
    assert normalize_phone("123") is None
    assert whatsapp_number("0501234567") == "972501234567"


def test_requires_five_photos(client):
    r = make_business(client, n=4)
    assert r.status_code == 422


def test_rejects_non_images(client):
    r = client.post("/api/businesses", data={
        "name": "x" * 3, "phone": "0501234567", "city": "חיפה",
        "lat": "32.8", "lng": "35.0",
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


def test_whatsapp_redirect_counts_lead(client):
    created = make_business(client).json()
    bid, token = created["id"], created["token"]
    r = client.get(f"/api/businesses/{bid}/whatsapp", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://wa.me/972501234567?text=")
    assert "Nails" in loc
    stats = client.get(f"/api/businesses/{bid}/manage", headers={"X-Edit-Token": token}).json()["stats"]
    assert stats["whatsapp_clicks"] == 1


def test_owner_edit_requires_token(client):
    created = make_business(client).json()
    bid, token = created["id"], created["token"]
    assert client.patch(f"/api/businesses/{bid}", json={"name": "חדש"}).status_code == 403
    assert client.patch(f"/api/businesses/{bid}", json={"name": "חדש"},
                        headers={"X-Edit-Token": "wrong"}).status_code == 403
    r = client.patch(f"/api/businesses/{bid}", json={"name": "חדש", "services": ["art"]},
                     headers={"X-Edit-Token": token})
    assert r.status_code == 200
    assert r.json()["name"] == "חדש"
    assert r.json()["services"] == ["art"]


def test_photos_keep_minimum(client):
    created = make_business(client).json()
    bid, h = created["id"], {"X-Edit-Token": created["token"]}
    first = client.get(f"/api/businesses/{bid}").json()["photos"][0]["id"]
    assert client.delete(f"/api/businesses/{bid}/photos/{first}", headers=h).status_code == 422
    added = client.post(f"/api/businesses/{bid}/photos", headers=h, files=photos(1))
    assert added.status_code == 201 and len(added.json()) == 6
    assert client.delete(f"/api/businesses/{bid}/photos/{first}", headers=h).status_code == 200


def test_uploaded_photo_is_served(client):
    created = make_business(client).json()
    url = client.get(f"/api/businesses/{created['id']}").json()["photos"][0]["url"]
    r = client.get(url)
    assert r.status_code == 200 and r.content == JPEG


def test_delete_business(client):
    created = make_business(client).json()
    bid = created["id"]
    assert client.delete(f"/api/businesses/{bid}", headers={"X-Edit-Token": created["token"]}).status_code == 204
    assert client.get(f"/api/businesses/{bid}").status_code == 404
