"""Extraction orchestrator.

    model (small local model -> Gemini fallback -> deterministic rules)
      -> normalise loose model JSON
      -> merge deterministic vitals / demographics / symptom scan (disagreements recorded, never hidden)
      -> ground every quote to an exact source span
"""
import re
import time
from typing import Any

from pydantic import ValidationError

from app.config import get_settings
from app.models.case import Source
from app.models.patient import Patient
from app.schemas.extraction import Discrepancy, Evidence, ExtractedValue, Extraction, LabResult, SourceFlag, Symptom
from app.services.extraction import prompts
from app.services.extraction.grounding import attach_locators, ground_evidence, ground_extraction
from app.services.extraction.rule_extractor import CONF_LEXICON, rule_extract, timeline_from_sources
from app.services.extraction.labs_regex import LAB_LABELS, extract_labs
from app.services.extraction.vitals_regex import Hit, extract_demographics, extract_vitals
from app.services.llm import LLMError, LLMProvider, provider_chain
from app.services.triage.text_match import canonicalize, label_for, load_lexicon, scan

CONF_REGEX = 0.9
CONF_FORM = 0.98

# How far apart two readings must be before we call it a discrepancy
TOLERANCE = {"spo2": 1, "pulse": 5, "resp_rate": 2, "systolic_bp": 5, "diastolic_bp": 5, "temperature_c": 0.3}
# "Normal" anchor used to pick the more concerning of two conflicting readings (safety-first)
NORMAL = {"spo2": 100, "pulse": 75, "resp_rate": 16, "systolic_bp": 120, "diastolic_bp": 80, "temperature_c": 37.0}
NUMERIC_VITALS = list(NORMAL)


# ---------------------------------------------------------------- model output normalisation
def _ev(x: Any) -> dict | None:
    if isinstance(x, dict):
        x = dict(x)
        if x.pop("from_translation", False):
            x["in_translation"] = True
        return x
    if isinstance(x, str) and x.strip():
        return {"quote": x}
    return None


def _vf(x: Any) -> dict:
    if isinstance(x, dict) and ("value" in x or "confidence" in x or "evidence" in x):
        out = dict(x)
        out["evidence"] = _ev(out.get("evidence"))
        return out
    if x in (None, "", "null", "unknown"):
        return {"value": None}
    return {"value": x, "confidence": 0.6}


def _num(v: Any) -> Any:
    if isinstance(v, (int, float)) or v is None:
        return v
    try:
        return float(str(v).replace("%", "").replace("°", "").strip().split()[0])
    except (ValueError, IndexError):
        return None


_COMPACT_DEFAULT_CONF = 0.8


def _compact_item(x: Any, text_key: str = "value") -> Any:
    """Compact shape: {"...", "quote": "..."} -> evidence object."""
    if isinstance(x, dict) and "quote" in x and "evidence" not in x:
        x = dict(x)
        x["evidence"] = _ev(x.pop("quote"))
        x.setdefault("confidence", _COMPACT_DEFAULT_CONF)
    return x


def _upgrade_compact(raw: dict[str, Any]) -> dict[str, Any]:
    """Map the compact prompt shape onto the full Extraction shape (old shape passes through)."""
    raw = dict(raw)
    if "pregnant" in raw and "pregnancy_status" not in raw:
        pv = raw.pop("pregnant")
        raw["pregnancy_status"] = {True: "pregnant", False: "not_pregnant"}.get(pv) if isinstance(pv, bool) else pv
    if "history" in raw and "medical_history" not in raw:
        raw["medical_history"] = raw.pop("history")
    for k in ("chief_complaint", "age_years", "sex", "pregnancy_status"):
        v = raw.get(k)
        if v is not None and not isinstance(v, dict):
            raw[k] = {"value": v, "confidence": _COMPACT_DEFAULT_CONF}
    vit = raw.get("vitals")
    if isinstance(vit, dict):
        raw["vitals"] = {k: ({"value": v, "confidence": _COMPACT_DEFAULT_CONF} if v is not None and not isinstance(v, dict) else v)
                         for k, v in vit.items()}
    lex = None
    syms = []
    for sym in raw.get("symptoms") or []:
        sym = _compact_item(sym)
        if isinstance(sym, dict):
            sid = sym.pop("id", None)
            if sid and sid != "other":
                if lex is None:
                    from app.services.triage.text_match import label_for, load_lexicon
                    lex = load_lexicon()
                if sid in lex:
                    sym["canonical_id"] = sid
                    if not sym.get("name"):
                        sym["name"] = label_for(sid)
        syms.append(sym)
    if syms:
        raw["symptoms"] = syms
    for k in ("labs", "urgency_signals"):
        if raw.get(k):
            raw[k] = [_compact_item(x) for x in raw[k]]
    return raw


