from typing import Literal

from pydantic import BaseModel


class InsightItem(BaseModel):
    # Stable identifier of the rule that produced it (e.g. "best_window"), useful for UI and tests.
    id: str
    # "improve": something to work on; "strength": keep doing it; "info": useful to know.
    kind: Literal["improve", "strength", "info"]
    title: str
    message: str
    # One concrete thing to try. Empty for pure strengths.
    tip: str
    # The numbers behind the insight, in plain words.
    evidence: str
    confidence: Literal["low", "medium", "high"]


class InsightResponse(BaseModel):
    # How many days of history the insights are based on.
    lookback_days: int
    sessions_analyzed: int
    items: list[InsightItem]
