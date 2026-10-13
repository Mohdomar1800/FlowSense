"""Live updates over WebSocket.

Connect to /api/v1/ws?token=<access token>. The server sends a `snapshot` with the current session
right away, then `session.updated`, `session.deleted` and `distraction.logged` events as they happen.
Sending the text "ping" gets "pong" back (keep-alive).
"""

import asyncio
import contextlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.errors import UnauthorizedError
from app.core.events import get_broker
from app.db.session import get_session_factory
from app.services.auth import user_for_token
from app.services.session import get_active_session, session_response

router = APIRouter(tags=["live"])

UNAUTHORIZED_CLOSE_CODE = 4401


def _authenticate_and_snapshot(session_factory, token: str) -> tuple[int, dict] | None:
    with session_factory() as db:
        try:
            user = user_for_token(db, token)
        except UnauthorizedError:
            return None
        active = get_active_session(db, user)
        snapshot = session_response(db, active).model_dump(mode="json") if active else None
        return user.id, {"type": "snapshot", "session": snapshot}


@router.websocket("/ws")
async def live_updates(
    websocket: WebSocket,
    session_factory: Annotated[Callable[[], AbstractContextManager[Session]], Depends(get_session_factory)],
    token: str = Query(default=""),
) -> None:
    await websocket.accept()
    auth = await asyncio.to_thread(_authenticate_and_snapshot, session_factory, token)
    if auth is None:
        await websocket.close(code=UNAUTHORIZED_CLOSE_CODE, reason="Invalid or expired token")
        return
    user_id, snapshot = auth

    async with get_broker().subscribe(user_id) as messages:
        await websocket.send_json(snapshot)

        async def forward() -> None:
            async for message in messages:
                await websocket.send_json(message)

        async def receive() -> None:
            while True:
                if await websocket.receive_text() == "ping":
                    await websocket.send_text("pong")

        tasks = [asyncio.create_task(forward()), asyncio.create_task(receive())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                    await task
