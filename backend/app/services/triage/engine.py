"""Triage engine: combines independent signals into a suggested priority with reasons.

Safety invariants (enforced here and covered by tests):
  1. The final suggestion is the MOST urgent of all signals. No signal can lower another.
  2. Red-flag rules and NEWS2 are deterministic and explainable; every reason links to evidence.
  3. Model-identified urgency signals can raise a routine case to P3 for human review, never higher on their own.
  4. Low data quality raises a routine case to P3 rather than letting it sit unseen.
  5. The output is always a SUGGESTION (needs_human_review=True). A clinician sets the final priority.

Phase 6 adds the shadow-trained agent as one more signal, under the same invariants.
"""
from typing import Optional

from app.config import get_settings
from app.schemas.extraction import Evidence, Extraction
from app.schemas.validation import ValidationReport
from app.schemas.triage import (
    PRIORITY_INFO,
    DataQuality,
    Reason,
    TriageOutput,
    more_urgent,
)
from app.services.triage import red_flags
from app.services.triage.vitals_score import compute_news2, news2_priority
from app.services.triage.content import has_clinical_content

BASE_SCORE = {"P1": 90, "P2": 70, "P3": 45, "P4": 20}


def present_symptoms(ex: Extraction) -> dict[str, list[Evidence]]:
    out: dict[str, list[Evidence]] = {}
    for s in ex.symptoms:
        if s.negated or not s.canonical_id:
            continue
        out.setdefault(s.canonical_id, [])
        if s.evidence:
            out[s.canonical_id].append(s.evidence)
    return out


def assess_quality(ex: Extraction, validation: Optional[ValidationReport] = None) -> DataQuality:
    s = get_settings()
    confs = [v.confidence for v in (ex.chief_complaint, ex.age_years, ex.sex) if v.present]
    confs += [sym.confidence for sym in ex.symptoms]
    confs += [lab.confidence for lab in ex.labs]
    confs += [getattr(ex.vitals, f).confidence for f in type(ex.vitals).model_fields if getattr(ex.vitals, f).present]
    avg = round(sum(confs) / len(confs), 3) if confs else 0.0
    ungrounded = sum(1 for sym in ex.symptoms if sym.evidence is not None and sym.evidence.grounded is False)
    vitals_present = sum(1 for f in type(ex.vitals).model_fields if getattr(ex.vitals, f).present)

    notes: list[str] = []
    serious_flags = [f for f in ex.source_flags if f.severity in ("warning", "critical")]
    for f in serious_flags:
        notes.append(f"Source {f.source_id}: {f.detail}")
    if not has_clinical_content(ex):
        notes.append("No recognisable symptom or test result could be extracted.")
    if avg < s.low_confidence_threshold:
        notes.append(f"Average extraction confidence is low ({avg:.2f}).")
    if ungrounded:
        notes.append(f"{ungrounded} extracted fact(s) could not be traced to the source text.")
    if ex.fallback_used:
        notes.append("Language models were unavailable; deterministic fallback extraction was used.")
    if ex.discrepancies:
        notes.append(f"{len(ex.discrepancies)} conflicting value(s) between sources.")
    if vitals_present == 0:
        notes.append("No vital signs available.")

    low_labs = [lab for lab in ex.labs if lab.confidence < s.low_confidence_threshold]
    if low_labs:
        notes.append(f"{len(low_labs)} lab value(s) read with low confidence: " + ", ".join(lab.name for lab in low_labs) + ".")
    if validation:
        if validation.injections:
            notes.append("Suspicious instruction found in an input.")
        extra = [c for c in validation.conflicts if not c.id.startswith("disc:")]
        if extra:
            notes.append(f"{len(extra)} further conflict(s) found (see flags).")
    uncertain = bool(validation and (validation.injections or validation.conflicts)) or (not has_clinical_content(ex)) or bool(serious_flags) or bool(low_labs) or avg < s.low_confidence_threshold or ex.fallback_used or ungrounded > 0 or bool(ex.discrepancies)
    return DataQuality(
        avg_confidence=avg, ungrounded_facts=ungrounded, fallback_used=ex.fallback_used,
        vitals_present=vitals_present, uncertain=uncertain, notes=notes,
    )


