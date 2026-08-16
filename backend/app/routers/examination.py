from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_lecturer, require_student
from app.models import (
    Assessment,
    AssessmentStatus,
    Attempt,
    Course,
    Question,
    QuestionType,
    Response as ResponseModel,
    User,
)
from app.rag.assessment_agent import generate_questions, grade_saq
from app.routers.courses import _ensure_access
from app.schemas import (
    AssessmentCreateRequest,
    AssessmentOut,
    AttemptResultOut,
    MyAttemptOut,
    QuestionEditRequest,
    QuestionOut,
    QuestionWithAnswerOut,
    SubmitAttemptRequest,
)

router = APIRouter(prefix="/courses/{course_id}/examination", tags=["examination"])


def _get_course(db: Session, course_id: int, user: User) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, user)
    return course


def _get_assessment(db: Session, course: Course, assessment_id: int) -> Assessment:
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.course_id != course.id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return assessment


# ---------- Lecturer: generation & review ----------


@router.post("/assessments", response_model=AssessmentOut, status_code=201)
async def create_assessment(
    course_id: int,
    payload: AssessmentCreateRequest,
    db: Session = Depends(get_db),
    lecturer: User = Depends(require_lecturer),
):
    course = _get_course(db, course_id, lecturer)

    assessment = Assessment(
        course_id=course.id,
        title=payload.title,
        topic=payload.topic,
        mcq_count=payload.mcq_count,
        saq_count=payload.saq_count,
        time_limit_minutes=payload.time_limit_minutes,
        status=AssessmentStatus.DRAFT,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    generated = await generate_questions(
        collection_name=course.chroma_collection_name,
        topic=payload.topic,
        mcq_count=payload.mcq_count,
        saq_count=payload.saq_count,
    )

    order = 0
    for mcq in generated.get("mcqs", []):
        db.add(
            Question(
                assessment_id=assessment.id,
                type=QuestionType.MCQ,
                text=mcq["text"],
                options=mcq["options"],
                correct_answer=mcq["correct_answer"],
                order=order,
            )
        )
        order += 1
    for saq in generated.get("saqs", []):
        db.add(
            Question(
                assessment_id=assessment.id,
                type=QuestionType.SAQ,
                text=saq["text"],
                rubric=saq["rubric"],
                order=order,
            )
        )
        order += 1
    db.commit()
    return assessment


@router.get("/assessments", response_model=list[AssessmentOut])
def list_assessments(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_lecturer)):
    course = _get_course(db, course_id, user)
    return db.query(Assessment).filter(Assessment.course_id == course.id).all()


@router.get("/assessments/{assessment_id}/review", response_model=list[QuestionWithAnswerOut])
def review_questions(
    course_id: int, assessment_id: int, db: Session = Depends(get_db), lecturer: User = Depends(require_lecturer)
):
    course = _get_course(db, course_id, lecturer)
    assessment = _get_assessment(db, course, assessment_id)
    return (
        db.query(Question)
        .filter(Question.assessment_id == assessment.id)
        .order_by(Question.order)
        .all()
    )


