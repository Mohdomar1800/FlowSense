from datetime import date
from typing import Literal

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentUser, DbSession
from app.schemas.session import (
    SessionActionRequest,
    SessionDetailResponse,
    SessionResponse,
    SessionStartRequest,
    SessionSummary,
    SessionTransitionResponse,
    SessionUpdateRequest,
)
from app.services import session as service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/start", response_model=SessionResponse, status_code=201)
def start_session(payload: SessionStartRequest, db: DbSession, current_user: CurrentUser) -> SessionResponse:
    return service.start_session(db, current_user, payload.tag_id, payload.intent, payload.start_time)


@router.post("/pause", response_model=SessionResponse)
def pause_session(
    db: DbSession, current_user: CurrentUser, payload: SessionActionRequest | None = None
) -> SessionResponse:
    return service.pause_session(db, current_user, payload.at if payload else None)


@router.post("/resume", response_model=SessionTransitionResponse)
def resume_session(
    db: DbSession, current_user: CurrentUser, payload: SessionActionRequest | None = None
) -> SessionTransitionResponse:
    session, previous = service.resume_session(db, current_user, payload.at if payload else None)
    return SessionTransitionResponse(session=session, previous_session=previous, split=previous is not None)


@router.post("/stop", response_model=SessionResponse)
def stop_session(
    db: DbSession, current_user: CurrentUser, payload: SessionActionRequest | None = None
) -> SessionResponse:
    return service.stop_session(db, current_user, payload.at if payload else None)


@router.get("/active", response_model=SessionResponse | None)
def get_active_session(db: DbSession, current_user: CurrentUser) -> SessionResponse | None:
    session = service.get_active_session(db, current_user)
    return service.session_response(db, session) if session else None


@router.get("", response_model=SessionSummary)
def list_sessions(
    db: DbSession,
    current_user: CurrentUser,
    period: Literal["day", "week", "month", "custom"] = "day",
    reference_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> SessionSummary:
    sessions, total = service.list_sessions(db, current_user, period, reference_date, start_date, end_date)
    return SessionSummary(sessions=sessions, total_focus_seconds=total)


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: int, db: DbSession, current_user: CurrentUser) -> SessionDetailResponse:
    return service.get_session_detail(db, current_user, session_id)


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: int, payload: SessionUpdateRequest, db: DbSession, current_user: CurrentUser
) -> SessionResponse:
    return service.update_session(db, current_user, session_id, payload)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, db: DbSession, current_user: CurrentUser) -> Response:
    service.delete_session(db, current_user, session_id)
    return Response(status_code=204)
