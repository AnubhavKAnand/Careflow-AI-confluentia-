"""Deterministic parser for common lab values on Indian lab reports.

Handles the unit styles seen on Indian reports, e.g. platelets as "18,000 /cumm",
"0.18 lakh", "18 x10^3/uL"; glucose in mg/dL; haemoglobin as g/dL or gm%.
Ambiguous units lower the confidence instead of being guessed silently.
"""
import re
from dataclasses import dataclass
from typing import Any, Optional

_GAP = r"[^\d\n]{0,25}?"  # label ... value (skips ':', '(', 'count', units on the left, etc.)
_NUM = r"(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)"

LAB_LABELS = {
    "hemoglobin": "Haemoglobin",
    "platelets": "Platelet count",
    "wbc": "Total WBC count",
    "glucose": "Blood glucose",
    "creatinine": "Serum creatinine",
    "potassium": "Serum potassium",
    "sodium": "Serum sodium",
    "hba1c": "HbA1c",
    "troponin": "Troponin",
    "dengue_ns1": "Dengue NS1 antigen",
    "dengue_igm": "Dengue IgM",
}

PATTERNS: dict[str, re.Pattern] = {
    "hemoglobin": re.compile(rf"(?<!glycated )(?<!glycosylated )\b(?:h(?:a)?emoglobin|hb|hgb)\b{_GAP}{_NUM}\s*(g/?dl|gm/?dl|gm\s*%|g\s*%)?", re.I),
    "platelets": re.compile(
        rf"\b(?:platelets?|plt)(?:\s*count)?\b{_GAP}{_NUM}\s*(lakhs?|lacs?|x\s*10\^?\s*3|×\s*10\^?\s*3|10\^3|thou|k\b|/\s*(?:cumm|cu\.?\s*mm|mm3|µl|ul|mcl))?",
        re.I),
    "wbc": re.compile(
        rf"\b(?:total\s+)?(?:wbc|tlc|w\.b\.c\.?|total\s+leu[ck]ocyte\s+count|white\s+blood\s+cells?)(?:\s*count)?\b{_GAP}{_NUM}\s*"
        r"(x\s*10\^?\s*3|×\s*10\^?\s*3|10\^3|thou|k\b|/\s*(?:cumm|cu\.?\s*mm|mm3|µl|ul|mcl))?", re.I),
    "glucose": re.compile(
        rf"\b(?:(?:(?:random|fasting|post\s*prandial|pp)\s+)?(?:blood\s+)?(?:sugar|glucose)(?:\s*\((?:random|fasting|rbs|fbs|pp)\))?|(?:rbs|fbs|ppbs|grbs|cbg))\b{_GAP}{_NUM}\s*(mg/?dl|mmol/?l)?",
        re.I),
    "creatinine": re.compile(rf"\b(?:s(?:erum)?\.?\s*)?creatinine\b{_GAP}{_NUM}\s*(mg/?dl|µmol/?l|umol/?l)?", re.I),
    "potassium": re.compile(rf"\b(?:s(?:erum)?\.?\s*)?potassium\b(?:\s*\(k\+?\))?{_GAP}{_NUM}\s*(meq/?l|mmol/?l)?", re.I),
    "sodium": re.compile(rf"\b(?:s(?:erum)?\.?\s*)?sodium\b(?:\s*\(na\+?\))?{_GAP}{_NUM}\s*(meq/?l|mmol/?l)?", re.I),
    "hba1c": re.compile(rf"\b(?:(?:glycated|glycosylated)\s+ha?emoglobin(?:\s*\(\s*hba1c\s*\))?|hba1c)(?![\w]){_GAP}{_NUM}\s*(%)?", re.I),
}
DENGUE = re.compile(r"\b(?:dengue\s+)?(ns1(?:\s+antigen)?|igm)\b[^\n]{0,25}?\b(positive|negative|non[-\s]?reactive|reactive)\b", re.I)
TROPONIN = re.compile(r"\btrop(?:onin)?(?:\s*-?\s*[it])?\b[^\n]{0,30}?\b(positive|negative|non[-\s]?reactive|reactive|detected|not\s+detected)\b", re.I)

# Physiologically possible ranges after normalisation; outside -> ignored and flagged
PLAUSIBLE = {
    "hemoglobin": (1, 25), "platelets": (1_000, 2_000_000), "wbc": (100, 200_000), "glucose": (10, 1500),
    "creatinine": (0.1, 30), "potassium": (1, 10), "sodium": (90, 200), "hba1c": (3, 20),
}
UNITS = {"hemoglobin": "g/dL", "platelets": "/µL", "wbc": "/µL", "glucose": "mg/dL", "creatinine": "mg/dL",
         "potassium": "mmol/L", "sodium": "mmol/L", "hba1c": "%"}


@dataclass
class LabHit:
    lab: str
    value: Any
    unit: Optional[str]
    start: int
    end: int
    text: str
    confidence: float
    plausible: bool = True
    note: Optional[str] = None


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def _normalise(lab: str, value: float, unit: str) -> tuple[float, float, Optional[str]]:
    """Return (value in standard unit, confidence, note)."""
    u = (unit or "").lower().replace(" ", "")
    if lab in ("platelets", "wbc"):
        if "lakh" in u or "lac" in u:
            return value * 100_000, 0.9, None
        if any(x in u for x in ("10^3", "103", "thou")) or u == "k":
            return value * 1_000, 0.9, None
        if u:  # /cumm, /µL: absolute count
            return value, 0.9, None
        if lab == "platelets" and value < 10:  # "1.5" with no unit: lakh is the common Indian style
            return value * 100_000, 0.55, "unit missing; assumed lakh"
        if value < 1_000:
            return value * 1_000, 0.55, "unit missing; assumed x10^3/µL"
        return value, 0.75, "unit missing"
    if lab == "glucose" and "mmol" in u:
        return round(value * 18, 0), 0.9, None
    if lab == "creatinine" and "mol" in u:
        return round(value / 88.4, 2), 0.9, None
    return value, 0.9 if u else 0.8, None


def extract_labs(text: str) -> list[LabHit]:
    hits: list[LabHit] = []
    if not text:
        return hits
    for lab, pat in PATTERNS.items():
        for m in pat.finditer(text):
            groups = [g for g in m.groups()]
            num_str = next((g for g in groups if g and re.fullmatch(_NUM, g)), None)
            if num_str is None:
                continue
            unit = groups[-1] if groups[-1] and groups[-1] != num_str else ""
            value, conf, note = _normalise(lab, _to_float(num_str), unit)
            lo, hi = PLAUSIBLE[lab]
            hits.append(LabHit(lab, value, UNITS[lab], m.start(), m.end(), m.group(0), conf, lo <= value <= hi, note))
            break  # first occurrence per lab on a source
    m = TROPONIN.search(text)
    if m:
        word = m.group(1).lower()
        val = "negative" if word.startswith(("neg", "non", "not")) else "positive"
        hits.append(LabHit("troponin", val, None, m.start(), m.end(), m.group(0), 0.85))
    for m in DENGUE.finditer(text):
        lab = "dengue_ns1" if m.group(1).lower().startswith("ns1") else "dengue_igm"
        word = m.group(2).lower()
        val = "negative" if word.startswith(("neg", "non")) else "positive"
        if not any(h.lab == lab for h in hits):
            hits.append(LabHit(lab, val, None, m.start(), m.end(), m.group(0), 0.85))
    return hits
