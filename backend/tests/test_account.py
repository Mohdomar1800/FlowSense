"""Account features: onboarding flag, token refresh, password change, account deletion, login rate limiting."""

from datetime import timedelta

import jwt

from app.core.config import get_settings
from app.core.timeutils import now_utc
from app.models import FocusSession, User
from tests.conftest import API, login_headers, register
from tests.helpers import make_session


def test_new_users_start_not_onboarded_and_can_finish_onboarding(client, auth):
    me = client.get(f"{API}/auth/me", headers=auth).json()
    assert me["onboarded"] is False
    assert "onboarded_at" not in me  # internal field, exposed only as the boolean

    done = client.patch(f"{API}/auth/me", headers=auth, json={"onboarded": True}).json()
    assert done["onboarded"] is True
    # Other updates leave it alone.
    assert client.patch(f"{API}/auth/me", headers=auth, json={"timezone": "Europe/Paris"}).json()["onboarded"] is True


def test_login_returns_expiry_and_refresh_issues_a_new_valid_token(client, auth):
    login = client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "password123"}).json()
    assert login["expires_in"] == get_settings().jwt_expire_minutes * 60

    refreshed = client.post(f"{API}/auth/refresh", headers=auth)
    assert refreshed.status_code == 200
    headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 200
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_tokens_without_issue_time_are_rejected(client, auth):
    settings = get_settings()
    no_iat = jwt.encode(
        {"sub": "1", "type": "access", "exp": now_utc() + timedelta(hours=1)}, settings.jwt_secret_key, "HS256"
    )
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {no_iat}"}).status_code == 401


def test_password_change_signs_out_other_devices(client, db, auth):
    other_device = login_headers(client)
    # Make the existing tokens clearly older than the change (tokens have one-second resolution).
    db.query(User).update({User.created_at: now_utc() - timedelta(days=1)})
    old_settings = get_settings()
    stale = jwt.encode(
        {
            "sub": str(db.query(User).one().id),
            "type": "access",
            "iat": now_utc() - timedelta(minutes=5),
            "exp": now_utc() + timedelta(hours=1),
        },
        old_settings.jwt_secret_key,
        "HS256",
    )

    response = client.post(
        f"{API}/auth/password", headers=auth, json={"current_password": "password123", "new_password": "new-password-1"}
    )
    assert response.status_code == 200
    fresh = {"Authorization": f"Bearer {response.json()['access_token']}"}

    rejected = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {stale}"})
    assert rejected.status_code == 401
    assert "password was changed" in rejected.json()["error"]["message"]
    assert client.get(f"{API}/auth/me", headers=fresh).status_code == 200
    assert other_device  # issued in the same second as the change: tolerated, as documented

    assert (
        client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "password123"}).status_code
        == 401
    )
    assert (
        client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "new-password-1"}).status_code
        == 200
    )


def test_password_change_validation(client, auth):
    def change(current, new):
        return client.post(
            f"{API}/auth/password", headers=auth, json={"current_password": current, "new_password": new}
        )

    assert change("wrong-password", "new-password-1").status_code == 401
    assert change("password123", "short").status_code == 422
    assert change("password123", "password123").status_code == 400
    assert change("password123", "x" * 73).status_code == 422


def test_websocket_rejects_tokens_from_before_a_password_change(client, db, auth):
    user = db.query(User).one()
    stale = jwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "iat": now_utc() - timedelta(minutes=5),
            "exp": now_utc() + timedelta(hours=1),
        },
        get_settings().jwt_secret_key,
        "HS256",
    )
    client.post(
        f"{API}/auth/password", headers=auth, json={"current_password": "password123", "new_password": "new-password-1"}
    )
    with client.websocket_connect(f"{API}/ws?token={stale}") as ws:
        try:
            ws.receive_json()
            raise AssertionError("expected the socket to be closed")
        except Exception as exc:  # WebSocketDisconnect
            assert getattr(exc, "code", None) == 4401


def test_delete_account_removes_everything(client, db, auth):
    start = now_utc() - timedelta(hours=1)
    make_session(client, auth, start, start + timedelta(minutes=30))
    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    make_session(client, other, start, start + timedelta(minutes=20))

    wrong = client.request("DELETE", f"{API}/auth/me", headers=auth, json={"password": "nope-nope"})
    assert wrong.status_code == 401
    assert client.request("DELETE", f"{API}/auth/me", headers=auth, json={"password": "password123"}).status_code == 204

    assert client.get(f"{API}/auth/me", headers=auth).status_code == 401
    assert db.query(User).filter_by(email="user@example.com").count() == 0
    assert db.query(FocusSession).count() == 1  # only the other user's session remains
    assert client.get(f"{API}/sessions", headers=other).json()["total_focus_seconds"] == 20 * 60


def test_login_rate_limiting(client):
    register(client)

    def attempt(password, email="user@example.com"):
        return client.post(f"{API}/auth/login", json={"email": email, "password": password})

    for _ in range(8):
        assert attempt("wrong-guess").status_code == 401
    blocked = attempt("password123")  # even the right password waits out the lockout
    assert blocked.status_code == 429
    assert blocked.json()["error"]["type"] == "too_many_requests"
    assert int(blocked.headers["Retry-After"]) > 0

    # Another account is unaffected.
    register(client, email="other@example.com")
    assert attempt("password123", email="other@example.com").status_code == 200


def test_successful_login_resets_the_failure_count(client):
    register(client)
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "wrong-guess"})
    assert (
        client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "password123"}).status_code
        == 200
    )
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "wrong-guess"})
    assert (
        client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "password123"}).status_code
        == 200
    )
