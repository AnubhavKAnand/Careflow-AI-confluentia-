from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.extraction import Evidence
from app.schemas.validation import ValidationReport

# Priority bands. Review-time targets adapted from the Manchester Triage System
# (red 0 / orange 10 / yellow 60 / green 120 min) for an outpatient / primary-care queue.
PRIORITY_ORDER = ["P1", "P2", "P3", "P4"]
PRIORITY_INFO = {
    "P1": {"label": "Immediate", "target_minutes": 0, "color": "red"},
    "P2": {"label": "Very urgent", "target_minutes": 10, "color": "orange"},
    "P3": {"label": "Urgent", "target_minutes": 60, "color": "yellow"},
    "P4": {"label": "Routine", "target_minutes": 120, "color": "green"},
}


def more_urgent(a: str, b: str) -> str:
    return a if PRIORITY_ORDER.index(a) <= PRIORITY_ORDER.index(b) else b


class Reason(BaseModel):
    kind: str  # "red_flag" | "vitals" | "ai_signal" | "suspicious" | "conflict" | "uncertainty" | "default"
    text: str
    priority: str  # the priority this reason argues for
    rule_id: Optional[str] = None
    reference: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)


class RedFlagHit(BaseModel):
    rule_id: str
    label: str
    priority: str
    rationale: str
    reference: Optional[str] = None
    matched: list[str] = Field(default_factory=list)  # canonical symptoms / vitals that matched
    evidence: list[Evidence] = Field(default_factory=list)


class News2Result(BaseModel):
    total: int
    components: dict[str, int]
    params_present: int
    params_total: int = 7
    band: str  # "none" | "low" | "low-medium" | "medium" | "high"
    partial: bool
    applicable: bool  # False for <16 years or pregnancy (NEWS2 not validated there)
    note: Optional[str] = None


class DataQuality(BaseModel):
    avg_confidence: float
    ungrounded_facts: int
    fallback_used: bool
    vitals_present: int
    uncertain: bool
    notes: list[str] = Field(default_factory=list)


class TriageOutput(BaseModel):
    priority: str
    priority_label: str
    target_minutes: int
    sort_score: float
    reasons: list[Reason]
    red_flags: list[RedFlagHit]
    news2: Optional[News2Result]
    data_quality: DataQuality
    detected_symptoms: list[str]
    validation: Optional[ValidationReport] = None  # missing / conflicting / suspicious info + follow-up questions
    needs_human_review: bool = True  # always: the AI never finalises a decision
    engine_version: str
