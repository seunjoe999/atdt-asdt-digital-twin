from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_lecturer
from app.models import Course, TeachingMaterial, TeachingStyleProfile, User
from app.rag.agent import extract_teaching_style, generate_teaching_advice, generate_teaching_material
from app.routers.courses import _ensure_access
from app.schemas import (
    TeachingAdviceRequest,
    TeachingAdviceResponse,
    TeachingMaterialOut,
    TeachingMaterialRequest,
    TeachingStyleIn,
    TeachingStyleOut,
)

router = APIRouter(prefix="/courses/{course_id}/teaching", tags=["teaching"])


def persona_for(course: Course, db: Session) -> str:
    """The lecturer persona ATDT speaks/generates as — augmented with a
    captured teaching-style profile when one exists, so the twin actually
    sounds like this lecturer rather than a generic tutor."""
    base = f"the lecturer for {course.title}"
    profile = db.query(TeachingStyleProfile).filter(TeachingStyleProfile.course_id == course.id).first()
    if not profile:
        return base
    return f"{base}, who teaches in this observed style:\n{profile.style_summary}"


@router.post("/materials", response_model=TeachingMaterialOut, status_code=201)
async def create_material(
    course_id: int,
    payload: TeachingMaterialRequest,
    db: Session = Depends(get_db),
    lecturer: User = Depends(require_lecturer),
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, lecturer)

    content, _chunks = await generate_teaching_material(
        collection_name=course.chroma_collection_name,
        material_type=payload.type.value,
        topic=payload.topic,
        instructions=payload.instructions,
        persona=persona_for(course, db),
    )

    material = TeachingMaterial(
        course_id=course.id, type=payload.type, topic=payload.topic, content=content
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


@router.get("/materials", response_model=list[TeachingMaterialOut])
def list_materials(course_id: int, db: Session = Depends(get_db), lecturer: User = Depends(require_lecturer)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, lecturer)
    return db.query(TeachingMaterial).filter(TeachingMaterial.course_id == course.id).all()


@router.get("/materials/published", response_model=list[TeachingMaterialOut])
def list_published_materials(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The student-facing "read the course" feed: published teaching
    material only, readable by the lecturer or any enrolled student."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, user)
    return (
        db.query(TeachingMaterial)
        .filter(TeachingMaterial.course_id == course.id, TeachingMaterial.published.is_(True))
        .all()
    )


@router.post("/materials/{material_id}/publish", response_model=TeachingMaterialOut)
def publish_material(
    course_id: int,
    material_id: int,
    db: Session = Depends(get_db),
    lecturer: User = Depends(require_lecturer),
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, lecturer)

    material = db.get(TeachingMaterial, material_id)
    if not material or material.course_id != course.id:
        raise HTTPException(status_code=404, detail="Material not found")
    material.published = True
    db.commit()
    db.refresh(material)
    return material


@router.post("/advice", response_model=TeachingAdviceResponse)
async def generate_advice(
    course_id: int,
    payload: TeachingAdviceRequest,
    db: Session = Depends(get_db),
    lecturer: User = Depends(require_lecturer),
):
    """Real ATDT-generated advice for one student, grounded in this course's
    material — the lecturer supplies the student's current ASDT knowledge
    state (already loaded from ASDT's teacher/report by the frontend), and
    the Teacher Twin turns it into a concrete recommendation instead of a
    frontend-computed heuristic.
    """
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, lecturer)

    advice = await generate_teaching_advice(
        collection_name=course.chroma_collection_name,
        persona=persona_for(course, db),
        student_name=payload.student_name,
        overall_mastery=payload.overall_mastery,
        open_gaps=payload.open_gaps,
        topics=[(t.topic, t.mastery) for t in payload.topics],
    )
    return TeachingAdviceResponse(advice=advice)


@router.post("/style", response_model=TeachingStyleOut)
async def capture_style(
    course_id: int,
    payload: TeachingStyleIn,
    db: Session = Depends(get_db),
    lecturer: User = Depends(require_lecturer),
):
    """The "observes the teacher and teaches like them" feature: the lecturer
    pastes a lecture transcript/notes sample, ATDT distills a style
    descriptor from it, and every future generation/tutoring answer for this
    course folds that descriptor into its persona.
    """
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, lecturer)

    style_summary = await extract_teaching_style(payload.sample)

    profile = db.query(TeachingStyleProfile).filter(TeachingStyleProfile.course_id == course.id).first()
    if profile:
        profile.sample = payload.sample
        profile.style_summary = style_summary
    else:
        profile = TeachingStyleProfile(course_id=course.id, sample=payload.sample, style_summary=style_summary)
        db.add(profile)
    db.commit()
    db.refresh(profile)
    return TeachingStyleOut(has_profile=True, style_summary=profile.style_summary, updated_at=profile.updated_at)


@router.get("/style", response_model=TeachingStyleOut)
def get_style(
    course_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, user)

    profile = db.query(TeachingStyleProfile).filter(TeachingStyleProfile.course_id == course.id).first()
    if not profile:
        return TeachingStyleOut(has_profile=False)
    return TeachingStyleOut(has_profile=True, style_summary=profile.style_summary, updated_at=profile.updated_at)
