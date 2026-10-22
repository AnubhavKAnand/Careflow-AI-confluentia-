from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PatientIn(BaseModel):
    name: str
    age_years: Optional[int] = Field(default=None, ge=0, le=120)
    sex: Optional[Literal["male", "female", "other"]] = None
    phone: Optional[str] = None
    preferred_language: Optional[str] = None


class VitalsIn(BaseModel):
    """Optional vitals entered by the intake worker (most trusted source)."""

    spo2: Optional[float] = Field(default=None, ge=50, le=100)
    pulse: Optional[float] = Field(default=None, ge=20, le=250)
    resp_rate: Optional[float] = Field(default=None, ge=4, le=60)
    systolic_bp: Optional[float] = Field(default=None, ge=50, le=260)
    diastolic_bp: Optional[float] = Field(default=None, ge=20, le=160)
    temperature_c: Optional[float] = Field(default=None, ge=30, le=45)
    consciousness: Optional[Literal["A", "C", "V", "P", "U"]] = None
    on_oxygen: Optional[bool] = None


class CaseCreate(BaseModel):
    patient: PatientIn
    consent_given: bool
    message: str = Field(min_length=1, description="Patient's own description, any language")
    vitals: Optional[VitalsIn] = None


class CaseIntake(BaseModel):
    """Multipart intake: same as CaseCreate, but the message is optional when files are attached."""

    patient: PatientIn
    consent_given: bool
    message: Optional[str] = None
    vitals: Optional[VitalsIn] = None


class CaseListItem(BaseModel):
    id: int
    patient_name: str
    age_years: Optional[int]
    sex: Optional[str]
    status: str
    priority: Optional[str]
    priority_label: Optional[str]
    final_priority: Optional[str]
    chief_complaint: Optional[str]
    red_flag_count: int
    top_reason: Optional[str]
    uncertain: bool
    sort_score: float
    created_at: datetime
    waiting_minutes: int
    overdue: bool
    target_minutes: Optional[int] = None
    queue_score: float = 0.0  # sort_score + waiting-time escalation (never crosses into the next band)
    completeness: Optional[float] = None
    flag_counts: dict[str, int] = Field(default_factory=dict)  # suspicious / conflicting / unclear / missing
    critical_flags: int = 0
    source_kinds: list[str] = Field(default_factory=list)


class SourceOut(BaseModel):
    id: int
    kind: str
    label: Optional[str]
    original_text: str
    language: Optional[str]
    language_confidence: Optional[float]
    translated_text: Optional[str]
    translation_confidence: Optional[float]
    mime: Optional[str] = None
    processing_status: str = "done"
    has_file: bool = False
    # Reading details for the source viewer: engine, avg_confidence, legibility, pages, lines (with bbox),
    # segments (with timestamps), quality_flags. Internal fields like sha256 are dropped.
    reading: dict[str, Any] = Field(default_factory=dict)


class NoteOut(BaseModel):
    id: int
    version: int
    content: str
    status: str
    author: str
    author_type: str
    created_at: datetime


class CaseDetail(BaseModel):
    id: int
    status: str
    patient: dict[str, Any]
    sources: list[SourceOut]
    extraction: Optional[dict[str, Any]]
    extraction_provider: Optional[str]
    extraction_latency_ms: Optional[int]
    triage: Optional[dict[str, Any]]
    note: Optional[NoteOut]
    final_priority: Optional[str]
    created_at: datetime
    permissions: list[str] = Field(default_factory=list)  # what the signed-in user may do on this case
    withdrawn: bool = False
    learning_mode: str = "shadow"
    agent: Optional[dict[str, Any]] = None  # learned suggestion: only in recommendation mode, not on blind checks
    # Only on the creation response: the consent receipt the desk gives to the patient
    receipt: Optional[dict[str, Any]] = None


class NoteUpdate(BaseModel):
    content: str = Field(min_length=1)


class ReviewIn(BaseModel):
    action: Literal["approve", "override"]
    final_priority: Literal["P1", "P2", "P3", "P4"]
    reason: Optional[str] = None
    note_content: Optional[str] = None  # if given, saved as a new note version before approval


class AnswerIn(BaseModel):
    question_id: str  # FollowUp.id from the case's validation report
    answer: Optional[str] = None  # free text, any language
    yes: Optional[bool] = None  # for yes/no questions


class AnswersIn(BaseModel):
    answers: list[AnswerIn] = Field(min_length=1)
