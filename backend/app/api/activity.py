from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, DbSession
from app.models.activity import ActivityRule
from app.schemas.activity import ActivityReport, ActivityResult, RuleCreate, RuleResponse
from app.services import activity as service

router = APIRouter(prefix="/activity", tags=["activity"])


@router.post("", response_model=ActivityResult)
def report_activity(payload: ActivityReport, db: DbSession, current_user: CurrentUser) -> ActivityResult:
    """Called by the desktop agent when the foreground window changes."""
    return service.record_activity(db, current_user, payload.app, payload.title, payload.at)


@router.get("/rules", response_model=list[RuleResponse])
def list_rules(db: DbSession, current_user: CurrentUser) -> list[ActivityRule]:
    return service.list_rules(db, current_user)


@router.post("/rules", response_model=RuleResponse, status_code=201)
def create_rule(payload: RuleCreate, db: DbSession, current_user: CurrentUser) -> ActivityRule:
    return service.create_rule(db, current_user, payload.pattern, payload.kind)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: DbSession, current_user: CurrentUser) -> Response:
    service.delete_rule(db, current_user, rule_id)
    return Response(status_code=204)
