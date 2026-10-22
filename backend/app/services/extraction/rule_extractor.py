"""Deterministic extractor: used offline (LLM_PROVIDER=rules), in tests, and as the last-resort
fallback when every model is unavailable. Lower recall than a model, but fully explainable."""
import re

from app.models.case import Source
from app.schemas.extraction import Evidence, ExtractedValue, Extraction, Symptom, TimelineEvent
from app.services.triage.text_match import scan

_DURATION = re.compile(
    r"\b(?:(?:since|for|from)\s+)?(\d+|a|an|one|two|three|four|five|ek|do|teen|char|paanch)\s*"
    r"(hours?|hrs?|days?|weeks?|months?|din|ghante|ghanta|hafte|hafta|mahine)\s*(?:ago|se|pehle|back)?\b"
    r"|\b(?:since\s+)?(yesterday|last\s+night|this\s+morning|today|kal\s+se|kal\s+raat\s+se|aaj\s+subah\s+se|subah\s+se|raat\s+se)\b",
    re.I,
)
_WORSE = re.compile(r"\b(getting worse|worsening|worse|increasing|badh raha|badh rahi|zyada ho raha|tez ho raha)\b", re.I)
_BETTER = re.compile(r"\b(getting better|improving|better|kam ho raha|theek ho raha)\b", re.I)
_SEVERE = re.compile(r"\b(severe|very bad|unbearable|bahut tez|bahut zyada|bahut)\b", re.I)
_SENTENCE = re.compile(r"[^.!?।\n]+[.!?।]?")

CONF_LEXICON = 0.7


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    for m in _SENTENCE.finditer(text):
        if m.start() <= pos < m.end():
            return m.start(), m.end()
    return 0, len(text)


def timeline_from_sources(sources: list[Source]) -> list[TimelineEvent]:
    """Durations / onsets ("since 2 days", "kal raat se") with the sentence they belong to."""
    out: list[TimelineEvent] = []
    for src in sources:
        if src.kind == "intake_form":
            continue
        text = src.original_text
        for d in _DURATION.finditer(text):
            s0, s1 = _sentence_bounds(text, d.start())
            out.append(
                TimelineEvent(
                    when=d.group(0).strip(),
                    event=text[s0:s1].strip()[:160],
                    evidence=Evidence(source_id=src.id, quote=d.group(0), start=d.start(), end=d.end(), grounded=True, origin="regex"),
                )
            )
    return out


def rule_extract(sources: list[Source]) -> Extraction:
    ex = Extraction(provider="rules")
    seen: set[str] = set()
    for src in sources:
        if src.kind == "intake_form":
            continue  # vitals from the form are merged separately
        for in_tr, text in ((False, src.original_text), (True, src.translated_text or "")):
            _scan_into(ex, src, text, in_tr, seen)
    ex.timeline = timeline_from_sources(sources)
    present = [s for s in ex.symptoms if not s.negated]
    if present:
        first = present[0]
        ex.chief_complaint = ExtractedValue(value=first.name, confidence=0.5, evidence=first.evidence)
    ex.uncertainties.append("Extracted by deterministic rules (no language model); recall may be limited.")
    return ex


def _scan_into(ex: Extraction, src: Source, text: str, in_tr: bool, seen: set[str]) -> None:
    for m in scan(text):
        key = f"{m.canonical_id}:{m.negated}"
        if key in seen:
            continue
        seen.add(key)
        s0, s1 = _sentence_bounds(text, m.start)
        sentence = text[s0:s1]
        dur = _DURATION.search(sentence)
        ex.symptoms.append(
            Symptom(
                name=m.label,
                canonical_id=m.canonical_id,
                negated=m.negated,
                duration=dur.group(0).strip() if dur else None,
                severity="severe" if _SEVERE.search(sentence) else None,
                progression="worsening" if _WORSE.search(sentence) else ("improving" if _BETTER.search(sentence) else None),
                confidence=round(CONF_LEXICON * ((src.translation_confidence or 0.6) if in_tr else 1.0), 3),
                evidence=Evidence(source_id=src.id, quote=m.text, start=m.start, end=m.end, grounded=True,
                                  origin="lexicon", in_translation=in_tr),
            )
        )
