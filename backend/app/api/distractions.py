from datetime import date

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentUser, DbSession
from app.core.timeutils import local_today
from app.models.distraction_event import DistractionEvent, DistractionType
from app.schemas.distraction import (
    DetectedDistractionRequest,
    DistractionCreateRequest,
    DistractionDismissRequest,
    DistractionEndRequest,
    DistractionListResponse,
    DistractionResponse,
    DistractionSummaryResponse,
    InferredDistractionRequest,
)
from app.services import distraction as service

router = APIRouter(prefix="/distractions", tags=["distractions"])


@router.post("/manual", response_model=DistractionResponse, status_code=201)
def create_manual_distraction(
    payload: DistractionCreateRequest, db: DbSession, current_user: CurrentUser
) -> DistractionEvent:
    return service.log_manual_distraction(db, current_user, payload.session_id, payload.reason, payload.timestamp)


@router.post("/inferred", response_model=DistractionResponse, status_code=201)
def create_inferred_distraction(
    payload: InferredDistractionRequest, db: DbSession, current_user: CurrentUser
) -> DistractionEvent:
    return service.log_inferred_distraction(
        db, current_user, payload.session_id, payload.inactive_minutes, payload.reason, payload.timestamp
    )


@router.post("/detected", response_model=DistractionResponse, status_code=201)
def create_detected_distraction(
    payload: DetectedDistractionRequest, db: DbSession, current_user: CurrentUser
) -> DistractionEvent:
    """Screen/camera distraction from the desktop app; attached to the running session."""
    return service.log_detected_distraction(
        db, current_user, DistractionType(payload.source), payload.subject, payload.reason, payload.timestamp
    )


@router.post("/{distraction_id}/end", response_model=DistractionResponse)
def end_distraction(
    distraction_id: int, db: DbSession, current_user: CurrentUser, payload: DistractionEndRequest | None = None
) -> DistractionEvent:
    return service.end_distraction(db, current_user, distraction_id, payload.at if payload else None)


@router.post("/{distraction_id}/dismiss", status_code=204)
def dismiss_distraction(
    distraction_id: int, db: DbSession, current_user: CurrentUser, payload: DistractionDismissRequest | None = None
) -> Response:
    """Not a distraction: remove it, and optionally always allow its app/site from now on."""
    service.dismiss_distraction(db, current_user, distraction_id, payload.always_allow if payload else False)
    return Response(status_code=204)


@router.get("", response_model=DistractionListResponse)
def get_distractions(
    db: DbSession,
    current_user: CurrentUser,
    day: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DistractionListResponse:
    items, total = service.list_distractions(db, current_user, day=day, limit=limit, offset=offset)
    return DistractionListResponse(items=[DistractionResponse.model_validate(i) for i in items], total_count=total)


@router.get("/summary/daily", response_model=DistractionSummaryResponse)
def get_distraction_daily_summary(
    db: DbSession, current_user: CurrentUser, day: date | None = Query(default=None)
) -> DistractionSummaryResponse:
    resolved_day = day or local_today(current_user.timezone)
    counts = service.get_daily_summary(db, current_user, resolved_day)
    return DistractionSummaryResponse(
        day=resolved_day,
        total_events=sum(counts.values()),
        manual_events=counts[DistractionType.MANUAL],
        inferred_events=counts[DistractionType.INFERRED],
        screen_events=counts[DistractionType.SCREEN],
        camera_events=counts[DistractionType.CAMERA],
    )
