from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    AssessmentStatus,
    DocumentStatus,
    MaterialType,
    MessageRole,
    QuestionType,
    UserRole,
)

# ---------- Auth ----------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    role: UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole

    model_config = ConfigDict(from_attributes=True)


# ---------- Courses ----------


class CourseCreate(BaseModel):
    title: str
    description: str = ""
    subject_area: str = ""


class CourseOut(BaseModel):
    id: int
    title: str
    description: str
    subject_area: str
    enrolment_code: str
    lecturer_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EnrolRequest(BaseModel):
    enrolment_code: str


class EnrolledStudentOut(BaseModel):
    id: int
    email: str
    full_name: str

    model_config = ConfigDict(from_attributes=True)


# ---------- Documents ----------


class DocumentOut(BaseModel):
    id: int
    course_id: int
    filename: str
    status: DocumentStatus
    chunk_count: int
    error: str
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- Teaching ----------


class TeachingMaterialRequest(BaseModel):
    type: MaterialType
    topic: str = ""
    instructions: str = ""


class TeachingMaterialOut(BaseModel):
    id: int
    course_id: int
    type: MaterialType
    topic: str
    content: str
    published: bool
    created_at: datetime


class StudentAdviceTopic(BaseModel):
    topic: str
    mastery: float


class TeachingAdviceRequest(BaseModel):
    student_name: str
    overall_mastery: float
    open_gaps: int
    topics: list[StudentAdviceTopic] = []


class TeachingAdviceResponse(BaseModel):
    advice: str

    model_config = ConfigDict(from_attributes=True)


# ---------- Tutoring ----------


class TutorQuery(BaseModel):
    question: str
    conversation_id: int | None = None


class Citation(BaseModel):
    source_document: str
    page_number: int | None = None
    chunk_index: int | None = None
    excerpt: str


class TutorAnswer(BaseModel):
    conversation_id: int
    answer: str
    citations: list[Citation]


class MessageOut(BaseModel):
    id: int
    role: MessageRole
    content: str
    citations: list
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- Course messages (teacher <-> student) ----------


class CourseMessageCreate(BaseModel):
    content: str = Field(min_length=1)


class CourseMessageOut(BaseModel):
    id: int
    course_id: int
    sender_id: int
    sender_name: str
    sender_role: UserRole
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- Examination ----------


class AssessmentCreateRequest(BaseModel):
    title: str
    topic: str = ""
    mcq_count: int = 5
    saq_count: int = 2
    time_limit_minutes: int = 30


class QuestionOut(BaseModel):
    id: int
    type: QuestionType
    text: str
    options: list
    order: int

    model_config = ConfigDict(from_attributes=True)


class QuestionWithAnswerOut(QuestionOut):
    correct_answer: str
    rubric: str


class AssessmentOut(BaseModel):
    id: int
    course_id: int
    title: str
    topic: str
    mcq_count: int
    saq_count: int
    time_limit_minutes: int
    status: AssessmentStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuestionEditRequest(BaseModel):
    text: str | None = None
    options: list | None = None
    correct_answer: str | None = None
    rubric: str | None = None


class SubmitAnswer(BaseModel):
    question_id: int
    answer: str


class SubmitAttemptRequest(BaseModel):
    answers: list[SubmitAnswer]


class ResponseOut(BaseModel):
    question_id: int
    student_answer: str
    score: float | None
    feedback: str

    model_config = ConfigDict(from_attributes=True)


class AttemptResultOut(BaseModel):
    id: int
    assessment_id: int
    total_score: float | None
    submitted_at: datetime | None
    responses: list[ResponseOut]

    model_config = ConfigDict(from_attributes=True)


class MyAttemptOut(BaseModel):
    """A student's own attempt, with the assessment's topic folded in so a
    consumer (e.g. ASDT) can compute per-topic mastery without a second call
    per assessment.
    """

    id: int
    assessment_id: int
    assessment_title: str
    topic: str
    total_score: float | None
    submitted_at: datetime | None


# ---------- Wellbeing (counseling + gamification) ----------


class CheckInCreate(BaseModel):
    mood: int = Field(ge=1, le=5)
    stress: int = Field(ge=1, le=5)
    note: str = ""


class CheckInOut(BaseModel):
    id: int
    mood: int
    stress: int
    note: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StreakOut(BaseModel):
    current_streak: int
    longest_streak: int
    xp: int
    level: int
    badges: list[str]


class CounselMessageIn(BaseModel):
    message: str


class CounselMessageOut(BaseModel):
    reply: str
    flagged: bool
    resources: list[str] = []


class CounselHistoryItem(BaseModel):
    role: MessageRole
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AtRiskStudentOut(BaseModel):
    student_id: int
    full_name: str
    risk_score: int
    risk_label: str
    reasons: list[str]
