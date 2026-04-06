from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.distraction import (
    DistractionCreateRequest,
    DistractionListResponse,
    DistractionResponse,
    DistractionSummaryResponse,
    InferredDistractionRequest,
)
from app.services.distraction import (
    get_daily_summary,
    list_distractions,
    log_inferred_distraction,
    log_manual_distraction,
)

router = APIRouter(prefix="/distractions", tags=["distractions"])


@router.post("/manual", response_model=DistractionResponse, status_code=201)
def create_manual_distraction(
    payload: DistractionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DistractionResponse:
    event = log_manual_distraction(
        db=db,
        user_id=current_user.id,
        session_id=payload.session_id,
        reason=payload.reason,
        timestamp=payload.timestamp,
    )
    return DistractionResponse(
        id=event.id,
        user_id=event.user_id,
        session_id=event.session_id,
        event_type=event.event_type.value,
        reason=event.reason,
        timestamp=event.timestamp,
    )


@router.post("/inferred", response_model=DistractionResponse, status_code=201)
def create_inferred_distraction(
    payload: InferredDistractionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DistractionResponse:
    event = log_inferred_distraction(
        db=db,
        user_id=current_user.id,
        session_id=payload.session_id,
        inactive_minutes=payload.inactive_minutes,
        reason=payload.reason,
        timestamp=payload.timestamp,
    )
    return DistractionResponse(
        id=event.id,
        user_id=event.user_id,
        session_id=event.session_id,
        event_type=event.event_type.value,
        reason=event.reason,
        timestamp=event.timestamp,
    )


@router.get("", response_model=DistractionListResponse)
def get_distractions(
    day: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DistractionListResponse:
    items, total_count = list_distractions(db=db, user_id=current_user.id, day=day, limit=limit, offset=offset)
    return DistractionListResponse(
        items=[
            DistractionResponse(
                id=item.id,
                user_id=item.user_id,
                session_id=item.session_id,
                event_type=item.event_type.value,
                reason=item.reason,
                timestamp=item.timestamp,
            )
            for item in items
        ],
        total_count=total_count,
    )


@router.get("/summary/daily", response_model=DistractionSummaryResponse)
def get_distraction_daily_summary(
    day: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DistractionSummaryResponse:
    total, manual, inferred = get_daily_summary(db=db, user_id=current_user.id, day=day)
    return DistractionSummaryResponse(
        day=day,
        total_events=total,
        manual_events=manual,
        inferred_events=inferred,
    )
