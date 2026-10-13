from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.insight import InsightResponse
from app.services.insight import build_insights

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/recommendations", response_model=InsightResponse)
def get_recommendations(db: DbSession, current_user: CurrentUser) -> InsightResponse:
    """Personal, data-backed insights from the last four weeks, most important first."""
    return build_insights(db, current_user)
