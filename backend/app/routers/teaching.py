from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_lecturer
from app.models import Course, TeachingMaterial, User
from app.rag.agent import generate_teaching_material
from app.routers.courses import _ensure_access
from app.schemas import TeachingMaterialOut, TeachingMaterialRequest

router = APIRouter(prefix="/courses/{course_id}/teaching", tags=["teaching"])


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
        persona=f"the lecturer for {course.title}",
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
