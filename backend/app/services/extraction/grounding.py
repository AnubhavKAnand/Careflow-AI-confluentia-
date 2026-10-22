"""Grounding: verify every model quote actually exists in the source and record its exact span.

A fact whose quote cannot be found is kept but marked ungrounded and its confidence is
halved, so a hallucinated "evidence" never looks as trustworthy as a real one.
"""
import re
from difflib import SequenceMatcher
from typing import Any, Iterable, Iterator

from pydantic import BaseModel

from app.models.case import Source
from app.schemas.extraction import Evidence, ExtractedValue, Extraction

FUZZY_THRESHOLD = 0.8
UNGROUNDED_PENALTY = 0.5


def _locate(quote: str, text: str) -> tuple[int, int, float] | None:
    if not quote or not text:
        return None
    i = text.lower().find(quote.lower())
    if i != -1:
        return i, i + len(quote), 1.0
    words = quote.split()
    if words:
        m = re.search(r"\s+".join(re.escape(w) for w in words), text, re.IGNORECASE)
        if m:
            return m.start(), m.end(), 1.0
    sm = SequenceMatcher(None, text.lower(), quote.lower(), autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    if not blocks:
        return None
    matched = sum(b.size for b in blocks)
    ratio = matched / max(1, len(quote))
    if ratio >= FUZZY_THRESHOLD:
        start = blocks[0].a
        end = blocks[-1].a + blocks[-1].size
        if end - start <= len(quote) * 1.5:
            return start, end, ratio
    return None


def ground_evidence(ev: Evidence | None, sources: dict[int, Source]) -> bool:
    """Fill start/end on the evidence. Returns True if grounded."""
    if ev is None or not ev.quote:
        return False
    candidates: Iterable[Source] = (
        [sources[ev.source_id]] + [s for sid, s in sources.items() if sid != ev.source_id]
        if ev.source_id in sources
        else list(sources.values())
    )
    candidates = list(candidates)
    # Original text first (preferred: it is what the patient actually said/wrote), then translations
    for in_tr in ((True, False) if ev.in_translation else (False, True)):
        for src in candidates:
            text = src.translated_text if in_tr else src.original_text
            loc = _locate(ev.quote, text or "")
            if loc:
                ev.source_id, ev.start, ev.end = src.id, loc[0], loc[1]
                ev.in_translation = in_tr
                ev.grounded = True
                return True
    ev.grounded = False
    return False


def _ground_value(v: ExtractedValue, sources: dict[int, Source]) -> None:
    if not v.present:
        return
    if v.evidence and v.evidence.origin in ("regex", "lexicon", "form") and v.evidence.grounded:
        return
    if not ground_evidence(v.evidence, sources):
        v.confidence = round(v.confidence * UNGROUNDED_PENALTY, 3)


def ground_extraction(ex: Extraction, sources: list[Source]) -> int:
    """Ground every fact in place. Returns the number of ungrounded facts."""
    by_id = {s.id: s for s in sources}
    values: list[ExtractedValue] = [
        ex.chief_complaint, ex.age_years, ex.sex, ex.pregnancy_status,
        *ex.medical_history, *ex.medications, *ex.allergies,
        *(getattr(ex.vitals, f) for f in type(ex.vitals).model_fields),
    ]
    for v in values:
        _ground_value(v, by_id)
    for lab in ex.labs:
        if lab.evidence and lab.evidence.origin == "regex" and lab.evidence.grounded:
            continue
        if not ground_evidence(lab.evidence, by_id):
            lab.confidence = round(lab.confidence * UNGROUNDED_PENALTY, 3)
    for sym in ex.symptoms:
        if sym.evidence and sym.evidence.origin == "lexicon":
            continue
        if not ground_evidence(sym.evidence, by_id):
            sym.confidence = round(sym.confidence * UNGROUNDED_PENALTY, 3)
    for item in [*ex.timeline, *ex.urgency_signals]:
        ground_evidence(item.evidence, by_id)

    ungrounded_values = sum(1 for v in values if v.present and not (v.evidence and v.evidence.grounded))
    ungrounded_symptoms = sum(1 for s in ex.symptoms if not (s.evidence and s.evidence.grounded))
    ungrounded_labs = sum(1 for lab in ex.labs if not (lab.evidence and lab.evidence.grounded))
    return ungrounded_values + ungrounded_symptoms + ungrounded_labs


# ------------------------------------------------------------------ locators + OCR/ASR confidence
LOW_SOURCE_CONFIDENCE = 0.75


def _iter_with_evidence(obj: Any) -> Iterator[tuple[Any, Evidence]]:
    """Yield (owner, evidence) for every Evidence anywhere inside a model."""
    if isinstance(obj, Evidence):
        return
    if isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            val = getattr(obj, name)
            if isinstance(val, Evidence):
                yield obj, val
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, Evidence):
                        yield obj, item
                    else:
                        yield from _iter_with_evidence(item)
            elif isinstance(val, BaseModel):
                yield from _iter_with_evidence(val)


def _units(src: Source) -> list[dict]:
    meta = src.meta or {}
    return meta.get("lines") or meta.get("segments") or []


def attach_locators(ex: Extraction, sources: list[Source]) -> None:
    """Map each evidence span to its report line box / voice-note timestamp, and cap the fact's confidence
    by the OCR/ASR confidence of the text it came from (a fact is never more certain than its reading)."""
    by_id = {s.id: s for s in sources}
    for owner, ev in _iter_with_evidence(ex):
        src = by_id.get(ev.source_id) if ev.source_id is not None else None
        if src is None or ev.start is None or ev.in_translation:
            continue
        units = [u for u in _units(src) if u.get("char_end", 0) > ev.start and u.get("char_start", 0) < (ev.end or ev.start)]
        if not units:
            continue
        conf = round(min(float(u.get("confidence", 1.0)) for u in units), 3)
        ev.source_confidence = conf
        if "page" in units[0]:
            boxes = [u["bbox"] for u in units if u.get("bbox")]
            ev.locator = {"page": units[0]["page"]}
            if boxes:
                ev.locator["bbox"] = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                                      max(b[2] for b in boxes), max(b[3] for b in boxes)]
        elif "start_s" in units[0]:
            ev.locator = {"start_s": units[0]["start_s"], "end_s": units[-1]["end_s"]}
        if conf < LOW_SOURCE_CONFIDENCE and hasattr(owner, "confidence") and isinstance(owner.confidence, float):
            owner.confidence = min(owner.confidence, conf)
