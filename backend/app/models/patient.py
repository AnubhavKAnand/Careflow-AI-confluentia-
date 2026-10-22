from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Patient(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    age_years: Optional[int] = None
    sex: Optional[str] = None  # "male" | "female" | "other" | None
    phone: Optional[str] = None
    preferred_language: Optional[str] = None  # e.g. "hi", "en", "hi-en"

    # Consent (fully managed in Phase 5; recorded from day one)
    consent_given: bool = False
    consent_at: Optional[datetime] = None
    consent_text_version: Optional[str] = None
    withdrawn_at: Optional[datetime] = None
    withdrawal_reason: Optional[str] = None
    withdrawn_by: Optional[str] = None  # username, or "patient" when done with the reference code
    # Short code printed on the consent receipt; lets the patient withdraw without an account
    access_code: Optional[str] = None

    created_at: datetime = Field(default_factory=utcnow)
