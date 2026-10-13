from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, DbSession
from app.models.session_tag import SessionTag
from app.schemas.tag import TagCreate, TagResponse, TagUpdate
from app.services.tag import create_tag, delete_tag, list_tags, update_tag

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagResponse])
def get_tags(db: DbSession, current_user: CurrentUser) -> list[SessionTag]:
    return list_tags(db, current_user)


@router.post("", response_model=TagResponse, status_code=201)
def post_tag(payload: TagCreate, db: DbSession, current_user: CurrentUser) -> SessionTag:
    return create_tag(db, current_user, payload)


@router.patch("/{tag_id}", response_model=TagResponse)
def patch_tag(tag_id: int, payload: TagUpdate, db: DbSession, current_user: CurrentUser) -> SessionTag:
    return update_tag(db, current_user, tag_id, payload)


@router.delete("/{tag_id}", status_code=204)
def remove_tag(tag_id: int, db: DbSession, current_user: CurrentUser) -> Response:
    delete_tag(db, current_user, tag_id)
    return Response(status_code=204)
