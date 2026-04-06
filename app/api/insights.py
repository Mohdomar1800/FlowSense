from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.insight import InsightResponse
from app.services.insight import build_insights

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/recommendations", response_model=InsightResponse)
def get_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightResponse:
    items = build_insights(db=db, user_id=current_user.id)
    return InsightResponse(items=items)