def compute_triage(ex: Extraction, validation: Optional[ValidationReport] = None) -> TriageOutput:
    settings = get_settings()
    age = ex.age_years.value if isinstance(ex.age_years.value, (int, float)) else None
    pregnant = ex.pregnancy_status.value == "pregnant"
    symptoms = present_symptoms(ex)

    priority = "P4"
    reasons: list[Reason] = []

    # 1. Deterministic red flags
    labs = {}
    for lab in ex.labs:
        if lab.canonical_id and lab.canonical_id not in labs:
            labs[lab.canonical_id] = lab
    flags = red_flags.evaluate(symptoms, ex.vitals, age_years=age, pregnant=pregnant, labs=labs)
    for f in flags:
        priority = more_urgent(priority, f.priority)
        reasons.append(Reason(kind="red_flag", text=f"{f.label}: {f.rationale}", priority=f.priority,
                              rule_id=f.rule_id, reference=f.reference, evidence=f.evidence))

    # 2. NEWS2 vitals score
    news = compute_news2(ex.vitals, age_years=age, pregnant=pregnant)
    if news and news.applicable:
        np_ = news2_priority(news)
        if np_:
            priority = more_urgent(priority, np_)
            ev = [getattr(ex.vitals, k).evidence for k in news.components if getattr(ex.vitals, k).evidence]
            reasons.append(Reason(kind="vitals", text=f"NEWS2 score {news.total} ({news.band} risk)"
                                  + (f"; {news.note}" if news.partial else ""),
                                  priority=np_, reference="NEWS2, Royal College of Physicians 2017", evidence=ev))

    # 3. Model-identified urgency signals: may raise routine -> P3 for review, never higher
    if ex.urgency_signals:
        target = more_urgent(priority, "P3")
        priority = target
        for u in ex.urgency_signals:
            reasons.append(Reason(kind="ai_signal", text=f"AI-noted signal for review: {u.signal}", priority="P3",
                                  evidence=[u.evidence] if u.evidence else []))

    # 4. Suspicious instructions and critical conflicts need a human to look, whatever else the case shows
    if validation:
        if validation.injections:
            priority = more_urgent(priority, "P3")
            srcs = sorted({i.source_id for i in validation.injections if i.source_id is not None})
            reasons.append(Reason(kind="suspicious", priority="P3",
                                  text="Input contains text that tries to instruct the AI "
                                       f"(source {', '.join(map(str, srcs)) or 'unknown'}). It was ignored and hidden from the model; "
                                       "verify the document is genuine.",
                                  evidence=[Evidence(source_id=i.source_id, quote=i.text, start=i.start, end=i.end,
                                                     grounded=i.start is not None, origin="regex", in_translation=i.in_translation)
                                            for i in validation.injections if i.source_id is not None]))
        for c in validation.conflicts:
            if c.severity == "critical":
                priority = more_urgent(priority, "P3")
                reasons.append(Reason(kind="conflict", priority="P3", text=c.detail, evidence=c.evidence))

    # 5. Uncertainty never lets a case sit at routine. An unreadable report/voice note could hide anything.
    critical_src = [f for f in ex.source_flags if f.severity == "critical"]
    for f in critical_src:
        priority = more_urgent(priority, "P3")
        reasons.append(Reason(kind="uncertainty", priority="P3",
                              text=f"Source {f.source_id} could not be processed: {f.detail}",
                              evidence=[Evidence(source_id=f.source_id)]))
    quality = assess_quality(ex, validation)
    if quality.uncertain:
        if priority == "P4":
            priority = "P3"
        reasons.append(Reason(kind="uncertainty",
                              text="Data quality concerns: " + " ".join(quality.notes) + " A clinician should verify.",
                              priority="P3"))

    if not reasons:
        reasons.append(Reason(kind="default", text="No warning signs detected in the information provided.", priority="P4"))

    news_bonus = min(news.total, 10) if news else 0
    sort_score = BASE_SCORE[priority] + news_bonus + min(len(flags), 5) * 2 - (0 if quality.uncertain else 1)

    order = {"red_flag": 0, "vitals": 1, "suspicious": 2, "conflict": 3, "ai_signal": 4, "uncertainty": 5, "default": 6}
    reasons.sort(key=lambda r: (r.priority, order[r.kind]))
    return TriageOutput(
        priority=priority,
        priority_label=PRIORITY_INFO[priority]["label"],
        target_minutes=PRIORITY_INFO[priority]["target_minutes"],
        sort_score=float(sort_score),
        reasons=reasons,
        red_flags=flags,
        news2=news,
        data_quality=quality,
        detected_symptoms=sorted(symptoms),
        validation=validation,
        engine_version=settings.engine_version,
    )