def normalize_model_output(raw: dict[str, Any]) -> dict[str, Any]:
    raw = _upgrade_compact(raw or {})
    out: dict[str, Any] = {}
    for k in ("chief_complaint", "age_years", "sex", "pregnancy_status"):
        out[k] = _vf(raw.get(k))
    if out["age_years"].get("value") is not None:
        out["age_years"]["value"] = _num(out["age_years"]["value"])
    syms = []
    for s in raw.get("symptoms") or []:
        if isinstance(s, str):
            s = {"name": s, "confidence": 0.6}
        if isinstance(s, dict) and s.get("name"):
            s = dict(s)
            s["evidence"] = _ev(s.get("evidence"))
            syms.append(s)
    out["symptoms"] = syms
    vit = raw.get("vitals") or {}
    out["vitals"] = {}
    for k in (*NUMERIC_VITALS, "consciousness", "on_oxygen"):
        f = _vf(vit.get(k))
        if k in NUMERIC_VITALS:
            f["value"] = _num(f.get("value"))
        out["vitals"][k] = f
    for k in ("medical_history", "medications", "allergies"):
        out[k] = [_vf(x) for x in (raw.get(k) or []) if x]
    out["timeline"] = [
        {**t, "evidence": _ev(t.get("evidence"))} for t in (raw.get("timeline") or []) if isinstance(t, dict) and t.get("event")
    ]
    for t in out["timeline"]:
        t.setdefault("when", "unspecified")
        t["when"] = t["when"] or "unspecified"
    out["urgency_signals"] = [
        ({"signal": u} if isinstance(u, str) else {**u, "evidence": _ev(u.get("evidence"))})
        for u in (raw.get("urgency_signals") or [])
        if u
    ]
    out["urgency_signals"] = [u for u in out["urgency_signals"] if u.get("signal")]
    out["uncertainties"] = [str(u) for u in (raw.get("uncertainties") or []) if u]
    labs = []
    for lab in raw.get("labs") or []:
        if isinstance(lab, dict) and lab.get("name"):
            lab = dict(lab)
            lab["evidence"] = _ev(lab.get("evidence"))
            if isinstance(lab.get("value"), str) and lab["value"].lower() not in ("positive", "negative"):
                lab["value"] = _num(lab["value"].replace(",", ""))
            labs.append(lab)
    out["labs"] = labs
    return out


# ---------------------------------------------------------------- model call
def _generate(p: LLMProvider, user: str) -> dict[str, Any]:
    if getattr(p, "supports_schema", False):
        return p.generate_json(prompts.EXTRACTION_SYSTEM, user, schema=prompts.output_schema())
    return p.generate_json(prompts.EXTRACTION_SYSTEM, user)


def _call_model(p: LLMProvider, sources: list[Source]) -> Extraction:
    raw = _generate(p, prompts.build_user_prompt(sources))
    try:
        ex = Extraction.model_validate(normalize_model_output(raw))
    except ValidationError as e:
        raw = _generate(p, prompts.build_repair_prompt(sources, str(e)))
        ex = Extraction.model_validate(normalize_model_output(raw))
    if not ex.timeline:  # the compact prompt doesn't ask for a timeline; fill it deterministically
        ex.timeline = timeline_from_sources(sources)
    return ex


# ---------------------------------------------------------------- deterministic merge
def _hit_value(h: Hit, src: Source) -> ExtractedValue:
    form = src.kind == "intake_form"
    return ExtractedValue(
        value=h.value,
        confidence=CONF_FORM if form else CONF_REGEX,
        evidence=Evidence(source_id=src.id, quote=h.text, start=h.start, end=h.end, grounded=True, origin="form" if form else "regex"),
    )


def _concern(field: str, v: float) -> float:
    return abs(float(v) - NORMAL[field])


