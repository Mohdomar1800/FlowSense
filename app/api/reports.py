from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.schemas.report import ReportListResponse, ReportLogResponse
from app.services.report import list_reports as list_reports_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ReportListResponse)
def list_reports(
    report_type: str | None = Query(default=None, pattern="^(daily|weekly)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportListResponse:
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_date must be >= start_date")

    items, total_count = list_reports_service(
        db=db,
        user_id=current_user.id,
        report_type=report_type,
        limit=limit,
        offset=offset,
        start_date=start_date,
        end_date=end_date,
    )
    return ReportListResponse(
        items=[
            ReportLogResponse(
                id=item.id,
                user_id=item.user_id,
                report_type=item.report_type,
                content=item.content,
                created_at=item.created_at,
            )
            for item in items
        ],
        total_count=total_count,
    )
