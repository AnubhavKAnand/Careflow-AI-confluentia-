"""Structured extraction schema.

Every extracted fact carries a confidence and an Evidence link back to the exact
source and character span it came from. This is what powers "click a fact to see
where it came from" on the case page.
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Evidence(BaseModel):
    source_id: Optional[int] = None
    quote: Optional[str] = None  # verbatim text from the source
    start: Optional[int] = None  # char offsets in Source.original_text (set by grounding)
    end: Optional[int] = None
    grounded: Optional[bool] = None  # True if the quote was found in the source
    origin: str = "llm"  # "llm" | "regex" | "lexicon" | "form"
    # True when start/end refer to Source.translated_text instead of the original
    in_translation: bool = False
    # Where to show it in the original file: {"page", "bbox": [x0, y0, x1, y1] (0-1000)} for reports,
    # {"start_s", "end_s"} for voice notes. Set by grounding.attach_locators.
    locator: Optional[dict[str, Any]] = None
    # OCR / speech-recognition confidence of the underlying text (None for typed text)
    source_confidence: Optional[float] = None


class ExtractedValue(BaseModel):
    value: Any = None
    confidence: float = 0.0
    evidence: Optional[Evidence] = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @property
    def present(self) -> bool:
        return self.value not in (None, "", [], {})


class Symptom(BaseModel):
    name: str
    canonical_id: Optional[str] = None  # mapped from rules/symptom_lexicon.yaml
    negated: bool = False  # "no chest pain" / "seene mein dard nahi hai"
    onset: Optional[str] = None
    duration: Optional[str] = None
    severity: Optional[str] = None  # mild | moderate | severe
    progression: Optional[str] = None  # worsening | improving | stable | fluctuating
    body_site: Optional[str] = None
    confidence: float = 0.0
    evidence: Optional[Evidence] = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


class Vitals(BaseModel):
    spo2: ExtractedValue = Field(default_factory=ExtractedValue)  # %
    pulse: ExtractedValue = Field(default_factory=ExtractedValue)  # bpm
    resp_rate: ExtractedValue = Field(default_factory=ExtractedValue)  # breaths/min
    systolic_bp: ExtractedValue = Field(default_factory=ExtractedValue)  # mmHg
    diastolic_bp: ExtractedValue = Field(default_factory=ExtractedValue)
    temperature_c: ExtractedValue = Field(default_factory=ExtractedValue)
    consciousness: ExtractedValue = Field(default_factory=ExtractedValue)  # ACVPU letter
    on_oxygen: ExtractedValue = Field(default_factory=ExtractedValue)  # bool


class TimelineEvent(BaseModel):
    when: str  # "3 days ago", "this morning", "since yesterday"
    event: str
    evidence: Optional[Evidence] = None


class UrgencySignal(BaseModel):
    signal: str
    evidence: Optional[Evidence] = None


class LabResult(BaseModel):
    name: str
    canonical_id: Optional[str] = None  # hemoglobin | platelets | wbc | glucose | creatinine | potassium | sodium | hba1c | troponin
    value: Any = None  # number, or "positive"/"negative" for qualitative tests
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    abnormal_flag: Optional[str] = None  # as printed on the report: high | low | critical | normal
    confidence: float = 0.0
    evidence: Optional[Evidence] = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


class SourceFlag(BaseModel):
    """A problem with an input itself (blurry scan, unclear audio, uncertain translation)."""

    source_id: int
    kind: str  # low_ocr_confidence | poor_legibility | unreadable | low_asr_confidence | uncertain_language |
    #            low_translation_confidence | translation_unavailable | processing_failed | truncated
    detail: str
    severity: str = "warning"  # "warning" | "critical"


class Discrepancy(BaseModel):
    """Two sources (or the model and a deterministic check) disagree. Surfaced, never silently fixed."""

    field: str
    values: list[Any]
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)


class Extraction(BaseModel):
    chief_complaint: ExtractedValue = Field(default_factory=ExtractedValue)
    age_years: ExtractedValue = Field(default_factory=ExtractedValue)
    sex: ExtractedValue = Field(default_factory=ExtractedValue)
    pregnancy_status: ExtractedValue = Field(default_factory=ExtractedValue)  # pregnant|not_pregnant|unknown
    symptoms: list[Symptom] = Field(default_factory=list)
    vitals: Vitals = Field(default_factory=Vitals)
    labs: list[LabResult] = Field(default_factory=list)
    medical_history: list[ExtractedValue] = Field(default_factory=list)
    medications: list[ExtractedValue] = Field(default_factory=list)
    allergies: list[ExtractedValue] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    urgency_signals: list[UrgencySignal] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    # Filled by our own code, not the model
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    source_flags: list[SourceFlag] = Field(default_factory=list)
    provider: Optional[str] = None
    fallback_used: bool = False
    provider_errors: list[str] = Field(default_factory=list)


ACVPU = Literal["A", "C", "V", "P", "U"]