def _merge_vitals(ex: Extraction, sources: list[Source]) -> None:
    hits: list[tuple[Hit, Source]] = [(h, s) for s in sources for h in extract_vitals(s.original_text)]
    for h, s in hits:
        if not h.plausible:
            ex.uncertainties.append(f"Implausible {h.field.replace('_', ' ')} value '{h.text}' in source {s.id} was ignored.")
    hits = [(h, s) for h, s in hits if h.plausible]

    for field in (*NUMERIC_VITALS, "consciousness", "on_oxygen"):
        model_val: ExtractedValue = getattr(ex.vitals, field)
        det = [(h, s) for h, s in hits if h.field == field]
        if not det:
            continue
        if field in NUMERIC_VITALS:
            distinct = []
            for h, s in det:
                if all(abs(h.value - d.value) > TOLERANCE[field] for d, _ in distinct):
                    distinct.append((h, s))
            chosen_h, chosen_s = max(distinct, key=lambda hs: _concern(field, hs[0].value))
            if len(distinct) > 1:
                ex.discrepancies.append(
                    Discrepancy(
                        field=f"vitals.{field}",
                        values=[h.value for h, _ in distinct],
                        detail=f"Sources report different {field.replace('_', ' ')} values; triage used the more concerning "
                        f"value ({chosen_h.value:g}). Please verify.",
                        evidence=[_hit_value(h, s).evidence for h, s in distinct],
                    )
                )
            new = _hit_value(chosen_h, chosen_s)
            mv = model_val.value
            if mv is not None and isinstance(mv, (int, float)) and abs(mv - chosen_h.value) > TOLERANCE[field]:
                ex.discrepancies.append(
                    Discrepancy(
                        field=f"vitals.{field}",
                        values=[mv, chosen_h.value],
                        detail=f"Model read {field.replace('_', ' ')} as {mv}, deterministic parser found {chosen_h.value}. "
                        "Parser value used; please verify.",
                        evidence=[e for e in (model_val.evidence, new.evidence) if e],
                    )
                )
            setattr(ex.vitals, field, new)
        else:
            h, s = sorted(det, key=lambda hs: hs[1].kind != "intake_form")[0]
            if not model_val.present or s.kind == "intake_form":
                setattr(ex.vitals, field, _hit_value(h, s))


_SRC_NAME = {"patient_message": "the patient's message", "report": "report", "voice": "voice note"}


def _merge_demographics(ex: Extraction, sources: list[Source], patient: Patient | None) -> None:
    text_hits = [(h, s) for s in sources if s.kind != "intake_form" for h in extract_demographics(s.original_text)]
    record = {"age_years": patient.age_years if patient else None, "sex": patient.sex if patient else None}

    for field in ("age_years", "sex"):
        rec = record[field]
        stated = [(h, s) for h, s in text_hits if h.field == field and h.plausible]
        model_val: ExtractedValue = getattr(ex, field)
        if rec is not None:
            for h, s in stated:
                if h.value != rec and not (field == "age_years" and abs(h.value - rec) <= 1):
                    ex.discrepancies.append(
                        Discrepancy(
                            field=field,
                            values=[rec, h.value],
                            detail=f"Registration says {rec}, but {_SRC_NAME.get(s.kind, 'source')} {s.id} says {h.value}. "
                                   "Possibly a different patient's document; please verify.",
                            evidence=[_hit_value(h, s).evidence],
                        )
                    )
            if model_val.present and model_val.value != rec and not (
                field == "age_years" and isinstance(model_val.value, (int, float)) and abs(model_val.value - rec) <= 1
            ):
                # only a conflict if the model can point at where the text says so
                if not stated and model_val.evidence and ground_evidence(model_val.evidence, {x.id: x for x in sources}):
                    ex.discrepancies.append(
                        Discrepancy(field=field, values=[rec, model_val.value],
                                    detail=f"Registration says {rec}; model extracted {model_val.value}. Please verify.",
                                    evidence=[e for e in [model_val.evidence] if e])
                    )
            setattr(ex, field, ExtractedValue(value=rec, confidence=CONF_FORM, evidence=Evidence(origin="form", grounded=True)))
        elif not model_val.present and stated:
            h, s = stated[0]
            setattr(ex, field, _hit_value(h, s))

    preg = [(h, s) for h, s in text_hits if h.field == "pregnancy_status"]
    if preg and not ex.pregnancy_status.present:
        h, s = preg[0]
        ex.pregnancy_status = _hit_value(h, s)


