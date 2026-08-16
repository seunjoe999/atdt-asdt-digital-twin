import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class GapStatus(str, enum.Enum):
    OPEN = "open"  # detected, not yet acted on
    NEGOTIATING = "negotiating"  # remediation requested from ATDT, awaiting evidence of improvement
    RESOLVED = "resolved"  # a later sync showed mastery back above threshold


class Student(Base):
    """A cache of the ATDT identity ASDT is currently representing.

    ASDT never stores a password or issues its own credentials for this
    person — identity is always re-confirmed against ATDT's own /auth/me
    using the caller-supplied token (see app/atdt_client.py). This row only
    exists so the rest of ASDT's tables have something stable to key off.
    """

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    atdt_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    knowledge_states: Mapped[list["KnowledgeState"]] = relationship(back_populates="student")
    gap_events: Mapped[list["GapEvent"]] = relationship(back_populates="student")


class KnowledgeState(Base):
    """Simulation Layer (thesis Section 3.4.1, Layer 2): this student's
    estimated mastery per curriculum topic, in a given ATDT course. Updated
    by re-syncing against ATDT's Examination Channel results — a simple
    average-of-scores model, not the thesis's full Deep-Knowledge-Tracing
    probabilistic model (documented scope cut, see README).
    """

    __tablename__ = "knowledge_states"
    __table_args__ = (UniqueConstraint("student_id", "course_id", "topic", name="uq_student_course_topic"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, nullable=False)  # ATDT course id (no FK: separate DB)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    mastery: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0-1.0
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    student: Mapped["Student"] = relationship(back_populates="knowledge_states")


class GapEvent(Base):
    """Analytics/Reactive Control layers (thesis Layers 3-4): a detected
    competency gap and its remediation lifecycle.
    """

    __tablename__ = "gap_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False)  # 1 - mastery at detection time
    status: Mapped[GapStatus] = mapped_column(Enum(GapStatus), default=GapStatus.OPEN)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="gap_events")
    negotiations: Mapped[list["NegotiationRecord"]] = relationship(back_populates="gap_event")


class NegotiationRecord(Base):
    """A single ASDT<->ATDT negotiation round (thesis Section 2.4's
    Contract-Net-Protocol framing: ASDT announces a need, ATDT proposes a
    remediation, ASDT records the outcome). Every round is logged in full —
    this table *is* the "transparent negotiation logging" the thesis's
    ethics section (1.5) requires for human oversight.
    """

    __tablename__ = "negotiation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gap_event_id: Mapped[int] = mapped_column(ForeignKey("gap_events.id"), nullable=False)
    announcement: Mapped[str] = mapped_column(Text, nullable=False)  # what ASDT asked ATDT for
    atdt_answer: Mapped[str] = mapped_column(Text, nullable=False)  # ATDT's proposed remediation
    atdt_citations: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    gap_event: Mapped["GapEvent"] = relationship(back_populates="negotiations")
