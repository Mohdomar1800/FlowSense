from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.session_tag import SessionTag
from app.models.user import User
from app.schemas.tag import TagCreate, TagUpdate
from app.services.analytics import invalidate_productivity_cache


def get_owned_tag(db: Session, user: User, tag_id: int) -> SessionTag:
    tag = db.get(SessionTag, tag_id)
    if tag is None or tag.user_id != user.id:
        raise NotFoundError("Tag not found")
    return tag


def _name_taken(db: Session, user: User, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(SessionTag.id).where(SessionTag.user_id == user.id, func.lower(SessionTag.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(SessionTag.id != exclude_id)
    return db.scalar(stmt) is not None


def list_tags(db: Session, user: User) -> list[SessionTag]:
    return list(db.scalars(select(SessionTag).where(SessionTag.user_id == user.id).order_by(SessionTag.name)))


def create_tag(db: Session, user: User, payload: TagCreate) -> SessionTag:
    if _name_taken(db, user, payload.name):
        raise ConflictError("A tag with this name already exists")
    tag = SessionTag(user_id=user.id, name=payload.name, color=payload.color)
    db.add(tag)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A tag with this name already exists") from exc
    db.refresh(tag)
    return tag


def update_tag(db: Session, user: User, tag_id: int, payload: TagUpdate) -> SessionTag:
    tag = get_owned_tag(db, user, tag_id)
    if payload.name is not None:
        if _name_taken(db, user, payload.name, exclude_id=tag.id):
            raise ConflictError("A tag with this name already exists")
        tag.name = payload.name
    if payload.color is not None:
        tag.color = payload.color
    db.commit()
    db.refresh(tag)
    invalidate_productivity_cache(user.id)
    return tag


def delete_tag(db: Session, user: User, tag_id: int) -> None:
    tag = get_owned_tag(db, user, tag_id)
    db.delete(tag)  # sessions keep existing with tag_id set to NULL
    db.commit()
    invalidate_productivity_cache(user.id)
