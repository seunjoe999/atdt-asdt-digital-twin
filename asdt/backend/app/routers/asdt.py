from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import atdt_client, gap_analysis
from app.database import get_db
from app.models import GapEvent, GapStatus, Interaction, KnowledgeState, NegotiationRecord, Student, now_utc
from app.schemas import (
    AskRequest,
    GapEventOut,
    InteractionOut,
    KnowledgeStateOut,
    NegotiateRequest,
    NegotiationRecordOut,
    PerformanceReport,
    SyncRequest,
    SyncResponse,
)

router = APIRouter(prefix="/asdt", tags=["asdt"])
bearer_scheme = HTTPBearer()


async def _resolve_student(
    db: Session, credentials: HTTPAuthorizationCredentials
) -> tuple[Student, str]:
    """Resolve (and cache) the ATDT identity behind this token by asking
    ATDT itself — see app/atdt_client.py for why ASDT never decodes the
    token locally. Returns the cached Student row plus the raw token, since
    every subsequent ATDT call in the request needs to forward it too.
    """
    token = credentials.credentials
    who = await atdt_client.whoami(token)
    if who.get("role") != "student":
        raise HTTPException(status_code=403, detail="ASDT represents students only")

    student = db.query(Student).filter(Student.atdt_user_id == who["id"]).first()
    if student is None:
        student = Student(atdt_user_id=who["id"], email=who["email"], full_name=who["full_name"])
        db.add(student)
        db.commit()
        db.refresh(student)
    return student, token


