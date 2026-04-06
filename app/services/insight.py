from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, extract, func, select
from sqlalchemy.orm import Session

from app.models.distraction_event import DistractionEvent
from app.models.focus_session import FocusSession
from app.schemas.insight import InsightItem


def build_insights(db: Session, user_id: int) -> list[InsightItem]:
    insights: list[InsightItem] = []
    since = datetime.now(UTC) - timedelta(days=14)

    hour_rows = db.execute(
        select(
            extract("hour", FocusSession.start_time).label("hour"),
            func.coalesce(func.sum(FocusSession.duration_seconds), 0).label("focus_seconds"),
        )
        .where(
            and_(
                FocusSession.user_id == user_id,
                FocusSession.start_time >= since,
                FocusSession.duration_seconds > 0,
            )
        )
        .group_by(extract("hour", FocusSession.start_time))
        .order_by(func.coalesce(func.sum(FocusSession.duration_seconds), 0).desc())
        .limit(1)
    ).first()

    if hour_rows:
        hour = int(hour_rows.hour)
        next_hour = (hour + 2) % 24
        insights.append(
            InsightItem(
                title="Best focus window",
                message=f"Your strongest focus block is around {hour:02d}:00–{next_hour:02d}:00.",
                confidence="medium",
            )
        )

    evening_distractions = db.scalar(
        select(func.count(DistractionEvent.id)).where(
            and_(
                DistractionEvent.user_id == user_id,
                DistractionEvent.timestamp >= since,
                extract("hour", DistractionEvent.timestamp) >= 18,
            )
        )
    ) or 0

    if evening_distractions >= 5:
        insights.append(
            InsightItem(
                title="Evening distraction pattern",
                message="Distractions are higher after 6 PM. Try shorter sessions in the evening.",
                confidence="medium",
            )
        )

    avg_session_seconds = db.scalar(
        select(func.coalesce(func.avg(FocusSession.duration_seconds), 0)).where(
            and_(
                FocusSession.user_id == user_id,
                FocusSession.start_time >= since,
                FocusSession.duration_seconds > 0,
            )
        )
    ) or 0

    if avg_session_seconds > 45 * 60:
        insights.append(
            InsightItem(
                title="Session length optimization",
                message="Average sessions are long. Consider adding short breaks every 30–40 minutes.",
                confidence="low",
            )
        )

    if not insights:
        insights.append(
            InsightItem(
                title="Not enough data yet",
                message="Keep tracking sessions and distractions for a few days to unlock personalized insights.",
                confidence="low",
            )
        )

    return insights