@router.patch("/assessments/{assessment_id}/questions/{question_id}", response_model=QuestionWithAnswerOut)
def edit_question(
    course_id: int,
    assessment_id: int,
    question_id: int,
    payload: QuestionEditRequest,
    db: Session = Depends(get_db),
    lecturer: User = Depends(require_lecturer),
):
    course = _get_course(db, course_id, lecturer)
    assessment = _get_assessment(db, course, assessment_id)
    question = db.get(Question, question_id)
    if not question or question.assessment_id != assessment.id:
        raise HTTPException(status_code=404, detail="Question not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(question, field, value)
    db.commit()
    db.refresh(question)
    return question


@router.delete("/assessments/{assessment_id}/questions/{question_id}", status_code=204)
def delete_question(
    course_id: int,
    assessment_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    lecturer: User = Depends(require_lecturer),
):
    course = _get_course(db, course_id, lecturer)
    assessment = _get_assessment(db, course, assessment_id)
    question = db.get(Question, question_id)
    if not question or question.assessment_id != assessment.id:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(question)
    db.commit()


@router.post("/assessments/{assessment_id}/publish", response_model=AssessmentOut)
def publish_assessment(
    course_id: int, assessment_id: int, db: Session = Depends(get_db), lecturer: User = Depends(require_lecturer)
):
    course = _get_course(db, course_id, lecturer)
    assessment = _get_assessment(db, course, assessment_id)
    assessment.status = AssessmentStatus.PUBLISHED
    db.commit()
    db.refresh(assessment)
    return assessment


# ---------- Student: delivery, submission, grading ----------


@router.get("/assessments/published", response_model=list[AssessmentOut])
def list_published_assessments(
    course_id: int, db: Session = Depends(get_db), student: User = Depends(require_student)
):
    course = _get_course(db, course_id, student)
    return (
        db.query(Assessment)
        .filter(Assessment.course_id == course.id, Assessment.status == AssessmentStatus.PUBLISHED)
        .all()
    )


@router.get("/assessments/{assessment_id}/take", response_model=list[QuestionOut])
def take_assessment(
    course_id: int, assessment_id: int, db: Session = Depends(get_db), student: User = Depends(require_student)
):
    course = _get_course(db, course_id, student)
    assessment = _get_assessment(db, course, assessment_id)
    if assessment.status != AssessmentStatus.PUBLISHED:
        raise HTTPException(status_code=403, detail="Assessment is not published")

    questions = (
        db.query(Question).filter(Question.assessment_id == assessment.id).order_by(Question.order).all()
    )
    return questions


@router.post("/assessments/{assessment_id}/submit", response_model=AttemptResultOut)
async def submit_attempt(
    course_id: int,
    assessment_id: int,
    payload: SubmitAttemptRequest,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
):
    from app.models import now_utc

    course = _get_course(db, course_id, student)
    assessment = _get_assessment(db, course, assessment_id)
    if assessment.status != AssessmentStatus.PUBLISHED:
        raise HTTPException(status_code=403, detail="Assessment is not published")

    attempt = Attempt(student_id=student.id, assessment_id=assessment.id)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    questions_by_id = {
        q.id: q for q in db.query(Question).filter(Question.assessment_id == assessment.id)
    }

    total = 0.0
    graded = 0
    for answer in payload.answers:
        question = questions_by_id.get(answer.question_id)
        if not question:
            continue

        if question.type == QuestionType.MCQ:
            score = 1.0 if answer.answer.strip() == question.correct_answer.strip() else 0.0
            feedback = "Correct." if score == 1.0 else f"Incorrect. The correct answer is: {question.correct_answer}"
        else:
            score, feedback = await grade_saq(
                question_text=question.text, rubric=question.rubric, student_answer=answer.answer
            )

        db.add(
            ResponseModel(
                attempt_id=attempt.id,
                question_id=question.id,
                student_answer=answer.answer,
                score=score,
                feedback=feedback,
            )
        )
        total += score
        graded += 1

    attempt.total_score = round((total / graded) * 100, 2) if graded else 0.0
    attempt.submitted_at = now_utc()
    db.commit()
    db.refresh(attempt)
    return attempt


@router.get("/attempts/{attempt_id}/results", response_model=AttemptResultOut)
def get_results(
    course_id: int, attempt_id: int, db: Session = Depends(get_db), student: User = Depends(require_student)
):
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.student_id != student.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt


@router.get("/my-attempts", response_model=list[MyAttemptOut])
def my_attempts(course_id: int, db: Session = Depends(get_db), student: User = Depends(require_student)):
    """A student's own submitted attempts in this course, topic included.

    This is the read surface ASDT (or any other consumer acting on the
    student's behalf, using the student's own bearer token) uses to build a
    per-topic mastery model — the "Acquisition and Tracking Layer" of the
    ASDT thesis's six-layer CDDT architecture (Section 3.4.1).
    """
    course = _get_course(db, course_id, student)
    rows = (
        db.query(Attempt, Assessment)
        .join(Assessment, Attempt.assessment_id == Assessment.id)
        .filter(
            Attempt.student_id == student.id,
            Assessment.course_id == course.id,
            Attempt.submitted_at.isnot(None),
        )
        .order_by(Attempt.submitted_at)
        .all()
    )
    return [
        MyAttemptOut(
            id=attempt.id,
            assessment_id=assessment.id,
            assessment_title=assessment.title,
            topic=assessment.topic,
            total_score=attempt.total_score,
            submitted_at=attempt.submitted_at,
        )
        for attempt, assessment in rows
    ]
