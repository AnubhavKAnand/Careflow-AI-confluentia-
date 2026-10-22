"""Conflict checks that go beyond the extractor's value-level discrepancies.

All of these are surfaced to the clinician; none of them silently changes a value.
"""
import re
from datetime import date, datetime, timezone
from typing import Optional

from app.models.case import Source
from app.models.patient import Patient
from app.schemas.extraction import Evidence, Extraction
from app.schemas.validation import Conflict
from app.services.triage.text_match import label_for, scan

STALE_REPORT_DAYS = 30

_NAME = re.compile(r"\b(?:patient(?:'s)?\s*name|name\s+of\s+(?:the\s+)?patient|pt\.?\s*name|name)\s*[:\-]\s*([A-Za-z][A-Za-z .']{1,60})", re.I)
_HONORIFIC = re.compile(r"\b(?:mr|mrs|ms|miss|master|baby|smt|shri|sri|kumari|km|dr|late)\.?\s+", re.I)
_DATE = re.compile(
    r"\b(?:report(?:ed)?|collected|collection|sample|test|date)\s*(?:date|on|time)?\s*[:\-]?\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})",
    re.I,
)
# allergen -> medicines that are, or commonly cross-react with, that allergen (indicative, not exhaustive)
ALLERGY_MAP = {
    "penicillin": ["penicillin", "amoxicillin", "amoxycillin", "ampicillin", "augmentin", "cloxacillin", "piperacillin"],
    "sulfa": ["sulfamethoxazole", "cotrimoxazole", "co-trimoxazole", "septran", "bactrim", "sulfasalazine"],
    "nsaid": ["ibuprofen", "diclofenac", "aspirin", "naproxen", "ketorolac", "aceclofenac", "nimesulide"],
    "aspirin": ["aspirin", "ecosprin", "disprin"],
    "cephalosporin": ["ceftriaxone", "cefixime", "cefuroxime", "cephalexin", "cefpodoxime"],
}


def _norm_name(s: str) -> set[str]:
    s = _HONORIFIC.sub("", s.lower())
    s = re.split(r"\s{2,}|\b(?:age|sex|years?|yrs?|ref|uhid|id|date)\b", s)[0]
    return {t for t in re.findall(r"[a-z]{2,}", s)}


def wrong_patient(patient: Optional[Patient], sources: list[Source]) -> list[Conflict]:
    out: list[Conflict] = []
    if not patient or not patient.name:
        return out
    reg = _norm_name(patient.name)
    for s in sources:
        if s.kind != "report" or not s.original_text:
            continue
        m = _NAME.search(s.original_text)
        if not m:
            continue
        doc = _norm_name(m.group(1))
        if doc and reg and not (doc & reg):
            out.append(Conflict(
                id=f"wrong_patient:{s.id}", kind="wrong_patient", severity="critical",
                detail=f"Name on report ('{m.group(1).strip()}') does not match the registered patient ('{patient.name}'). "
                       "This may be another person's report; verify before using its values.",
                evidence=[Evidence(source_id=s.id, quote=m.group(0), start=m.start(), end=m.end(), grounded=True, origin="regex")],
            ))
    return out


def report_dates(sources: list[Source], today: Optional[date] = None) -> list[Conflict]:
    today = today or datetime.now(timezone.utc).date()
    out: list[Conflict] = []
    for s in sources:
        if s.kind != "report" or not s.original_text:
            continue
        m = _DATE.search(s.original_text)
        if not m:
            continue
        d, mo, y = (int(g) for g in m.groups())
        y = y + 2000 if y < 100 else y
        try:
            rep = date(y, mo, d)  # Indian reports use DD-MM-YYYY
        except ValueError:
            continue
        ev = [Evidence(source_id=s.id, quote=m.group(0), start=m.start(), end=m.end(), grounded=True, origin="regex")]
        age_days = (today - rep).days
        if age_days < -1:
            out.append(Conflict(id=f"future_report:{s.id}", kind="report_date", severity="warning", evidence=ev,
                                detail=f"Report date {rep:%d-%m-%Y} is in the future; the date may be misread or wrong."))
        elif age_days > STALE_REPORT_DAYS:
            out.append(Conflict(id=f"stale_report:{s.id}", kind="stale_report", severity="warning", evidence=ev,
                                detail=f"Report is {age_days} days old ({rep:%d-%m-%Y}); values may not reflect the current condition."))
    return out


