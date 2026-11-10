import httpx
import pytest

from .conftest import make_business

REHOVOT_HERZL = (31.8964, 34.8090)


@pytest.fixture
def geo(monkeypatch):
    """Fake map lookup: knows one street, records calls."""
    from app import geocode
    calls = []

    def lookup(city, street, number):
        calls.append((city, street, number))
        if (city, street) == ("רחובות", "הרצל"):
            return REHOVOT_HERZL
        return None
    monkeypatch.setattr(geocode, "lookup", lookup)
    return calls


def without_coords(client, **over):
    """make_business always sends lat/lng; drop them to use the address."""
    import json
    from .conftest import ALWAYS_OPEN, photos
    form = {"name": "סטודיו כתובת", "phone": "0501234567", "city": "רחובות", "street": "הרצל",
            "house_number": "12", "apartment": "4", "entrance": "ב", "price_min": "100",
            "price_max": "300", "hours": json.dumps(ALWAYS_OPEN), **over}
    return client.post("/api/businesses", data=form, files=photos(5))


def test_address_is_located_and_composed(client, geo):
    r = without_coords(client)
    assert r.status_code == 201, r.text
    b = client.get(f"/api/businesses/{r.json()['id']}").json()
    assert (b["lat"], b["lng"]) == REHOVOT_HERZL
    assert b["address"] == "הרצל 12, כניסה ב, דירה 4"
    assert (b["street"], b["house_number"], b["apartment"], b["entrance"]) == ("הרצל", "12", "4", "ב")
    assert geo == [("רחובות", "הרצל", "12")]


def test_apartment_and_entrance_are_optional(client, geo):
    r = without_coords(client, apartment="", entrance="")
    b = client.get(f"/api/businesses/{r.json()['id']}").json()
    assert b["address"] == "הרצל 12"


def test_street_and_number_required_without_location(client, geo):
    assert without_coords(client, street="").status_code == 422
    assert without_coords(client, house_number="").status_code == 422


def test_unknown_address(client, geo):
    r = without_coords(client, street="רחוב שלא קיים")
    assert r.status_code == 422 and "לא מצאנו" in r.json()["detail"]


def test_lookup_service_down(client, monkeypatch):
    from app import geocode

    def down(*a):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(geocode, "lookup", down)
    assert without_coords(client).status_code == 503


def test_phone_location_skips_lookup(client, geo):
    r = make_business(client, street="הרצל", house_number="12")   # sends lat/lng
    assert r.status_code == 201 and geo == []


def test_edit_address_relocates(client, geo):
    bid = make_business(client).json()["id"]                         # Tel Aviv, from the phone
    r = client.patch(f"/api/businesses/{bid}", json={"city": "רחובות", "street": "הרצל", "house_number": "12"})
    assert r.status_code == 200
    assert (r.json()["lat"], r.json()["lng"]) == REHOVOT_HERZL and r.json()["address"] == "הרצל 12"
    # changing only the apartment keeps the position and does not look anything up
    calls = len(geo)
    r = client.patch(f"/api/businesses/{bid}", json={"apartment": "7"})
    assert r.json()["address"] == "הרצל 12, דירה 7" and len(geo) == calls
