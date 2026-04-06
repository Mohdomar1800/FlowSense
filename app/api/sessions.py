from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.session import (
    SessionListQuery,
    SessionPauseRequest,
    SessionResponse,
    SessionStartRequest,
    SessionStopRequest,
    SessionSummary,
)
from app.services.session import list_sessions, pause_session, start_session, stop_session

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/start", response_model=SessionResponse, status_code=201)
def start_focus_session(
    payload: SessionStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    return start_session(db=db, user_id=current_user.id, tag_id=payload.tag_id, start_time=payload.start_time)


@router.post("/stop", response_model=SessionResponse)
def stop_focus_session(
    payload: SessionStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    return stop_session(db=db, user_id=current_user.id, end_time=payload.end_time)


@router.post("/pause", response_model=dict)
def pause_focus_session(
    payload: SessionPauseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    closed_session, resumed_session = pause_session(
        db=db,
        user_id=current_user.id,
        paused_at=payload.paused_at,
        resumed_at=payload.resumed_at,
    )
    return {
        "closed_session": SessionResponse.model_validate(closed_session),
        "resumed_session": SessionResponse.model_validate(resumed_session) if resumed_session else None,
        "split": resumed_session is not None,
    }


@router.get("", response_model=SessionSummary)
def get_sessions(
    period: str = Query(default="day", pattern="^(day|week|month|custom)$"),
    reference_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionSummary:
    query = SessionListQuery(
        period=period,
        reference_date=reference_date,
        start_date=start_date,
        end_date=end_date,
    )
    sessions, total_focus_seconds = list_sessions(
        db=db,
        user_id=current_user.id,
        period=query.period,
        reference_date=query.reference_date,
        start_date=query.start_date,
        end_date=query.end_date,
    )
    return SessionSummary(
        sessions=[SessionResponse.model_validate(item) for item in sessions],
        total_focus_seconds=total_focus_seconds,
    )
