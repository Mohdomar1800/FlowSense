from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.analytics import ProductivityAnalyticsResponse
from app.schemas.dashboard import DashboardResponse
from app.services.analytics import get_productivity_analytics
from app.services.dashboard import get_dashboard

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/productivity", response_model=ProductivityAnalyticsResponse)
def get_productivity_report(
    db: DbSession,
    current_user: CurrentUser,
    period: Literal["day", "week", "month"] = "week",
    reference_date: date | None = Query(default=None),
) -> ProductivityAnalyticsResponse:
    return get_productivity_analytics(db, current_user, period, reference_date)


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard_data(
    db: DbSession,
    current_user: CurrentUser,
    period: Literal["day", "week", "month", "custom"] = "week",
    reference_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> DashboardResponse:
    """Everything the dashboard shows for one period, including a comparison with the period before."""
    return get_dashboard(db, current_user, period, reference_date, start_date, end_date)
