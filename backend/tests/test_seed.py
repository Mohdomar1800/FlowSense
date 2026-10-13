"""The demo seed (used by the README and the end-to-end tests) must produce an account that is ready to use."""

from contextlib import nullcontext

from scripts import seed_demo_data
from tests.conftest import API, login_headers


def test_demo_user_is_onboarded_with_history_and_reset_recreates_it(client, db, monkeypatch):
    monkeypatch.setattr(seed_demo_data, "SessionLocal", lambda: nullcontext(db))

    seed_demo_data.seed()
    headers = login_headers(client, seed_demo_data.DEMO_EMAIL, seed_demo_data.DEMO_PASSWORD)
    me = client.get(f"{API}/auth/me", headers=headers).json()
    assert me["onboarded"] is True  # straight to the Focus screen, not the setup wizard
    assert len(client.get(f"{API}/tags", headers=headers).json()) == 3
    assert client.get(f"{API}/reports", headers=headers).json()["total_count"] > 0

    seed_demo_data.seed()  # without --reset an existing demo user is left alone
    assert client.get(f"{API}/auth/me", headers=headers).json()["id"] == me["id"]

    seed_demo_data.seed(reset=True)
    fresh = login_headers(client, seed_demo_data.DEMO_EMAIL, seed_demo_data.DEMO_PASSWORD)
    assert client.get(f"{API}/auth/me", headers=fresh).json()["id"] != me["id"]
