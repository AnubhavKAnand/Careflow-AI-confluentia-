"""Deterministic vitals and demographics extraction.

Runs on every source regardless of which model is used. Its results are merged with the
model's output, and any disagreement is recorded as a discrepancy instead of being
silently resolved.
"""
import re
from dataclasses import dataclass
from typing import Any, Optional

_NUM = r"(\d{2,3}(?:\.\d)?)"
_SEP = r"\s*(?:[:=\-]|is|was|of|at|hai|h)?\s*"

PATTERNS: dict[str, re.Pattern] = {
    "spo2": re.compile(rf"\b(?:spo2|sp02|spo₂|o2\s*sat(?:uration)?|oxygen(?:\s+(?:saturation|level|sat))?|saturation|sats?)\b{_SEP}{_NUM}\s*%?", re.I),
    "pulse": re.compile(rf"\b(?:pulse(?:\s+rate)?|heart\s*rate|hr|pr|dhadkan)\b{_SEP}{_NUM}\s*(?:bpm|/\s*min|per\s+min(?:ute)?)?", re.I),
    "resp_rate": re.compile(rf"\b(?:resp(?:iratory)?\s*rate|rr|respirations?|breathing\s+rate)\b{_SEP}(\d{{1,2}})\s*(?:/\s*min|per\s+min(?:ute)?|breaths)?", re.I),
    "bp": re.compile(rf"\b(?:bp|blood\s+pressure)\b{_SEP}(\d{{2,3}})\s*/\s*(\d{{2,3}})", re.I),
    "temperature": re.compile(rf"\b(?:temp(?:erature)?|fever\s+of|bukhar|bukhaar|taap)\b{_SEP}{_NUM}\s*°?\s*([cf])?\b", re.I),
    # looser forms: "fever 103", "103 fever", "102.5 degree bukhar" -- only kept when plausible
    "temperature_loose": re.compile(r"\b(?:fever|bukhar|bukhaar)\s+(\d{2,3}(?:\.\d)?)\b|\b(\d{2,3}(?:\.\d)?)\s*(?:°|deg(?:ree)?s?)?\s*([cf])?\s*(?:fever|bukhar|bukhaar)\b", re.I),
}

RANGES = {
    "spo2": (50, 100),
    "pulse": (20, 250),
    "resp_rate": (4, 60),
    "systolic_bp": (50, 260),
    "diastolic_bp": (20, 160),
    "temperature_c": (30, 45),
}

_UNCONSCIOUS = re.compile(r"\b(unconscious|unresponsive|not responding|behosh|responds? only to pain)\b|बेहोश", re.I)
_VOICE = re.compile(r"\b(responds? (?:only )?to voice)\b", re.I)
_CONFUSED = re.compile(r"\b(confused|disoriented|new confusion|not making sense)\b", re.I)
_ALERT = re.compile(r"\b(alert|fully conscious|conscious and oriented)\b", re.I)
_ACVPU_FIELD = re.compile(r"\b(?:consciousness|acvpu|avpu)\s*[:=]\s*([ACVPU])\b", re.I)
_ON_O2 = re.compile(r"\b(?:supplemental\s+oxygen|on\s+oxygen)\s*[:=]\s*yes\b|\b(on oxygen|on o2|oxygen support|o2 support|supplemental oxygen|nasal cannula)\b", re.I)

_AGE = re.compile(
    r"\b(\d{1,3})\s*(?:-|\s)?\s*(?:years?|yrs?|yo|y/o|saal|sal|varsh)(?:\s*old)?\b|\bage[d]?\s*[:=]?\s*(\d{1,3})\b|(\d{1,3})\s*वर्ष",
    re.I,
)
_AGE_MONTHS = re.compile(r"\b(\d{1,2})\s*(?:-|\s)?\s*(?:months?|mahine|mahina)\s*(?:old|ka|ki|ke)\b", re.I)
_FEMALE = re.compile(r"\b(female|woman|lady|girl|she|her|wife|mother|daughter|mahila|aurat|ladki|beti|maa|patni|biwi)\b|महिला", re.I)
_MALE = re.compile(r"\b(male|man|gentleman|boy|he|his|husband|father|son|aadmi|purush|ladka|beta|pita|pati)\b|पुरुष", re.I)
_PREGNANT = re.compile(r"\b(pregnant|pregnancy|garbhvati|garbhwati|weeks? pregnant|months? pregnant|expecting a baby)\b|गर्भवती", re.I)
_NOT_PREGNANT = re.compile(r"\b(not pregnant|no pregnancy)\b", re.I)


