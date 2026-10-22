"""Validation layer: missing information, conflicts, suspicious instructions, follow-up questions."""
from typing import Optional

from app.models.case import Source
from app.models.patient import Patient
from app.schemas.extraction import Extraction
from app.schemas.validation import Flag, InjectionFinding, ValidationReport
from app.services.validation import injection
from app.services.validation.conflicts import find_conflicts
from app.services.validation.followups import ai_followups, patient_language, rule_followups
from app.services.validation.missing import find_missing
from app.services.triage.content import has_clinical_content


def scan_injections(sources: list[Source]) -> None:
    """Detect embedded instructions in every source (original + translation) and store them in source.meta.
    Run before extraction so the spans can be masked from the language model."""
    for s in sources:
        meta = dict(s.meta or {})
        found = [dict(f.__dict__, in_translation=False) for f in injection.detect(s.original_text)]
        found += [dict(f.__dict__, in_translation=True) for f in injection.detect(s.translated_text or "")]
        meta["injection"] = found
        s.meta = meta


def injections_from_sources(sources: list[Source], ex: Extraction) -> list[InjectionFinding]:
    out = [InjectionFinding(source_id=s.id, pattern=f["pattern"], text=f["text"], start=f["start"], end=f["end"],
                            in_translation=f.get("in_translation", False))
           for s in sources for f in (s.meta or {}).get("injection", [])]
    # the model is told to report embedded instructions it notices; keep those too
    for u in ex.uncertainties:
        if "embedded instruction" in u.lower() and not out:
            out.append(InjectionFinding(pattern="model_reported", text=u))
    return out


def build_flags(report: ValidationReport, ex: Extraction) -> list[Flag]:
    flags: list[Flag] = []
    for i in report.injections:
        flags.append(Flag(type="suspicious", severity="critical", ref=i.pattern,
                          source_ids=[i.source_id] if i.source_id is not None else [],
                          text=f"Possible instruction aimed at the AI in source {i.source_id}: “{i.text[:80]}”. "
                               "It was ignored and hidden from the model. Check the document's authenticity."))
    for c in report.conflicts:
        flags.append(Flag(type="conflicting", severity=c.severity, text=c.detail, ref=c.id,
                          source_ids=sorted({e.source_id for e in c.evidence if e.source_id is not None})))
    for f in ex.source_flags:
        flags.append(Flag(type="unclear", severity=f.severity, text=f.detail, ref=f.kind, source_ids=[f.source_id]))
    for lab in ex.labs:
        if lab.confidence < 0.6:
            flags.append(Flag(type="unclear", severity="warning", ref=f"lab:{lab.canonical_id}",
                              source_ids=[lab.evidence.source_id] if lab.evidence and lab.evidence.source_id else [],
                              text=f"{lab.name} was read with low confidence ({lab.confidence:.2f})."))
    if not has_clinical_content(ex):
        flags.append(Flag(type="unclear", severity="warning", ref="nothing_extracted",
                          text="No symptom or test result could be identified. Ask the patient to describe the main problem."))
    for s in ex.symptoms:
        if s.evidence and s.evidence.grounded is False:
            flags.append(Flag(type="unclear", severity="warning", ref=f"ungrounded:{s.name}",
                              text=f"'{s.name}' could not be traced to the source text (possible model error)."))
    sev = {"critical": "critical", "important": "warning", "nice": "info"}
    for m in report.missing:
        flags.append(Flag(type="missing", severity=sev[m.priority], ref=m.id,
                          text=f"Missing: {m.label}" + (" (staff to measure)" if m.target == "staff" else "")))
    order = {"critical": 0, "warning": 1, "info": 2}
    kind = {"suspicious": 0, "conflicting": 1, "unclear": 2, "missing": 3}
    flags.sort(key=lambda f: (order[f.severity], kind[f.type]))
    return flags


def validate(ex: Extraction, sources: list[Source], patient: Optional[Patient], red_flag_ids: set[str],
             with_ai: bool = True) -> tuple[ValidationReport, Optional[str]]:
    missing, completeness, applied, defs = find_missing(ex, sources, red_flag_ids)
    conflicts = find_conflicts(ex, sources, patient)
    report = ValidationReport(missing=missing, conflicts=conflicts, completeness=completeness,
                              checklists_applied=applied, injections=injections_from_sources(sources, ex))
    lang = patient_language(patient, sources)
    report.followups = rule_followups(missing, defs, conflicts, ex, lang)
    ai_model = None
    if with_ai:
        extra, ai_model = ai_followups(ex, report.followups, lang)
        report.followups += extra
    report.flags = build_flags(report, ex)
    return report, ai_model
