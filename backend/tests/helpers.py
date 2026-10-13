from datetime import datetime

from fastapi.testclient import TestClient

from tests.conftest import API


def iso(value: datetime) -> str:
    return value.isoformat()


def make_session(client: TestClient, headers: dict, start: datetime, end: datetime, tag_id: int | None = None) -> dict:
    started = client.post(f"{API}/sessions/start", headers=headers, json={"tag_id": tag_id, "start_time": iso(start)})
    assert started.status_code == 201, started.text
    stopped = client.post(f"{API}/sessions/stop", headers=headers, json={"at": iso(end)})
    assert stopped.status_code == 200, stopped.text
    return stopped.json()


def log_distraction(
    client: TestClient, headers: dict, timestamp: datetime, session_id: int | None = None, reason="Phone"
):
    response = client.post(
        f"{API}/distractions/manual",
        headers=headers,
        json={"session_id": session_id, "reason": reason, "timestamp": iso(timestamp)},
    )
    assert response.status_code == 201, response.text
    return response.json()