def _merge_symptoms(ex: Extraction, sources: list[Source]) -> None:
    for sym in ex.symptoms:
        if sym.evidence is not None and sym.evidence.origin == "llm":
            continue  # already mapped and checked against its quote in _reconcile_symptom_ids
        sym.canonical_id = sym.canonical_id or canonicalize(sym.name) or (
            canonicalize(sym.evidence.quote) if sym.evidence and sym.evidence.quote else None
        )
    model_ids = {(s.canonical_id, s.negated) for s in ex.symptoms if s.canonical_id}
    scans = []
    for src in sources:
        if src.kind == "intake_form":
            continue
        scans += [(src, m, False) for m in scan(src.original_text)]
        if src.translated_text:  # English safety net for any language the lexicon doesn't cover
            scans += [(src, m, True) for m in scan(src.translated_text)]
    for src, m, in_tr in scans:
        if m.negated:
            continue
        if (m.canonical_id, False) in model_ids:
            continue
        if (m.canonical_id, True) in model_ids:
            ex.discrepancies.append(
                Discrepancy(
                    field=f"symptom.{m.canonical_id}",
                    values=["absent (model)", "present (text scan)"],
                    detail=f"Model marked '{m.label}' as denied, but the text scan found it stated. Please verify.",
                    evidence=[Evidence(source_id=src.id, quote=m.text, start=m.start, end=m.end, grounded=True,
                                       origin="lexicon", in_translation=in_tr)],
                )
            )
        ex.symptoms.append(
            Symptom(
                name=m.label, canonical_id=m.canonical_id,
                confidence=round(CONF_LEXICON * ((src.translation_confidence or 0.6) if in_tr else 1.0), 3),
                evidence=Evidence(source_id=src.id, quote=m.text, start=m.start, end=m.end, grounded=True,
                                  origin="lexicon", in_translation=in_tr),
            )
        )
        model_ids.add((m.canonical_id, False))


LAB_NAME_MAP = {
    "hemoglobin": ["haemoglobin", "hemoglobin", "hb", "hgb"],
    "platelets": ["platelet", "platelets", "plt"],
    "wbc": ["wbc", "tlc", "white blood", "leucocyte", "leukocyte"],
    "glucose": ["glucose", "sugar", "rbs", "fbs", "ppbs"],
    "creatinine": ["creatinine"],
    "potassium": ["potassium"],
    "sodium": ["sodium"],
    "hba1c": ["hba1c", "glycated", "glycosylated", "a1c"],
    "troponin": ["troponin", "trop"],
    "dengue_ns1": ["ns1"],
    "dengue_igm": ["igm"],
}
LAB_NORMAL = {"hemoglobin": 14, "platelets": 250_000, "wbc": 7_500, "glucose": 100, "creatinine": 0.9,
              "potassium": 4.2, "sodium": 140, "hba1c": 5.5}


def canonical_lab(name: str) -> str | None:
    low = (name or "").lower()
    if "hba1c" in low or "glycated" in low or "glycosylated" in low:
        return "hba1c"
    for cid, keys in LAB_NAME_MAP.items():
        if any(k in low for k in keys):
            return cid
    return None


def _lab_deviation(cid: str, v: Any) -> float:
    if isinstance(v, str):
        return 1.0 if v == "positive" else 0.0
    n = LAB_NORMAL.get(cid)
    return abs(float(v) - n) / n if n else 0.0


