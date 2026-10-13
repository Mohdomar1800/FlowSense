from datetime import timedelta

import jwt

from app.core.config import get_settings
from app.core.timeutils import now_utc
from tests.conftest import API, login_headers, register


def test_register_returns_profile_and_creates_default_settings(client):
    user = register(client, email="New@Example.com", timezone="Asia/Kolkata")
    assert user["email"] == "new@example.com"
    assert user["timezone"] == "Asia/Kolkata"
    assert "hashed_password" not in user

    headers = login_headers(client, email="new@example.com")
    settings = client.get(f"{API}/settings", headers=headers).json()
    assert settings["pause_threshold_seconds"] == 300
    assert settings["camera_tracking_enabled"] is False


def test_register_duplicate_email_is_case_insensitive(client):
    register(client, email="dup@example.com")
    response = client.post(f"{API}/auth/register", json={"email": "DUP@example.com", "password": "password123"})
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "conflict"


def test_register_rejects_bad_input(client):
    bad_tz = client.post(
        f"{API}/auth/register", json={"email": "a@example.com", "password": "password123", "timezone": "Mars/Base"}
    )
    short_pw = client.post(f"{API}/auth/register", json={"email": "b@example.com", "password": "short"})
    long_pw = client.post(f"{API}/auth/register", json={"email": "c@example.com", "password": "x" * 73})
    bad_email = client.post(f"{API}/auth/register", json={"email": "not-an-email", "password": "password123"})
    for response in (bad_tz, short_pw, long_pw, bad_email):
        assert response.status_code == 422
        assert response.json()["error"]["type"] == "validation_error"


def test_login_success_and_failures(client):
    register(client)
    assert (
        client.post(f"{API}/auth/login", json={"email": "USER@example.com", "password": "password123"}).status_code
        == 200
    )

    wrong_password = client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "nope-nope"})
    unknown_user = client.post(f"{API}/auth/login", json={"email": "ghost@example.com", "password": "password123"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    # Same message either way, so the API does not reveal which emails are registered.
    assert wrong_password.json() == unknown_user.json()


def test_me_and_update_timezone(client, auth):
    assert client.get(f"{API}/auth/me", headers=auth).json()["email"] == "user@example.com"

    updated = client.patch(f"{API}/auth/me", headers=auth, json={"timezone": "Europe/London"})
    assert updated.status_code == 200
    assert updated.json()["timezone"] == "Europe/London"
    assert client.patch(f"{API}/auth/me", headers=auth, json={"timezone": "Nowhere/City"}).status_code == 422


def test_protected_routes_require_valid_token(client, auth):
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401

    settings = get_settings()
    expired = jwt.encode(
        {"sub": "1", "type": "access", "exp": now_utc() - timedelta(minutes=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401

    forged = jwt.encode({"sub": "1", "type": "access"}, "some-other-secret-key-of-enough-length", algorithm="HS256")
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_token_for_deleted_user_is_rejected(client, db, auth):
    from app.models import User

    db.delete(db.query(User).one())
    db.commit()
    assert client.get(f"{API}/auth/me", headers=auth).status_code == 401
