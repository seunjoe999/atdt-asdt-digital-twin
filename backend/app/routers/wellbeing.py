"""Wellbeing channel: daily check-ins and a supportive counseling twin feed a
gamified streak/XP system, and a lecturer-facing at-risk dashboard reads the
same signals to flag students drifting toward dropout before it happens.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_lecturer, require_student
from app.llm.dyon_llm import generate
from app.models import (
    Assessment,
    Attempt,
    CheckIn,
    Course,
    CounselingMessage,
    Enrollment,
    MessageRole,
    StreakState,
    User,
)
from app.routers.courses import _ensure_access
from app.schemas import (
    AtRiskStudentOut,
    CheckInCreate,
    CheckInOut,
    CounselHistoryItem,
    CounselMessageIn,
    CounselMessageOut,
    CrisisAlertOut,
    StreakOut,
)

router = APIRouter(prefix="/wellbeing", tags=["wellbeing"])
course_router = APIRouter(prefix="/courses/{course_id}/wellbeing", tags=["wellbeing"])

_CRISIS_KEYWORDS = [
    "suicide",
    "kill myself",
    "end my life",
    "self-harm",
    "hurt myself",
    "want to die",
    "no reason to live",
]

_SAFETY_RESOURCES = [
    "If you're in immediate danger, contact your local emergency services right now.",
    "Nigeria: reach out to a trusted adult, your school counselor, or the Mentally Aware Nigeria Initiative (MANI) helpline.",
    "You can also talk to a real school counselor — MyStudyTwin is not a substitute for professional care.",
]

_COUNSELOR_SYSTEM_PROMPT = (
    "You are MyStudyTwin's supportive academic counselor twin — warm, non-judgmental, and "
    "focused on keeping students engaged with their studies and catching burnout or dropout "
    "risk early. You are not a licensed therapist and never claim to be one. Keep replies "
    "short, empathetic, and end with one concrete, gentle next step."
)

_CRISIS_SAFETY_INSTRUCTION = (
    "\n\nIMPORTANT: The student's message contains language suggesting they may be in crisis "
    "or thinking about self-harm. Respond with care, take it seriously, and firmly but gently "
    "encourage them to reach out to a trusted adult, school counselor, or emergency services "
    "right now. Do not attempt to diagnose or provide therapy."
)


def _is_crisis(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in _CRISIS_KEYWORDS)


def _record_activity(db: Session, student_id: int) -> StreakState:
    streak = db.query(StreakState).filter(StreakState.student_id == student_id).first()
    if streak is None:
        streak = StreakState(
            student_id=student_id, current_streak=0, longest_streak=0, xp=0, last_active_date=""
        )
        db.add(streak)

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    if streak.last_active_date == today:
        pass
    elif streak.last_active_date == yesterday:
        streak.current_streak += 1
    else:
        streak.current_streak = 1

    streak.xp += 10
    streak.longest_streak = max(streak.longest_streak, streak.current_streak)
    streak.last_active_date = today

    db.commit()
    db.refresh(streak)
    return streak


def _badges(streak: StreakState) -> list[str]:
    badges = []
    if streak.current_streak >= 3:
        badges.append("3-Day Spark")
    if streak.current_streak >= 7:
        badges.append("7-Day Flame")
    if streak.current_streak >= 30:
        badges.append("30-Day Legend")
    if streak.xp >= 100:
        badges.append("Century XP")
    if streak.xp >= 500:
        badges.append("XP Master")
    return badges


def _to_streak_out(streak: StreakState) -> StreakOut:
    return StreakOut(
        current_streak=streak.current_streak,
        longest_streak=streak.longest_streak,
        xp=streak.xp,
        level=streak.xp // 100,
        badges=_badges(streak),
    )


# ---------- Student-facing ----------


@router.post("/checkin", response_model=CheckInOut, status_code=201)
def create_checkin(
    payload: CheckInCreate, db: Session = Depends(get_db), student: User = Depends(require_student)
):
    checkin = CheckIn(
        student_id=student.id, mood=payload.mood, stress=payload.stress, note=payload.note
    )
    db.add(checkin)
    db.commit()
    _record_activity(db, student.id)
    db.refresh(checkin)
    return checkin


@router.get("/checkins", response_model=list[CheckInOut])
def list_checkins(db: Session = Depends(get_db), student: User = Depends(require_student)):
    return (
        db.query(CheckIn)
        .filter(CheckIn.student_id == student.id)
        .order_by(CheckIn.created_at.desc())
        .limit(30)
        .all()
    )


@router.get("/streak", response_model=StreakOut)
def get_streak(db: Session = Depends(get_db), student: User = Depends(require_student)):
    streak = db.query(StreakState).filter(StreakState.student_id == student.id).first()
    if streak is None:
        streak = StreakState(
            student_id=student.id, current_streak=0, longest_streak=0, xp=0, last_active_date=""
        )
    return _to_streak_out(streak)


@router.post("/counsel", response_model=CounselMessageOut)
async def counsel(
    payload: CounselMessageIn, db: Session = Depends(get_db), student: User = Depends(require_student)
):
    crisis = _is_crisis(payload.message)

    # Flagging the student's own message (not just the AI's reply) is what
    # makes it show up on the lecturer's crisis-alerts feed with the actual
    # words the student used -- the reply alone isn't actionable context.
    db.add(CounselingMessage(student_id=student.id, role=MessageRole.USER, content=payload.message, flagged=crisis))
    db.commit()

    system_prompt = _COUNSELOR_SYSTEM_PROMPT
    if crisis:
        system_prompt += _CRISIS_SAFETY_INSTRUCTION
    reply = await generate(system_prompt, payload.message)

    db.add(
        CounselingMessage(
            student_id=student.id, role=MessageRole.ASSISTANT, content=reply, flagged=crisis
        )
    )
    db.commit()
    _record_activity(db, student.id)

    resources = list(_SAFETY_RESOURCES) if crisis else []
    return CounselMessageOut(reply=reply, flagged=crisis, resources=resources)


@router.get("/counsel/history", response_model=list[CounselHistoryItem])
def counsel_history(db: Session = Depends(get_db), student: User = Depends(require_student)):
    return (
        db.query(CounselingMessage)
        .filter(CounselingMessage.student_id == student.id)
        .order_by(CounselingMessage.created_at.asc())
        .limit(50)
        .all()
    )


# ---------- Lecturer-facing ----------


@course_router.get("", response_model=list[AtRiskStudentOut])
def at_risk_students(
    course_id: int, db: Session = Depends(get_db), lecturer: User = Depends(require_lecturer)
):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, lecturer)

    student_ids = [e.student_id for e in db.query(Enrollment).filter(Enrollment.course_id == course.id)]
    if not student_ids:
        return []
    students = db.query(User).filter(User.id.in_(student_ids)).all()

    assessment_ids = [a.id for a in db.query(Assessment).filter(Assessment.course_id == course.id)]

    results: list[AtRiskStudentOut] = []
    for student in students:
        reasons: list[str] = []

        last_checkin = (
            db.query(CheckIn)
            .filter(CheckIn.student_id == student.id)
            .order_by(CheckIn.created_at.desc())
            .first()
        )
        last_attempt = (
            db.query(Attempt)
            .filter(Attempt.student_id == student.id, Attempt.assessment_id.in_(assessment_ids or [-1]))
            .order_by(Attempt.started_at.desc())
            .first()
        )
        last_counsel = (
            db.query(CounselingMessage)
            .filter(CounselingMessage.student_id == student.id, CounselingMessage.role == MessageRole.USER)
            .order_by(CounselingMessage.created_at.desc())
            .first()
        )

        last_activity_dates = [
            d.created_at if hasattr(d, "created_at") else d.started_at
            for d in (last_checkin, last_attempt, last_counsel)
            if d is not None
        ]
        if last_activity_dates:
            most_recent = max(d.replace(tzinfo=None) for d in last_activity_dates)
            days_inactive = max(0, (datetime.utcnow() - most_recent).days)
        else:
            days_inactive = 999

        recent_checkins = (
            db.query(CheckIn)
            .filter(CheckIn.student_id == student.id)
            .order_by(CheckIn.created_at.desc())
            .limit(5)
            .all()
        )
        mood_avg = (
            sum(c.mood for c in recent_checkins) / len(recent_checkins) if recent_checkins else 3.0
        )

        scored_attempts = (
            db.query(Attempt)
            .filter(
                Attempt.student_id == student.id,
                Attempt.assessment_id.in_(assessment_ids or [-1]),
                Attempt.total_score.isnot(None),
            )
            .order_by(Attempt.started_at.asc())
            .all()
        )
        score_trend = 0.0
        if len(scored_attempts) >= 2:
            mid = len(scored_attempts) // 2
            earlier = scored_attempts[:mid] or scored_attempts[:1]
            recent = scored_attempts[mid:]
            earlier_avg = sum(a.total_score for a in earlier) / len(earlier)
            recent_avg = sum(a.total_score for a in recent) / len(recent)
            score_trend = recent_avg - earlier_avg

        risk_score = 0
        inactivity_component = min(40, days_inactive * 4)
        risk_score += inactivity_component
        if inactivity_component >= 20:
            reasons.append(f"No activity in {days_inactive} days")

        mood_component = max(0, (3 - mood_avg) * 15)
        risk_score += mood_component
        if mood_component >= 15:
            reasons.append("Mood trending low in recent check-ins")

        if score_trend < 0:
            trend_component = min(30, abs(score_trend) * 60)
            risk_score += trend_component
            if trend_component >= 10:
                reasons.append("Assessment scores declining")

        risk_score = int(max(0, min(100, risk_score)))
        risk_label = "low" if risk_score < 34 else "medium" if risk_score < 67 else "high"

        results.append(
            AtRiskStudentOut(
                student_id=student.id,
                full_name=student.full_name,
                risk_score=risk_score,
                risk_label=risk_label,
                reasons=reasons,
            )
        )

    results.sort(key=lambda r: r.risk_score, reverse=True)
    return results


@course_router.get("/crisis-alerts", response_model=list[CrisisAlertOut])
def crisis_alerts(
    course_id: int, db: Session = Depends(get_db), lecturer: User = Depends(require_lecturer)
):
    """The crisis-chat human-escalation surface: every crisis-keyword-flagged
    message a student in this course has sent the counselor twin, most
    recent first. This is the "someone must actually see it" half of the
    safety feature -- keyword detection alone does nothing if nobody reads
    the result, so the lecturer's dashboard is where that has to land.
    """
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _ensure_access(db, course, lecturer)

    student_ids = [e.student_id for e in db.query(Enrollment).filter(Enrollment.course_id == course.id)]
    if not student_ids:
        return []
    students_by_id = {s.id: s for s in db.query(User).filter(User.id.in_(student_ids)).all()}

    flagged = (
        db.query(CounselingMessage)
        .filter(
            CounselingMessage.student_id.in_(student_ids),
            CounselingMessage.role == MessageRole.USER,
            CounselingMessage.flagged.is_(True),
        )
        .order_by(CounselingMessage.created_at.desc())
        .limit(50)
        .all()
    )

    return [
        CrisisAlertOut(
            student_id=m.student_id,
            full_name=students_by_id[m.student_id].full_name,
            message=m.content,
            created_at=m.created_at,
        )
        for m in flagged
        if m.student_id in students_by_id
    ]