def cross_source_symptoms(sources: list[Source]) -> list[Conflict]:
    """A symptom stated in one source and denied in another (e.g. message vs voice note)."""
    present: dict[str, list[tuple[Source, object]]] = {}
    denied: dict[str, list[tuple[Source, object]]] = {}
    for s in sources:
        if s.kind == "intake_form":
            continue
        for m in scan(s.original_text):
            (denied if m.negated else present).setdefault(m.canonical_id, []).append((s, m))
    out: list[Conflict] = []
    for cid in present.keys() & denied.keys():
        p_src = {s.id for s, _ in present[cid]}
        d_src = {s.id for s, _ in denied[cid]}
        if p_src - d_src and d_src - p_src:
            ev = [Evidence(source_id=s.id, quote=m.text, start=m.start, end=m.end, grounded=True, origin="lexicon")  # type: ignore[attr-defined]
                  for s, m in present[cid][:1] + denied[cid][:1]]
            out.append(Conflict(id=f"symptom:{cid}", kind="symptom", severity="warning", evidence=ev,
                                detail=f"'{label_for(cid)}' is reported in source {min(p_src - d_src)} but denied in source "
                                       f"{min(d_src - p_src)}. Please clarify with the patient."))
    return out


def denied_vs_measured(ex: Extraction) -> list[Conflict]:
    denied = {s.canonical_id: s for s in ex.symptoms if s.negated and s.canonical_id}
    present = {s.canonical_id for s in ex.symptoms if not s.negated and s.canonical_id}
    out: list[Conflict] = []
    t = ex.vitals.temperature_c.value
    if "fever" in denied and "fever" not in present and isinstance(t, (int, float)) and t >= 38.0:
        out.append(Conflict(id="fever_denied_measured", kind="symptom", severity="warning",
                            detail=f"Patient denies fever, but measured temperature is {t:g} °C.",
                            evidence=[e for e in (denied["fever"].evidence, ex.vitals.temperature_c.evidence) if e]))
    sp, rr = ex.vitals.spo2.value, ex.vitals.resp_rate.value
    if "breathlessness" in denied and "breathlessness" not in present and (
        (isinstance(sp, (int, float)) and sp < 92) or (isinstance(rr, (int, float)) and rr >= 25)
    ):
        out.append(Conflict(id="breath_denied_measured", kind="symptom", severity="warning",
                            detail=f"Patient denies breathlessness, but SpO2 is {sp} and breathing rate is {rr}.",
                            evidence=[e for e in (denied["breathlessness"].evidence, ex.vitals.spo2.evidence) if e]))
    return out


def demographic_consistency(ex: Extraction) -> list[Conflict]:
    out: list[Conflict] = []
    age = ex.age_years.value if isinstance(ex.age_years.value, (int, float)) else None
    if ex.pregnancy_status.value == "pregnant":
        if ex.sex.value == "male":
            out.append(Conflict(id="pregnancy_sex", kind="pregnancy", severity="critical",
                                detail="Pregnancy is mentioned but the patient is registered as male. Check registration and source.",
                                evidence=[e for e in [ex.pregnancy_status.evidence] if e]))
        elif age is not None and (age < 10 or age > 55):
            out.append(Conflict(id="pregnancy_age", kind="pregnancy", severity="warning",
                                detail=f"Pregnancy is mentioned for a patient aged {age:g}. Please verify.",
                                evidence=[e for e in [ex.pregnancy_status.evidence] if e]))
    return out


def allergy_medication(ex: Extraction) -> list[Conflict]:
    out: list[Conflict] = []
    meds = [(m, str(m.value).lower()) for m in ex.medications if m.value]
    for a in ex.allergies:
        allergen = str(a.value or "").lower()
        for key, drugs in ALLERGY_MAP.items():
            if key not in allergen:
                continue
            for m, mname in meds:
                if any(d in mname for d in drugs):
                    out.append(Conflict(id=f"allergy:{key}:{mname[:20]}", kind="allergy", severity="warning",
                                        detail=f"Patient reports {a.value} allergy and is taking {m.value}. Please review.",
                                        evidence=[e for e in (a.evidence, m.evidence) if e]))
    return out


def from_discrepancies(ex: Extraction) -> list[Conflict]:
    out = []
    for i, d in enumerate(ex.discrepancies):
        kind = d.field.split(".")[0]
        if d.field in ("age_years", "sex"):
            kind = "demographics"
        out.append(Conflict(id=f"disc:{i}:{d.field}", kind=kind, severity="warning", detail=d.detail, evidence=d.evidence))
    return out


def find_conflicts(ex: Extraction, sources: list[Source], patient: Optional[Patient]) -> list[Conflict]:
    found = (from_discrepancies(ex) + wrong_patient(patient, sources) + report_dates(sources)
             + cross_source_symptoms(sources) + denied_vs_measured(ex) + demographic_consistency(ex) + allergy_medication(ex))
    unique: dict[str, Conflict] = {}
    for c in found:
        unique.setdefault(c.id, c)
    return sorted(unique.values(), key=lambda c: c.severity != "critical")
