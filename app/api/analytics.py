from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.analytics import ProductivityAnalyticsResponse
from app.services.analytics import get_productivity_analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/productivity", response_model=ProductivityAnalyticsResponse)
def get_productivity_report(
    period: str = Query(default="week", pattern="^(day|week|month)$"),
    reference_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductivityAnalyticsResponse:
    overview, focus_by_tag, distractions_by_hour = get_productivity_analytics(
        db=db,
        user_id=current_user.id,
        period=period,
        reference_date=reference_date,
    )
    return ProductivityAnalyticsResponse(
        overview=overview,
        focus_by_tag=focus_by_tag,
        distractions_by_hour=distractions_by_hour,
    )
