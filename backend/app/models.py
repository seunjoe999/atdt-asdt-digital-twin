import enum
import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    LECTURER = "lecturer"
    STUDENT = "student"


class DocumentStatus(str, enum.Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MaterialType(str, enum.Enum):
    LESSON_PLAN = "lesson_plan"
    SUMMARY = "summary"
    REVISION_NOTES = "revision_notes"
    PRACTICE_QUESTIONS = "practice_questions"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class AssessmentStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class QuestionType(str, enum.Enum):
    MCQ = "mcq"
    SAQ = "saq"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    courses: Mapped[list["Course"]] = relationship(back_populates="lecturer")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    subject_area: Mapped[str] = mapped_column(String(255), default="")
    enrolment_code: Mapped[str] = mapped_column(
        String(16), unique=True, default=lambda: secrets.token_hex(4)
    )
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    lecturer: Mapped["User"] = relationship(back_populates="courses")
    documents: Mapped[list["Document"]] = relationship(back_populates="course")
    materials: Mapped[list["TeachingMaterial"]] = relationship(back_populates="course")
    assessments: Mapped[list["Assessment"]] = relationship(back_populates="course")

    @property
    def chroma_collection_name(self) -> str:
        return f"course_{self.id}"


class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.PROCESSING
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    course: Mapped["Course"] = relationship(back_populates="documents")


class TeachingMaterial(Base):
    __tablename__ = "teaching_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    type: Mapped[MaterialType] = mapped_column(Enum(MaterialType), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    course: Mapped["Course"] = relationship(back_populates="materials")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), default="")
    mcq_count: Mapped[int] = mapped_column(Integer, default=0)
    saq_count: Mapped[int] = mapped_column(Integer, default=0)
    time_limit_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[AssessmentStatus] = mapped_column(
        Enum(AssessmentStatus), default=AssessmentStatus.DRAFT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    course: Mapped["Course"] = relationship(back_populates="assessments")
    questions: Mapped[list["Question"]] = relationship(back_populates="assessment")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    type: Mapped[QuestionType] = mapped_column(Enum(QuestionType), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, default=list)  # MCQ only
    correct_answer: Mapped[str] = mapped_column(Text, default="")  # MCQ only
    rubric: Mapped[str] = mapped_column(Text, default="")  # SAQ only
    order: Mapped[int] = mapped_column(Integer, default=0)

    assessment: Mapped["Assessment"] = relationship(back_populates="questions")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    responses: Mapped[list["Response"]] = relationship(back_populates="attempt")


class CourseMessage(Base):
    """A shared, course-wide message board so a lecturer and their enrolled
    students can talk directly — independent of the AI tutoring/negotiation
    channels, which are twin-to-twin, not person-to-person.
    """

    __tablename__ = "course_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Response(Base):
    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    student_answer: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="")

    attempt: Mapped["Attempt"] = relationship(back_populates="responses")


class CheckIn(Base):
    """A student's daily wellbeing self-report — the raw signal the at-risk
    dashboard and the counseling twin both read from."""

    __tablename__ = "wellbeing_checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    mood: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 (low) - 5 (great)
    stress: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 (calm) - 5 (overwhelmed)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class StreakState(Base):
    """One row per student tracking the gamified daily-engagement streak."""

    __tablename__ = "streak_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD


class CounselingMessage(Base):
    """Turn-by-turn log of a student's chat with the AI counselor twin."""

    __tablename__ = "counseling_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
