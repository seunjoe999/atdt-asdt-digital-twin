from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Course, CourseMessage, User
from app.routers.courses import _ensure_access
from app.schemas import CourseMessageCreate, CourseMessageOut

router = APIRouter(prefix="/courses/{course_id}/messages", tags=["messages"])


def _get_course_or_404(db: Session, course_id: int, user: User) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, user)
    return course


def _to_out(message: CourseMessage, sender: User) -> CourseMessageOut:
    return CourseMessageOut(
        id=message.id,
        course_id=message.course_id,
        sender_id=message.sender_id,
        sender_name=sender.full_name,
        sender_role=sender.role,
        content=message.content,
        created_at=message.created_at,
    )


@router.get("", response_model=list[CourseMessageOut])
def list_messages(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    course = _get_course_or_404(db, course_id, user)
    messages = (
        db.query(CourseMessage)
        .filter(CourseMessage.course_id == course.id)
        .order_by(CourseMessage.created_at.asc())
        .all()
    )
    senders = {u.id: u for u in db.query(User).filter(User.id.in_({m.sender_id for m in messages})).all()}
    return [_to_out(m, senders[m.sender_id]) for m in messages]


@router.post("", response_model=CourseMessageOut, status_code=201)
def post_message(
    course_id: int,
    payload: CourseMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = _get_course_or_404(db, course_id, user)
    message = CourseMessage(course_id=course.id, sender_id=user.id, content=payload.content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return _to_out(message, user)
