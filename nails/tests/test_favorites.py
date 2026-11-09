from .conftest import make_business, photos, register


def test_save_list_remove(client):
    a = make_business(client, name="עסק א").json()["id"]
    b = make_business(client, name="עסק ב").json()["id"]
    customer = register(client, "noa")
    assert client.put(f"/api/favorites/{a}", headers=customer).status_code == 204
    assert client.put(f"/api/favorites/{b}", headers=customer).status_code == 204
    assert client.put(f"/api/favorites/{b}", headers=customer).status_code == 204   # twice is fine
    assert client.get("/api/favorites/ids", headers=customer).json() == [b, a]       # newest first
    assert [x["name"] for x in client.get("/api/favorites", headers=customer).json()] == ["עסק ב", "עסק א"]
    assert client.delete(f"/api/favorites/{a}", headers=customer).status_code == 204
    assert client.get("/api/favorites/ids", headers=customer).json() == [b]
    assert client.get("/api/favorites/ids").json() == []                              # per account


def test_unknown_business(client):
    assert client.put("/api/favorites/999").status_code == 404


def test_new_photos_flag(client):
    bid = make_business(client).json()["id"]
    customer = register(client, "noa")
    client.put(f"/api/favorites/{bid}", headers=customer)
    assert client.get("/api/favorites", headers=customer).json()[0]["new_photos"] is False
    client.post(f"/api/businesses/{bid}/photos", files=photos(1))                   # owner adds work
    assert client.get("/api/favorites", headers=customer).json()[0]["new_photos"] is True
    client.get(f"/api/businesses/{bid}", headers=customer)                          # she looks
    assert client.get("/api/favorites", headers=customer).json()[0]["new_photos"] is False


def test_owner_sees_saves(client):
    bid = make_business(client).json()["id"]
    for uid in ("noa", "maya"):
        client.put(f"/api/favorites/{bid}", headers=register(client, uid))
    assert client.get("/api/my/businesses").json()[0]["stats"]["saves"] == 2


def test_deleted_business_disappears_from_favorites(client):
    bid = make_business(client).json()["id"]
    customer = register(client, "noa")
    client.put(f"/api/favorites/{bid}", headers=customer)
    client.delete(f"/api/businesses/{bid}")
    assert client.get("/api/favorites", headers=customer).json() == []


def test_delete_account_removes_her_favorites(client):
    bid = make_business(client).json()["id"]
    customer = register(client, "noa")
    client.put(f"/api/favorites/{bid}", headers=customer)
    client.delete("/api/me", headers=customer)
    assert client.get("/api/my/businesses").json()[0]["stats"]["saves"] == 0
