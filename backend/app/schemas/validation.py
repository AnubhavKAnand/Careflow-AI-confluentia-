"""Validation report: what is missing, unclear, conflicting or suspicious, and what to ask next."""
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.extraction import Evidence


class MissingItem(BaseModel):
    id: str
    checklist: str
    label: str
    priority: str  # critical | important | nice
    target: str  # patient | staff


class Conflict(BaseModel):
    id: str
    kind: str  # vitals | labs | demographics | symptom | wrong_patient | stale_report | allergy | pregnancy | ...
    detail: str
    severity: str  # warning | critical
    evidence: list[Evidence] = Field(default_factory=list)


class InjectionFinding(BaseModel):
    source_id: Optional[int] = None
    pattern: str
    text: str
    start: Optional[int] = None
    end: Optional[int] = None
    in_translation: bool = False


class FollowUp(BaseModel):
    id: str
    text: str  # in the language chosen for the asker (patient language for patient questions)
    text_en: str
    language: str  # en | hi | hi_latn
    target: str  # patient | staff | clinician
    priority: str  # critical | important | nice
    reason: str
    origin: str = "rule"  # rule | conflict | quality | ai
    answer_type: str = "free_text"  # yes_no | free_text
    symptom: Optional[str] = None  # canonical id a yes/no answer maps to


class Flag(BaseModel):
    """One row in the 'flags' panel: the four kinds the problem statement asks to surface."""

    type: str  # missing | unclear | conflicting | suspicious
    severity: str  # info | warning | critical
    text: str
    source_ids: list[int] = Field(default_factory=list)
    ref: Optional[str] = None  # id of the underlying item


class ValidationReport(BaseModel):
    missing: list[MissingItem] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    injections: list[InjectionFinding] = Field(default_factory=list)
    followups: list[FollowUp] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    completeness: float = 1.0  # weighted share of applicable checklist items that are satisfied
    checklists_applied: list[str] = Field(default_factory=list)