@router.post("/sync", response_model=SyncResponse)
async def sync(
    payload: SyncRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """Acquisition & Tracking Layer -> Simulation Layer -> Analytics Layer,
    in one call: pull fresh attempt data from ATDT, recompute per-topic
    mastery, and open or resolve GapEvents accordingly.
    """
    student, token = await _resolve_student(db, credentials)
    attempts = await atdt_client.get_my_attempts(token, payload.course_id)
    mastery_by_topic = gap_analysis.compute_mastery_by_topic(attempts)

    knowledge_states: list[KnowledgeState] = []
    new_gaps: list[GapEvent] = []
    resolved_gaps: list[GapEvent] = []

    for topic, (mastery, sample_count) in mastery_by_topic.items():
        state = (
            db.query(KnowledgeState)
            .filter(
                KnowledgeState.student_id == student.id,
                KnowledgeState.course_id == payload.course_id,
                KnowledgeState.topic == topic,
            )
            .first()
        )
        if state is None:
            state = KnowledgeState(student_id=student.id, course_id=payload.course_id, topic=topic, mastery=mastery)
            db.add(state)
        state.mastery = mastery
        state.sample_count = sample_count
        knowledge_states.append(state)

        open_gap = (
            db.query(GapEvent)
            .filter(
                GapEvent.student_id == student.id,
                GapEvent.course_id == payload.course_id,
                GapEvent.topic == topic,
                GapEvent.status != GapStatus.RESOLVED,
            )
            .first()
        )

        if gap_analysis.is_gap(mastery):
            if open_gap is None:
                open_gap = GapEvent(
                    student_id=student.id,
                    course_id=payload.course_id,
                    topic=topic,
                    severity=gap_analysis.severity(mastery),
                )
                db.add(open_gap)
                new_gaps.append(open_gap)
            else:
                open_gap.severity = gap_analysis.severity(mastery)
        elif open_gap is not None:
            open_gap.status = GapStatus.RESOLVED
            open_gap.resolved_at = now_utc()
            resolved_gaps.append(open_gap)

    db.commit()
    for obj in knowledge_states + new_gaps + resolved_gaps:
        db.refresh(obj)

    return SyncResponse(
        knowledge_states=[KnowledgeStateOut.model_validate(s) for s in knowledge_states],
        new_gaps=[GapEventOut.model_validate(g) for g in new_gaps],
        resolved_gaps=[GapEventOut.model_validate(g) for g in resolved_gaps],
    )


@router.get("/gaps", response_model=list[GapEventOut])
async def list_gaps(
    course_id: int,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    student, _token = await _resolve_student(db, credentials)
    return (
        db.query(GapEvent)
        .filter(GapEvent.student_id == student.id, GapEvent.course_id == course_id)
        .order_by(GapEvent.detected_at.desc())
        .all()
    )


@router.post("/negotiate", response_model=NegotiationRecordOut)
async def negotiate(
    payload: NegotiateRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """Reactive Control Layer, Contract-Net-Protocol-flavoured (thesis
    Section 2.4): ASDT announces the gap by asking ATDT's Tutoring Channel
    for help with the topic; ATDT's RAG-grounded answer + citations *is* its
    "bid"; ASDT accepts it (the simplest possible award rule — a single
    proposer) and logs the whole round. Every step is a real HTTP call
    between two independent services, not a simulated exchange.
    """
    student, token = await _resolve_student(db, credentials)

    gap = db.get(GapEvent, payload.gap_event_id)
    if not gap or gap.student_id != student.id:
        raise HTTPException(status_code=404, detail="Gap not found")
    if gap.status == GapStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="This gap is already resolved")

    announcement = (
        f"I'm struggling with '{gap.topic}'. Can you explain it more simply, with an example, "
        "and point me to what I should review?"
    )
    atdt_response = await atdt_client.ask_tutor(token, gap.course_id, announcement)

    record = NegotiationRecord(
        gap_event_id=gap.id,
        announcement=announcement,
        atdt_answer=atdt_response["answer"],
        atdt_citations=atdt_response.get("citations", []),
        decision="accepted_remediation",
    )
    db.add(record)
    gap.status = GapStatus.NEGOTIATING
    db.commit()
    db.refresh(record)
    return record


@router.post("/ask", response_model=InteractionOut)
async def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """The primary "student learns through ASDT" path: free-form questions
    that aren't tied to a detected gap. ASDT still proxies to ATDT's
    Tutoring Channel (it has no tutoring intelligence of its own — ATDT owns
    the course material and the RAG pipeline), but the student only ever
    talks to their own twin, and every exchange is logged to their learning
    history the same way a gap negotiation is.
    """
    student, token = await _resolve_student(db, credentials)
    atdt_response = await atdt_client.ask_tutor(token, payload.course_id, payload.question)

    interaction = Interaction(
        student_id=student.id,
        course_id=payload.course_id,
        question=payload.question,
        atdt_answer=atdt_response["answer"],
        atdt_citations=atdt_response.get("citations", []),
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


@router.get("/report", response_model=PerformanceReport)
async def performance_report(
    course_id: int,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """The "Generate Performance Report" use case (thesis Figure 3.1) — one
    of the two use cases the thesis flags as crossing the ASDT-ATDT
    boundary. Aggregates this student's current knowledge state, gap
    history, and negotiation log for one course.
    """
    student, _token = await _resolve_student(db, credentials)

    states = (
        db.query(KnowledgeState)
        .filter(KnowledgeState.student_id == student.id, KnowledgeState.course_id == course_id)
        .all()
    )
    overall = round(sum(s.mastery for s in states) / len(states), 4) if states else 0.0

    gaps = (
        db.query(GapEvent)
        .filter(GapEvent.student_id == student.id, GapEvent.course_id == course_id)
        .all()
    )
    open_count = sum(1 for g in gaps if g.status == GapStatus.OPEN)
    negotiating_count = sum(1 for g in gaps if g.status == GapStatus.NEGOTIATING)
    resolved_count = sum(1 for g in gaps if g.status == GapStatus.RESOLVED)

    gap_ids = [g.id for g in gaps]
    recent_negotiations = (
        db.query(NegotiationRecord)
        .filter(NegotiationRecord.gap_event_id.in_(gap_ids))
        .order_by(NegotiationRecord.created_at.desc())
        .limit(10)
        .all()
        if gap_ids
        else []
    )

    recent_interactions = (
        db.query(Interaction)
        .filter(Interaction.student_id == student.id, Interaction.course_id == course_id)
        .order_by(Interaction.created_at.desc())
        .limit(10)
        .all()
    )

    return PerformanceReport(
        course_id=course_id,
        student_email=student.email,
        overall_mastery=overall,
        topics=[KnowledgeStateOut.model_validate(s) for s in states],
        open_gaps=open_count,
        negotiating_gaps=negotiating_count,
        resolved_gaps=resolved_count,
        recent_negotiations=[NegotiationRecordOut.model_validate(n) for n in recent_negotiations],
        recent_interactions=[InteractionOut.model_validate(i) for i in recent_interactions],
    )