@dataclass
class Hit:
    field: str
    value: Any
    start: int
    end: int
    text: str
    plausible: bool = True


def _in_range(field: str, value: float) -> bool:
    lo, hi = RANGES.get(field, (float("-inf"), float("inf")))
    return lo <= value <= hi


def extract_vitals(text: str) -> list[Hit]:
    hits: list[Hit] = []
    if not text:
        return hits
    for key in ("spo2", "pulse", "resp_rate"):
        for m in PATTERNS[key].finditer(text):
            v = float(m.group(1))
            hits.append(Hit(key, v, m.start(), m.end(), m.group(0), _in_range(key, v)))
    for m in PATTERNS["bp"].finditer(text):
        s, d = float(m.group(1)), float(m.group(2))
        hits.append(Hit("systolic_bp", s, m.start(), m.end(), m.group(0), _in_range("systolic_bp", s)))
        hits.append(Hit("diastolic_bp", d, m.start(), m.end(), m.group(0), _in_range("diastolic_bp", d)))
    for m in PATTERNS["temperature"].finditer(text):
        v = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit == "f" or (not unit and v > 45):
            v = round((v - 32) * 5 / 9, 1)
        hits.append(Hit("temperature_c", v, m.start(), m.end(), m.group(0), _in_range("temperature_c", v)))
    if not any(h.field == "temperature_c" for h in hits):
        for m in PATTERNS["temperature_loose"].finditer(text):
            raw = m.group(1) or m.group(2)
            v = float(raw)
            unit = (m.group(3) or "").lower()
            if unit == "f" or (not unit and v > 45):
                v = round((v - 32) * 5 / 9, 1)
            if 35 <= v <= 43:  # silently skip implausible loose matches ("fever 10 days")
                hits.append(Hit("temperature_c", v, m.start(), m.end(), m.group(0), True))
                break

    m = _ACVPU_FIELD.search(text)
    if m:
        hits.append(Hit("consciousness", m.group(1).upper(), m.start(), m.end(), m.group(0)))
    for pat, letter in ((_UNCONSCIOUS, "U"), (_VOICE, "V"), (_CONFUSED, "C"), (_ALERT, "A")):
        m = pat.search(text) if not any(h.field == "consciousness" for h in hits) else None
        if m:
            hits.append(Hit("consciousness", letter, m.start(), m.end(), m.group(0)))
            break
    m = _ON_O2.search(text)
    if m:
        hits.append(Hit("on_oxygen", True, m.start(), m.end(), m.group(0)))
    return hits


def extract_demographics(text: str) -> list[Hit]:
    hits: list[Hit] = []
    if not text:
        return hits
    m = _AGE_MONTHS.search(text)
    if m:
        hits.append(Hit("age_years", 0, m.start(), m.end(), m.group(0)))
    else:
        m = _AGE.search(text)
        if m:
            v = int(next(g for g in m.groups() if g))
            hits.append(Hit("age_years", v, m.start(), m.end(), m.group(0), 0 <= v <= 120))
    f, ma = _FEMALE.search(text), _MALE.search(text)
    if f and not ma:
        hits.append(Hit("sex", "female", f.start(), f.end(), f.group(0)))
    elif ma and not f:
        hits.append(Hit("sex", "male", ma.start(), ma.end(), ma.group(0)))
    m = _NOT_PREGNANT.search(text)
    if m:
        hits.append(Hit("pregnancy_status", "not_pregnant", m.start(), m.end(), m.group(0)))
    else:
        m = _PREGNANT.search(text)
        if m:
            hits.append(Hit("pregnancy_status", "pregnant", m.start(), m.end(), m.group(0)))
    return hits


def first(hits: list[Hit], field: str) -> Optional[Hit]:
    return next((h for h in hits if h.field == field and h.plausible), None)
