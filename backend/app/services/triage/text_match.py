"""Deterministic, negation-aware multilingual symptom scanner.

This is the safety net that runs independently of the language model: even if the
model misses "seene mein dard aur pasina", this scan finds chest_pain + sweating and
the red-flag rules fire.
"""
import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from app.config import RULES_DIR

# English negation cues that come BEFORE the symptom ("no fever", "denies chest pain")
_PRE_NEG = re.compile(
    r"\b(no|not|denies|denied|deny|without|never|negative for|free of|absence of)\b[\w\s/-]{0,20}$",
    re.IGNORECASE,
)
# Hindi / Hinglish negation comes AFTER the symptom ("bukhar nahi hai", "सीने में दर्द नहीं है").
# Requires the negation word to close the clause, so "bukhar nahi utar raha" (fever not coming down)
# is NOT treated as negated.
_POST_NEG = re.compile(
    r"^\s*(?:to\s+|toh\s+)?(?:bilkul\s+)?(nahi|nahin|nhi|nai|नहीं|नही)\s*(hai|he|h|tha|thi|hua|हैं|है|था|थी)?\s*"
    r"([.,;!?।]|$|\s+(aur|par|lekin|magar|but|and|or|bas)\b)",
    re.IGNORECASE,
)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


@dataclass
class SymptomMatch:
    canonical_id: str
    label: str
    start: int
    end: int
    text: str
    negated: bool


@lru_cache
def load_lexicon() -> dict[str, dict]:
    with open(RULES_DIR / "symptom_lexicon.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _pattern_for(phrase: str) -> re.Pattern:
    words = [re.escape(w) for w in phrase.replace("'", "'").split()]
    body = r"\s+".join(words)
    if _DEVANAGARI.search(phrase):
        return re.compile(body)  # \b is unreliable around Devanagari combining marks
    return re.compile(rf"(?<![\w]){body}(?![\w])", re.IGNORECASE)


@lru_cache
def _compiled() -> list[tuple[str, str, re.Pattern, list[re.Pattern]]]:
    out = []
    for cid, entry in load_lexicon().items():
        excludes = [_pattern_for(x) for x in entry.get("exclude", [])]
        # longest synonyms first so "heavy bleeding" wins over "bleeding" for span display
        for syn in sorted(entry["synonyms"], key=len, reverse=True):
            out.append((cid, entry["label"], _pattern_for(str(syn)), excludes))
    return out


def _is_negated(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 40):start]
    # Only look within the current clause. Splitting on commas too is deliberately conservative:
    # a missed negation causes over-triage (safe); a false negation could hide a red flag (unsafe).
    before = re.split(r"[,.;!?।\n]|\bbut\b|\band\b|\blekin\b|\bpar\b|\baur\b", before, flags=re.IGNORECASE)[-1]
    if _PRE_NEG.search(before):
        return True
    return bool(_POST_NEG.match(text[end:end + 30]))


def scan(text: str) -> list[SymptomMatch]:
    """Return one match per (canonical id, position); overlapping synonyms of the same id are merged."""
    if not text:
        return []
    matches: list[SymptomMatch] = []
    taken: dict[str, list[tuple[int, int]]] = {}
    for cid, label, pat, excludes in _compiled():
        excluded_spans = [(m.start(), m.end()) for ex in excludes for m in ex.finditer(text)]
        for m in pat.finditer(text):
            s, e = m.start(), m.end()
            if any(es <= s and e <= ee for es, ee in excluded_spans):
                continue
            if any(not (e <= ts or s >= te) for ts, te in taken.get(cid, [])):
                continue
            taken.setdefault(cid, []).append((s, e))
            matches.append(SymptomMatch(cid, label, s, e, text[s:e], _is_negated(text, s, e)))
    return sorted(matches, key=lambda x: x.start)


def canonicalize(name: str) -> str | None:
    """Map a free-text symptom name (e.g. from the model) to a canonical id."""
    if not name:
        return None
    hits = [h for h in scan(name) if not h.negated]
    if hits:
        # prefer the longest matched phrase; a multi-word token match beats a one-word scan hit
        best = max(hits, key=lambda h: h.end - h.start)
        if len(name[best.start:best.end].split()) == 1:
            alt = _token_subset(name.lower().strip())
            if alt:
                return alt
        return best.canonical_id
    low = name.lower().strip()
    for cid, entry in load_lexicon().items():
        if low == cid.replace("_", " ") or low == entry["label"].lower():
            return cid
    return _token_subset(low)


_STOP = {"a", "an", "the", "in", "of", "my", "is", "up", "and", "on", "to", "with", "at", "has", "have",
         "was", "were", "be", "been", "feeling", "feels", "feel", "some", "very", "since", "from", "his", "her"}


def _tokens(s: str) -> set[str]:
    import re as _re
    return {t for t in _re.findall(r"[a-z]+", s.lower()) if t not in _STOP}


def _token_subset(low: str) -> str | None:
    """Short model-written names like 'speech became slurred': match a multi-word Latin synonym
    whose content words all appear in the name. Prefers the synonym with the most words."""
    toks = _tokens(low)
    if not toks or len(low.split()) > 6:
        return None
    best: tuple[int, str] | None = None
    for cid, entry in load_lexicon().items():
        for syn in [entry.get("label", "")] + list(entry.get("synonyms", [])):
            st = _tokens(str(syn))
            if len(st) >= 2 and st <= toks and (best is None or len(st) > best[0]):
                best = (len(st), cid)
    return best[1] if best else None


def label_for(cid: str) -> str:
    return load_lexicon().get(cid, {}).get("label", cid)
