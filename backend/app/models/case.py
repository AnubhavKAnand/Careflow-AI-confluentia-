from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.patient import utcnow


class CaseStatus:
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    FINALIZED = "finalized"
    ERROR = "error"


class Case(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    status: str = Field(default=CaseStatus.PROCESSING, index=True)

    # Denormalised for fast queue sorting
    priority: Optional[str] = Field(default=None, index=True)  # P1..P4 (AI suggestion until finalized)
    final_priority: Optional[str] = None  # set by the clinician
    sort_score: float = 0.0
    chief_complaint: Optional[str] = None

    # Full structured extraction (schemas.extraction.Extraction) incl. source links
    extraction: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    extraction_provider: Optional[str] = None
    extraction_latency_ms: Optional[int] = None

    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class Source(SQLModel, table=True):
    """One piece of raw input: a patient message, an intake form, (Phase 2) a report or voice note."""

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case.id", index=True)
    kind: str  # "patient_message" | "intake_form" | "report" | "voice"
    label: Optional[str] = None
    original_text: str = ""
    language: Optional[str] = None
    language_confidence: Optional[float] = None
    translated_text: Optional[str] = None  # English, filled in Phase 2
    translation_confidence: Optional[float] = None
    file_path: Optional[str] = None  # path relative to UPLOAD_DIR
    mime: Optional[str] = None
    processing_status: str = "pending"  # pending | done | failed
    meta: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
