from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import GapStatus


class SyncRequest(BaseModel):
    course_id: int


class KnowledgeStateOut(BaseModel):
    topic: str
    mastery: float
    sample_count: int
    last_updated: datetime

    model_config = ConfigDict(from_attributes=True)


class GapEventOut(BaseModel):
    id: int
    course_id: int
    topic: str
    severity: float
    status: GapStatus
    detected_at: datetime
    resolved_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SyncResponse(BaseModel):
    knowledge_states: list[KnowledgeStateOut]
    new_gaps: list[GapEventOut]
    resolved_gaps: list[GapEventOut]


class NegotiateRequest(BaseModel):
    gap_event_id: int


class NegotiationRecordOut(BaseModel):
    id: int
    gap_event_id: int
    announcement: str
    atdt_answer: str
    atdt_citations: list
    decision: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PerformanceReport(BaseModel):
    course_id: int
    student_email: str
    overall_mastery: float
    topics: list[KnowledgeStateOut]
    open_gaps: int
    negotiating_gaps: int
    resolved_gaps: int
    recent_negotiations: list[NegotiationRecordOut]
