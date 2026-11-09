import os

import pytest

from .conftest import JPEG, auth, make_business, register

SELFIE = {"selfie": ("me.jpg", JPEG, "image/jpeg")}


@pytest.fixture
def admin(client, monkeypatch):
    monkeypatch.setenv("NAILS_ADMIN_EMAILS", "Boss@Example.com, other@example.com")
    return register(client, "boss", "המנהל")  # registers boss@example.com


def test_admin_flag(client, admin):
    assert client.get("/api/me", headers=admin).json()["is_admin"] is True
    assert client.get("/api/me").json()["is_admin"] is False


def test_only_admins_reach_admin_api(client, admin):
    assert client.get("/api/admin/summary").status_code == 403
    assert client.get("/api/admin/verifications").status_code == 403
    assert client.get("/api/admin/summary", headers=admin).json() == {"pending_verifications": 0}


def test_request_needs_a_business(client):
    assert client.post("/api/me/verification", files=SELFIE).status_code == 422


def test_full_approval_flow(client, admin, tmp_path):
    bid = make_business(client).json()["id"]
    assert client.get(f"/api/businesses/{bid}").json()["verified"] is False

    me = client.post("/api/me/verification", files=SELFIE).json()
    assert me["verification"]["status"] == "pending" and me["verified"] is False
    assert client.post("/api/me/verification", files=SELFIE).status_code == 409   # one at a time

    # the selfie is private: not under /uploads, only through the admin API
    assert os.listdir(tmp_path / "private")
    [req] = client.get("/api/admin/verifications", headers=admin).json()
    assert req["user"]["name"] == "דנה" and req["businesses"][0]["id"] == bid and req["has_selfie"]
    assert client.get(f"/api/admin/verifications/{req['id']}/selfie").status_code == 403
    assert client.get(f"/api/admin/verifications/{req['id']}/selfie", headers=admin).content == JPEG
    assert client.get("/api/admin/summary", headers=admin).json()["pending_verifications"] == 1

    r = client.post(f"/api/admin/verifications/{req['id']}", json={"approve": True}, headers=admin)
    assert r.json()["status"] == "approved"
    assert os.listdir(tmp_path / "private") == []                                  # selfie deleted
    assert client.get("/api/me").json()["verified"] is True
    assert client.get(f"/api/businesses/{bid}").json()["verified"] is True        # badge everywhere
    assert client.get("/api/businesses").json()[0]["verified"] is True
    assert client.post(f"/api/admin/verifications/{req['id']}", json={"approve": False}, headers=admin).status_code == 409
    assert client.post("/api/me/verification", files=SELFIE).status_code == 409   # already verified


def test_reject_with_reason_then_retry(client, admin):
    make_business(client)
    client.post("/api/me/verification", files=SELFIE)
    [req] = client.get("/api/admin/verifications", headers=admin).json()
    client.post(f"/api/admin/verifications/{req['id']}", json={"approve": False, "note": "התמונה מטושטשת"}, headers=admin)
    me = client.get("/api/me").json()
    assert me["verified"] is False
    assert me["verification"] == {**me["verification"], "status": "rejected", "note": "התמונה מטושטשת"}
    assert client.get("/api/admin/verifications?status=rejected", headers=admin).json()[0]["has_selfie"] is False
    assert client.post("/api/me/verification", files=SELFIE).status_code == 201  # may try again


def test_admin_can_remove_verification(client, admin):
    make_business(client)
    client.post("/api/me/verification", files=SELFIE)
    [req] = client.get("/api/admin/verifications", headers=admin).json()
    client.post(f"/api/admin/verifications/{req['id']}", json={"approve": True}, headers=admin)
    client.post(f"/api/admin/users/{req['uid']}/unverify", headers=admin)
    assert client.get("/api/me").json()["verified"] is False


def test_selfie_must_be_image(client):
    make_business(client)
    r = client.post("/api/me/verification", files={"selfie": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_delete_account_removes_pending_selfie(client, tmp_path):
    make_business(client)
    client.post("/api/me/verification", files=SELFIE)
    client.delete("/api/me")
    assert os.listdir(tmp_path / "private") == []
