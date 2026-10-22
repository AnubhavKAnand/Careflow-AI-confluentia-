from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.patient import utcnow


class AuditLog(SQLModel, table=True):
    """Append-only record of every important action by the AI, the system and humans."""

    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow, index=True)
    actor: str  # username, model name, or "system"
    actor_type: str  # "human" | "ai" | "system"
    action: str
    case_id: Optional[int] = Field(default=None, index=True)
    patient_id: Optional[int] = Field(default=None, index=True)
    details: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    # Tamper evidence: each row's hash covers its content and the previous row's hash
    prev_hash: Optional[str] = None
    hash: Optional[str] = Field(default=None, index=True)
