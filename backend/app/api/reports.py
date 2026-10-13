from datetime import date
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import CurrentUser, DbSession
from app.core.errors import BadRequestError
from app.models.report_log import ReportLog
from app.schemas.report import ReportListResponse, ReportLogResponse
from app.services import report as service
from app.services.report_export import render_markdown, report_filename

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ReportListResponse)
def list_reports(
    db: DbSession,
    current_user: CurrentUser,
    report_type: Literal["daily", "weekly"] | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> ReportListResponse:
    if start_date and end_date and end_date < start_date:
        raise BadRequestError("end_date must be >= start_date")
    items, total = service.list_reports(db, current_user, report_type, limit, offset, start_date, end_date)
    return ReportListResponse(items=[ReportLogResponse.model_validate(i) for i in items], total_count=total)


@router.get("/{report_id}", response_model=ReportLogResponse)
def get_report(report_id: int, db: DbSession, current_user: CurrentUser) -> ReportLog:
    return service.get_report(db, current_user, report_id)


@router.get("/{report_id}/export", response_class=Response)
def export_report(report_id: int, db: DbSession, current_user: CurrentUser) -> Response:
    """The report as a Markdown file download."""
    report = service.get_report(db, current_user, report_id)
    return Response(
        content=render_markdown(report),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report_filename(report)}"'},
    )
