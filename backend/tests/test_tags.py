from tests.conftest import API, login_headers, register


def test_tag_crud(client, auth):
    created = client.post(f"{API}/tags", headers=auth, json={"name": "  Coding ", "color": "#112233"})
    assert created.status_code == 201
    tag = created.json()
    assert tag["name"] == "Coding"

    assert [t["name"] for t in client.get(f"{API}/tags", headers=auth).json()] == ["Coding"]

    renamed = client.patch(f"{API}/tags/{tag['id']}", headers=auth, json={"name": "Deep work"})
    assert renamed.json()["name"] == "Deep work"
    assert renamed.json()["color"] == "#112233"

    assert client.delete(f"{API}/tags/{tag['id']}", headers=auth).status_code == 204
    assert client.get(f"{API}/tags", headers=auth).json() == []


def test_tag_validation_and_duplicates(client, auth):
    client.post(f"{API}/tags", headers=auth, json={"name": "Reading"})
    assert client.post(f"{API}/tags", headers=auth, json={"name": "reading"}).status_code == 409
    assert client.post(f"{API}/tags", headers=auth, json={"name": "   "}).status_code == 422
    assert client.post(f"{API}/tags", headers=auth, json={"name": "x", "color": "red"}).status_code == 422

    other = client.post(f"{API}/tags", headers=auth, json={"name": "Writing"}).json()
    assert client.patch(f"{API}/tags/{other['id']}", headers=auth, json={"name": "READING"}).status_code == 409


def test_cannot_touch_another_users_tag(client, auth):
    tag = client.post(f"{API}/tags", headers=auth, json={"name": "Mine"}).json()
    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")

    assert client.patch(f"{API}/tags/{tag['id']}", headers=other, json={"name": "Stolen"}).status_code == 404
    assert client.delete(f"{API}/tags/{tag['id']}", headers=other).status_code == 404
    assert client.post(f"{API}/sessions/start", headers=other, json={"tag_id": tag["id"]}).status_code == 404
    # Same name is fine for a different user.
    assert client.post(f"{API}/tags", headers=other, json={"name": "Mine"}).status_code == 201


def test_deleting_tag_keeps_sessions_untagged(client, auth):
    tag = client.post(f"{API}/tags", headers=auth, json={"name": "Temp"}).json()
    session = client.post(f"{API}/sessions/start", headers=auth, json={"tag_id": tag["id"]}).json()
    client.delete(f"{API}/tags/{tag['id']}", headers=auth)

    active = client.get(f"{API}/sessions/active", headers=auth).json()
    assert active["id"] == session["id"]
    assert active["tag_id"] is None