def _merge_labs(ex: Extraction, sources: list[Source]) -> None:
    for lab in ex.labs:
        lab.canonical_id = lab.canonical_id or canonical_lab(lab.name)
    hits = [(h, s) for s in sources if s.kind != "intake_form" for h in extract_labs(s.original_text)]
    for h, s in hits:
        if not h.plausible:
            ex.uncertainties.append(f"Implausible {LAB_LABELS[h.lab]} value '{h.text}' in source {s.id} was ignored.")
    hits = [(h, s) for h, s in hits if h.plausible]
    for cid in dict.fromkeys(h.lab for h, _ in hits):
        det = [(h, s) for h, s in hits if h.lab == cid]
        distinct = []
        for h, s in det:
            if all(not _same_lab(h.value, d.value) for d, _ in distinct):
                distinct.append((h, s))
        h, s = max(distinct, key=lambda hs: _lab_deviation(cid, hs[0].value))
        ev = Evidence(source_id=s.id, quote=h.text, start=h.start, end=h.end, grounded=True, origin="regex")
        if len(distinct) > 1:
            ex.discrepancies.append(Discrepancy(
                field=f"labs.{cid}", values=[d.value for d, _ in distinct],
                detail=f"Different {LAB_LABELS[cid]} values across reports; triage used the most abnormal ({h.value:g}). "
                       "Check report dates." if not isinstance(h.value, str) else f"Conflicting {LAB_LABELS[cid]} results.",
                evidence=[Evidence(source_id=ss.id, quote=dh.text, start=dh.start, end=dh.end, grounded=True, origin="regex")
                          for dh, ss in distinct]))
        model_lab = next((lab for lab in ex.labs if lab.canonical_id == cid), None)
        det_lab = LabResult(name=LAB_LABELS[cid], canonical_id=cid, value=h.value, unit=h.unit,
                            confidence=h.confidence, evidence=ev)
        if h.note:
            ex.uncertainties.append(f"{LAB_LABELS[cid]}: {h.note} ('{h.text}').")
        if model_lab is None:
            ex.labs.append(det_lab)
            continue
        if model_lab.value is not None and not _same_lab(model_lab.value, h.value):
            ex.discrepancies.append(Discrepancy(
                field=f"labs.{cid}", values=[model_lab.value, h.value],
                detail=f"Model read {LAB_LABELS[cid]} as {model_lab.value}, parser found {h.value}. Parser value used; please verify.",
                evidence=[e for e in (model_lab.evidence, ev) if e]))
        # keep the model's reference range / flag, but take the parser's normalised value
        det_lab.reference_range = model_lab.reference_range
        det_lab.abnormal_flag = model_lab.abnormal_flag
        ex.labs[ex.labs.index(model_lab)] = det_lab


def _same_lab(a: Any, b: Any) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a).lower() == str(b).lower()
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= 0.05 * max(abs(a), abs(b), 1e-9)


def _collect_source_flags(ex: Extraction, sources: list[Source]) -> None:
    for s in sources:
        for f in (s.meta or {}).get("quality_flags", []):
            ex.source_flags.append(SourceFlag(**f))


_SIGNAL_LABEL = re.compile(r"\s*\(.*?\)\s*")
_WORD = re.compile(r"[a-z]{4,}")


def _stems(text: str) -> set[str]:
    return {w[:5] for w in _WORD.findall((text or "").lower())}


def _quote_supports(cid: str, quote: str) -> bool:
    """Does the quoted text actually talk about this symptom? Exact lexicon hit, or a shared word stem
    with the symptom's label / synonyms ("blacked" ~ "blackout")."""
    if not quote:
        return False
    if any(m.canonical_id == cid and not m.negated for m in scan(quote)) or canonicalize(quote) == cid:
        return True
    entry = load_lexicon().get(cid, {})
    vocab = _stems(entry.get("label", "")) | {st for syn in entry.get("synonyms", []) for st in _stems(str(syn))}
    return bool(_stems(quote) & vocab)


def _gate_urgency_signals(ex: Extraction) -> None:
    """Model-written urgency signals are checked before they can influence triage.
    - quote not found in the sources            -> uncertainty only
    - names a symptom that is already detected  -> dropped (adds nothing)
    - names a symptom the quote really supports -> promoted to a symptom, so the normal rules apply
    - names a symptom the quote doesn't support -> uncertainty only (small models echo the symptom list)
    - free-text danger ("cannot walk")          -> kept; may lift a routine case to P3 for review"""
    present = {s.canonical_id for s in ex.symptoms if s.canonical_id and not s.negated}
    kept = []
    for u in ex.urgency_signals:
        if u.evidence is None or not u.evidence.grounded:
            ex.uncertainties.append(f"Model suggested '{u.signal}' but could not point to it in the text; not used for triage.")
            continue
        text = _SIGNAL_LABEL.sub(" ", u.signal).replace("_", " ").strip()
        key = text.lower().replace(" ", "_")
        cid = key if key in load_lexicon() else canonicalize(text)
        if cid is None:
            if _stems(text) & _stems(u.evidence.quote or ""):
                kept.append(u)
            else:
                ex.uncertainties.append(f"Model suggested '{u.signal}' but the quoted text doesn't say it; not used for triage.")
        elif cid in present:
            continue
        elif _quote_supports(cid, u.evidence.quote or ""):
            ex.symptoms.append(Symptom(name=label_for(cid), canonical_id=cid, confidence=0.6, evidence=u.evidence))
            present.add(cid)
        else:
            ex.uncertainties.append(f"Model suggested '{label_for(cid)}' but the quoted text doesn't describe it; not used for triage.")
    ex.urgency_signals = kept


