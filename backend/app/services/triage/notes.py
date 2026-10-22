"""Draft triage / referral note. Template-based on purpose: every sentence is traceable to
extracted facts or rule output, and nothing is invented or diagnosed."""
from typing import Optional

from app.models.patient import Patient
from app.schemas.extraction import Extraction
from app.schemas.triage import TriageOutput

DISCLAIMER = (
    "AI-generated DRAFT for clinical review. Not a diagnosis. Priority is a suggestion only; "
    "the final triage decision must be made by a qualified healthcare professional."
)

_VITAL_LABELS = [
    ("spo2", "SpO2", "%"), ("pulse", "Pulse", " bpm"), ("resp_rate", "Resp. rate", "/min"),
    ("temperature_c", "Temp", " °C"), ("consciousness", "ACVPU", ""), ("on_oxygen", "On oxygen", ""),
]


def _fmt(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def _src(ev) -> str:
    if ev is None or ev.source_id is None:
        return " [registration]" if ev is not None and ev.origin == "form" else ""
    return f" [src {ev.source_id}]"


def _symptom_line(s) -> str:
    bits = [s.name]
    details = [x for x in (s.severity, s.progression, s.duration, s.onset and f"onset {s.onset}") if x]
    if details:
        bits.append(f"({', '.join(details)})")
    conf = "" if s.confidence >= 0.6 else f" — low confidence {s.confidence:.2f}"
    return " ".join(bits) + _src(s.evidence) + conf


_KIND = {"patient_message": "Patient message", "intake_form": "Intake form", "report": "Report", "voice": "Voice note"}


def generate_note(patient: Optional[Patient], ex: Extraction, tri: TriageOutput, sources: Optional[list] = None) -> str:
    L: list[str] = []
    L.append("TRIAGE NOTE (DRAFT)")
    L.append(DISCLAIMER)
    L.append("")

    name = patient.name if patient else "Unknown"
    age = ex.age_years.value if ex.age_years.present else "age not stated"
    sex = ex.sex.value if ex.sex.present else "sex not stated"
    preg = " · pregnant" if ex.pregnancy_status.value == "pregnant" else ""
    L.append(f"Patient: {name} · {age}{' y' if isinstance(age, (int, float)) else ''} · {sex}{preg}")
    when = "review immediately" if tri.target_minutes == 0 else f"review within {tri.target_minutes} min"
    L.append(f"Suggested priority: {tri.priority} — {tri.priority_label} ({when})")
    L.append("")

    L.append("Presenting complaint:")
    L.append(f"  {ex.chief_complaint.value or 'Not clearly stated'}{_src(ex.chief_complaint.evidence)}")
    L.append("")

    present = [s for s in ex.symptoms if not s.negated]
    denied = [s for s in ex.symptoms if s.negated]
    L.append("Symptoms reported:")
    L.extend(f"  - {_symptom_line(s)}" for s in present) if present else L.append("  - None extracted")
    if denied:
        L.append("Denied: " + ", ".join(s.name for s in denied))
    if ex.timeline:
        L.append("Timeline:")
        L.extend(f"  - {t.when}: {t.event}{_src(t.evidence)}" for t in ex.timeline[:8])
    L.append("")

    L.append("Vital signs:")
    vit = []
    for key, label, unit in _VITAL_LABELS:
        v = getattr(ex.vitals, key)
        if v.present:
            vit.append(f"{label} {_fmt(v.value)}{unit}{_src(v.evidence)}")
    if ex.vitals.systolic_bp.present:
        dia = ex.vitals.diastolic_bp.value if ex.vitals.diastolic_bp.present else "?"
        vit.append(f"BP {_fmt(ex.vitals.systolic_bp.value)}/{_fmt(dia)} mmHg{_src(ex.vitals.systolic_bp.evidence)}")
    L.append("  " + ("; ".join(vit) if vit else "Not recorded"))
    if tri.news2:
        L.append(f"  NEWS2: {tri.news2.total} ({tri.news2.band})" + (f" — {tri.news2.note}" if tri.news2.note else ""))
    L.append("")

    if ex.labs:
        L.append("Lab results:")
        for lab in ex.labs:
            val = _fmt(lab.value) if lab.value is not None else "?"
            unit = f" {lab.unit}" if lab.unit else ""
            rng = f" (ref {lab.reference_range})" if lab.reference_range else ""
            flag = f" [{lab.abnormal_flag}]" if lab.abnormal_flag and lab.abnormal_flag != "normal" else ""
            conf = "" if lab.confidence >= 0.6 else f" — low confidence {lab.confidence:.2f}, verify on report"
            L.append(f"  - {lab.name}: {val}{unit}{rng}{flag}{_src(lab.evidence)}{conf}")
        L.append("")

    for title, items in (("History", ex.medical_history), ("Medications", ex.medications), ("Allergies", ex.allergies)):
        if items:
            L.append(f"{title}: " + "; ".join(f"{i.value}{_src(i.evidence)}" for i in items))
    if ex.medical_history or ex.medications or ex.allergies:
        L.append("")

    L.append("Warning flags:")
    if tri.red_flags:
        for f in tri.red_flags:
            srcs = sorted({e.source_id for e in f.evidence if e and e.source_id is not None})
            where = f" [src {', '.join(map(str, srcs))}]" if srcs else ""
            L.append(f"  - [{f.priority}] {f.label}{where}")
    else:
        L.append("  - None detected by rules")
    L.append("")

    v = tri.validation
    if v and v.flags:
        titles = {"suspicious": "Suspicious content", "conflicting": "Conflicting information",
                  "unclear": "Unclear / low-confidence information", "missing": "Missing information"}
        for kind, title in titles.items():
            items = [f for f in v.flags if f.type == kind and f.severity != "info"]
            if items:
                L.append(f"{title}:")
                L.extend(f"  - {'[!] ' if f.severity == 'critical' else ''}{f.text}" for f in items)
        L.append(f"Information completeness: {v.completeness:.0%}")
        L.append("")
    else:
        concerns = tri.data_quality.notes + [d.detail for d in ex.discrepancies] + ex.uncertainties
        if concerns:
            L.append("Data quality / items to verify:")
            L.extend(f"  - {c}" for c in dict.fromkeys(concerns))
            L.append("")

    if v and v.followups:
        L.append("Suggested follow-up questions:")
        for q in v.followups[:10]:
            who = {"patient": "Ask patient", "staff": "Staff", "clinician": "Clinician"}[q.target]
            extra = f" ({q.text_en})" if q.language != "en" else ""
            tag = " [AI-suggested]" if q.origin == "ai" else ""
            L.append(f"  - {who}: {q.text}{extra}{tag}")
        L.append("")

    if sources:
        L.append("Sources:")
        for src in sources:
            meta = src.meta or {}
            bits = [_KIND.get(src.kind, src.kind)]
            if src.language:
                bits.append(f"language {src.language}")
            if meta.get("engine") and src.kind in ("report", "voice"):
                bits.append(f"read by {meta['engine']} ({meta.get('avg_confidence', 0):.2f})")
            if src.translated_text:
                bits.append(f"translated ({src.translation_confidence or 0:.2f})")
            L.append(f"  [src {src.id}] " + ", ".join(bits))
        L.append("")

    L.append("Clinician assessment: ____________________________")
    L.append("Final priority: ____    Disposition / referral: ____________________")
    return "\n".join(L)
