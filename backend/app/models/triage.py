from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.patient import utcnow


class TriageResult(SQLModel, table=True):
    """Output of the triage engine. A new row is written on every (re)triage; latest = current."""

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case.id", index=True)
    priority: str
    sort_score: float
    payload: dict[str, Any] = Field(sa_column=Column(JSON))  # schemas.triage.TriageOutput
    engine_version: str
    created_at: datetime = Field(default_factory=utcnow)


class TriageNote(SQLModel, table=True):
    """Versioned triage / referral note. AI writes v1 as a draft; clinicians edit and approve."""

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case.id", index=True)
    version: int
    content: str
    status: str = "draft"  # "draft" | "edited" | "approved"
    author: str
    author_type: str  # "ai" | "human"
    created_at: datetime = Field(default_factory=utcnow)


class Review(SQLModel, table=True):
    """A clinician decision on a case. These rows are the training signal for the Phase 6 shadow agent."""

    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case.id", index=True)
    reviewer: str
    reviewer_role: str
    action: str  # "approve" | "override"
    ai_priority: str
    final_priority: str
    reason: Optional[str] = None
    note_id: Optional[int] = Field(default=None, foreign_key="triagenote.id")
    created_at: datetime = Field(default_factory=utcnow)
