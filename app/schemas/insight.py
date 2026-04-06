from pydantic import BaseModel


class InsightItem(BaseModel):
    title: str
    message: str
    confidence: str


class InsightResponse(BaseModel):
    items: list[InsightItem]
