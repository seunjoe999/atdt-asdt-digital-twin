from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_lecturer, require_student
from app.models import Course, Enrollment, User, UserRole
from app.schemas import CourseCreate, CourseOut, EnrolRequest, EnrolledStudentOut

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("", response_model=CourseOut, status_code=201)
def create_course(
    payload: CourseCreate, db: Session = Depends(get_db), lecturer: User = Depends(require_lecturer)
):
    course = Course(
        title=payload.title,
        description=payload.description,
        subject_area=payload.subject_area,
        lecturer_id=lecturer.id,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == UserRole.LECTURER:
        return db.query(Course).filter(Course.lecturer_id == user.id).all()

    enrolled_ids = [
        e.course_id for e in db.query(Enrollment).filter(Enrollment.student_id == user.id)
    ]
    if not enrolled_ids:
        return []
    return db.query(Course).filter(Course.id.in_(enrolled_ids)).all()


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, user)
    return course


@router.post("/enrol", response_model=CourseOut)
def enrol(
    payload: EnrolRequest, db: Session = Depends(get_db), student: User = Depends(require_student)
):
    course = db.query(Course).filter(Course.enrolment_code == payload.enrolment_code).first()
    if not course:
        raise HTTPException(status_code=404, detail="No course matches that enrolment code")

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student.id, Enrollment.course_id == course.id)
        .first()
    )
    if not existing:
        db.add(Enrollment(student_id=student.id, course_id=course.id))
        db.commit()
    return course


@router.get("/{course_id}/students", response_model=list[EnrolledStudentOut])
def list_students(
    course_id: int, db: Session = Depends(get_db), lecturer: User = Depends(require_lecturer)
):
    """Lets the Teacher Twin see who's enrolled, so it knows which Student
    Twins it can look up mastery/gaps for."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, lecturer)

    student_ids = [e.student_id for e in db.query(Enrollment).filter(Enrollment.course_id == course.id)]
    if not student_ids:
        return []
    return db.query(User).filter(User.id.in_(student_ids)).all()


def _ensure_access(db: Session, course: Course, user: User) -> None:
    """Raise 403 unless the user is the course's lecturer or an enrolled student."""
    if user.role == UserRole.LECTURER:
        if course.lecturer_id != user.id:
            raise HTTPException(status_code=403, detail="Not your course")
        return

    enrolled = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == user.id, Enrollment.course_id == course.id)
        .first()
    )
    if not enrolled:
        raise HTTPException(status_code=403, detail="Not enrolled in this course")
