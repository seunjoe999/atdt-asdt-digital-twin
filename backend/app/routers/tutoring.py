from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_student
from app.models import Conversation, Course, Message, MessageRole, User
from app.rag.agent import answer_question
from app.routers.courses import _ensure_access
from app.schemas import Citation, MessageOut, TutorAnswer, TutorQuery

router = APIRouter(prefix="/courses/{course_id}/tutoring", tags=["tutoring"])

HISTORY_MESSAGES = 6  # last N messages folded into the prompt for context


@router.post("/query", response_model=TutorAnswer)
async def query_tutor(
    course_id: int,
    payload: TutorQuery,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, student)

    if payload.conversation_id:
        conversation = db.get(Conversation, payload.conversation_id)
        if not conversation or conversation.student_id != student.id or conversation.course_id != course.id:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(student_id=student.id, course_id=course.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    history_msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(HISTORY_MESSAGES)
        .all()
    )
    history_msgs.reverse()
    history_text = "\n".join(f"{m.role.value}: {m.content}" for m in history_msgs)

    answer, chunks = await answer_question(
        collection_name=course.chroma_collection_name,
        question=payload.question,
        persona=f"the lecturer for {course.title}",
        history=history_text,
    )

    citations = [
        Citation(
            source_document=c.source_document,
            page_number=c.page_number,
            chunk_index=c.chunk_index,
            excerpt=(c.text[:280] + "...") if len(c.text) > 280 else c.text,
        )
        for c in chunks
    ]

    db.add(Message(conversation_id=conversation.id, role=MessageRole.USER, content=payload.question))
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=answer,
            citations=[c.model_dump() for c in citations],
        )
    )
    db.commit()

    return TutorAnswer(conversation_id=conversation.id, answer=answer, citations=citations)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages(
    course_id: int,
    conversation_id: int,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.student_id != student.id or conversation.course_id != course_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return db.query(Message).filter(Message.conversation_id == conversation.id).order_by(Message.id).all()
