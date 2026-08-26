import logging
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_lecturer
from app.models import Course, Document, DocumentStatus, User
from app.rag.ingest import ingest_document
from app.routers.courses import _ensure_access
from app.schemas import DocumentOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/courses/{course_id}/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def _get_course_or_404(db: Session, course_id: int, user: User) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, user)
    return course


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    course_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    db: Session = Depends(get_db),
    lecturer: User = Depends(require_lecturer),
):
    course = _get_course_or_404(db, course_id, lecturer)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, and TXT files are supported")

    document = Document(course_id=course.id, filename=file.filename, status=DocumentStatus.PROCESSING)
    db.add(document)
    db.commit()
    db.refresh(document)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.write(file.file.read())
    tmp.close()

    background_tasks.add_task(
        _run_ingestion, course.id, document.id, course.chroma_collection_name, tmp.name, file.filename
    )
    return document


def _run_ingestion(course_id, document_id, collection_name, tmp_path, filename):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        try:
            chunk_count = ingest_document(
                course_id=course_id,
                document_id=document_id,
                collection_name=collection_name,
                file_path=tmp_path,
                filename=filename,
            )
            document.status = DocumentStatus.READY
            document.chunk_count = chunk_count
        except Exception as exc:  # noqa: BLE001 - surface any extraction/embedding failure
            log.exception("Ingestion failed for document %s", document_id)
            document.status = DocumentStatus.FAILED
            document.error = str(exc)
        db.commit()
    finally:
        db.close()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.get("", response_model=list[DocumentOut])
def list_documents(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Readable by the course's lecturer or any enrolled student — this is
    what lets a student see what ATDT has actually learned from."""
    course = _get_course_or_404(db, course_id, user)
    return db.query(Document).filter(Document.course_id == course.id).all()
