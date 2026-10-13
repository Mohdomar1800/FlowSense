from tests.conftest import API


def test_patch_settings_updates_only_given_fields(client, auth):
    response = client.patch(
        f"{API}/settings", headers=auth, json={"pause_threshold_seconds": 600, "camera_tracking_enabled": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pause_threshold_seconds"] == 600
    assert body["camera_tracking_enabled"] is True
    assert body["daily_focus_goal_minutes"] == 120  # untouched


def test_settings_validation(client, auth):
    assert client.patch(f"{API}/settings", headers=auth, json={"pause_threshold_seconds": 5}).status_code == 422
    assert client.patch(f"{API}/settings", headers=auth, json={"daily_focus_goal_minutes": 5000}).status_code == 422


def test_new_sessions_use_current_pause_threshold(client, auth):
    client.patch(f"{API}/settings", headers=auth, json={"pause_threshold_seconds": 900})
    session = client.post(f"{API}/sessions/start", headers=auth, json={}).json()
    assert session["pause_threshold_seconds"] == 900
