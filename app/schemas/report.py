from datetime import datetime

from pydantic import BaseModel


class ReportLogResponse(BaseModel):
    id: int
    user_id: int
    report_type: str
    content: str
    created_at: datetime


class ReportListResponse(BaseModel):
    items: list[ReportLogResponse]
    total_count: int
