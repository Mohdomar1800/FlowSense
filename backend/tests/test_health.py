def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_reports_status_without_leaking_config(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ready", "database": "ok", "cache": "ok"}
    assert "password" not in response.text and "postgresql" not in response.text