def _reconcile_symptom_ids(ex: Extraction) -> None:
    """The model's symptom id must be backed by the words it quotes.

    Measured on the development runs, ids whose quote doesn't support them were mostly wrong
    ("seizure" quoting "Severe headache", "sore_throat" quoting "सीने में दर्द").
    - quote supports the id                     -> keep
    - quote clearly names another symptom       -> use that one
    - quote names nothing we know               -> drop the id; keep the complaint as free text
    Negation is checked the same way: "denies chest pain ... came for follow-up" does not deny the follow-up."""
    for sym in ex.symptoms:
        if not sym.evidence or sym.evidence.origin != "llm":
            continue
        quote = sym.evidence.quote or ""
        if not sym.canonical_id:
            sym.canonical_id = (canonicalize(sym.name) if sym.name else None) or (canonicalize(quote) if quote else None)
            if not sym.canonical_id:
                continue  # free-text complaint the lexicon doesn't know
        if not _quote_supports(sym.canonical_id, quote):
            by_quote = canonicalize(quote) if quote else None
            if by_quote:
                sym.canonical_id = by_quote
                sym.name = label_for(by_quote)
            else:
                ex.uncertainties.append(
                    f"Model labelled '{quote[:60]}' as '{label_for(sym.canonical_id)}', which the text doesn't say; kept as free text.")
                sym.canonical_id = None
                continue
        if sym.negated:
            hits = [m for m in scan(quote) if m.canonical_id == sym.canonical_id]
            if hits and not any(m.negated for m in hits):
                sym.negated = False


_JUNK_UNCERTAINTY = {"unknown", "none", "n/a", "possible embedded instruction"}


def _clean_uncertainties(ex: Extraction) -> None:
    """Small models sometimes dump symptom-list entries ("snake bite", "head_injury") into uncertainties."""
    lex = load_lexicon()
    labels = {e["label"].lower() for e in lex.values()}
    out = []
    for u in ex.uncertainties:
        low = u.strip().lower()
        key = low.replace(" ", "_")
        if (key in lex or low in labels or low in _JUNK_UNCERTAINTY or low.startswith("cannot_")
                or (len(low.split()) <= 3 and canonicalize(low) and not low.startswith("model "))):
            continue
        out.append(u)
    ex.uncertainties = list(dict.fromkeys(out))


# ---------------------------------------------------------------- public entry point
def extract(sources: list[Source], patient: Patient | None = None) -> tuple[Extraction, int]:
    started = time.perf_counter()
    settings = get_settings()
    errors: list[str] = []
    ex: Extraction | None = None
    chain = [] if settings.llm_provider.lower() == "rules" else provider_chain()

    for p in chain:
        if not p.is_available():
            errors.append(f"{p.model_id} unavailable")
            continue
        try:
            ex = _call_model(p, sources)
            ex.provider = p.model_id
            break
        except (LLMError, ValidationError) as e:
            errors.append(f"{p.model_id}: {str(e)[:200]}")

    if ex is None:
        ex = rule_extract(sources)
        ex.fallback_used = bool(chain)
    ex.provider_errors = errors

    _merge_vitals(ex, sources)
    _merge_labs(ex, sources)
    _merge_demographics(ex, sources, patient)
    _reconcile_symptom_ids(ex)
    _merge_symptoms(ex, sources)
    _collect_source_flags(ex, sources)
    ground_extraction(ex, sources)
    _gate_urgency_signals(ex)
    _clean_uncertainties(ex)
    attach_locators(ex, sources)
    return ex, int((time.perf_counter() - started) * 1000)
