"""The API also serves the web UI from the same origin."""


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>FlowSense</title>" in response.text
    assert "Content-Security-Policy" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_assets_are_served(client):
    for path, content_type in [
        ("/js/app.js", "javascript"),
        ("/css/app.css", "text/css"),
        ("/assets/icon.svg", "image/svg+xml"),
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert content_type in response.headers["content-type"], path


def test_api_routes_take_precedence_and_errors_stay_json(client):
    assert client.get("/health").json() == {"status": "ok"}
    missing_api = client.get("/api/v1/does-not-exist")
    assert missing_api.status_code == 404
    assert missing_api.json()["error"]["type"] == "http_error"
    assert client.get("/no-such-file.txt").status_code == 404


def test_path_traversal_is_blocked(client):
    response = client.get("/../backend/app/core/config.py")
    assert response.status_code == 404
    assert "jwt_secret_key" not in response.text
