"""Turn a case into a named, sparse feature vector for the shadow agent and similar-case memory.

Every feature has a human-readable label, so the agent's suggestion can be explained
("Age 65+, Fever, History: diabetes") and clinicians can see why two cases look alike.
"""
import re
from functools import lru_cache
from typing import Optional

from app.schemas.extraction import Extraction
from app.schemas.triage import PRIORITY_ORDER, TriageOutput
from app.schemas.validation import ValidationReport
from app.services.triage.red_flags import load_rules
from app.services.triage.text_match import load_lexicon

AGE_BANDS = [("age:<5", 0, 4), ("age:5-15", 5, 15), ("age:16-39", 16, 39), ("age:40-64", 40, 64), ("age:65+", 65, 200)]
HISTORY = {
    "hist:diabetes": r"\b(diabet\w*|sugar|insulin|metformin|glimepiride|madhumeh)\b",
    "hist:cardiac": r"\b(heart|cardiac|angina|stent|bypass|mi\b|heart attack|dil ki bimari)",
    "hist:hypertension": r"\b(hypertension|high bp|bp ki dawai|bp ki dawa|bp\b|amlodipine|telmisartan)",
    "hist:respiratory": r"\b(asthma|copd|dama|inhaler|tb\b|tuberculosis)",
    "hist:kidney": r"\b(kidney|ckd|dialysis|renal)",
}
LAB_FEATURES = {
    "lab:platelets_low": ("platelets", lambda v: max(0.0, (150_000 - v) / 150_000)),
    "lab:hb_low": ("hemoglobin", lambda v: max(0.0, (12 - v) / 12)),
    "lab:glucose_low": ("glucose", lambda v: max(0.0, (70 - v) / 70)),
    "lab:glucose_high": ("glucose", lambda v: min(1.5, max(0.0, (v - 200) / 300))),
    "lab:potassium_high": ("potassium", lambda v: max(0.0, (v - 5.1) / 2)),
    "lab:sodium_low": ("sodium", lambda v: max(0.0, (135 - v) / 20)),
    "lab:creatinine_high": ("creatinine", lambda v: min(1.5, max(0.0, (v - 1.3) / 3))),
    "lab:wbc_high": ("wbc", lambda v: min(1.5, max(0.0, (v - 11_000) / 20_000))),
    "lab:wbc_low": ("wbc", lambda v: max(0.0, (4_000 - v) / 4_000)),
}
NON_CLINICAL_PREFIXES = ("bias", "engine:", "q:")  # excluded from similarity


@lru_cache
def feature_names() -> list[str]:
    names = ["bias", *[f"engine:{p}" for p in PRIORITY_ORDER]]
    names += [f"flag:{r['id']}" for r in load_rules()]
    names += [f"sym:{cid}" for cid in load_lexicon()]
    names += ["sym:any_severe", "sym:any_worsening"]
    names += ["v:spo2_low", "v:pulse_high", "v:pulse_low", "v:rr_high", "v:sbp_low", "v:sbp_high", "v:temp_high",
              "v:not_alert", "v:none_measured", "v:news2"]
    names += list(LAB_FEATURES) + ["lab:troponin_pos"]
    names += [b[0] for b in AGE_BANDS] + ["age:unknown", "sex:female", "pregnant"]
    names += list(HISTORY)
    names += ["q:uncertain", "q:low_completeness", "q:conflict", "q:suspicious", "q:unreadable_source"]
    return names


def label(name: str) -> str:
    kind, _, key = name.partition(":")
    if kind == "flag":
        rule = next((r for r in load_rules() if r["id"] == key), None)
        return f"Warning sign: {rule['label']}" if rule else key
    if kind == "sym":
        if key == "any_severe":
            return "A symptom described as severe"
        if key == "any_worsening":
            return "Symptoms getting worse"
        return load_lexicon().get(key, {}).get("label", key)
    fixed = {
        "v:spo2_low": "Low SpO2", "v:pulse_high": "Fast pulse", "v:pulse_low": "Slow pulse", "v:rr_high": "Fast breathing",
        "v:sbp_low": "Low blood pressure", "v:sbp_high": "High blood pressure", "v:temp_high": "High temperature",
        "v:not_alert": "Not fully alert", "v:none_measured": "No vitals measured", "v:news2": "NEWS2 score",
        "lab:troponin_pos": "Positive troponin", "age:unknown": "Age unknown", "sex:female": "Female", "pregnant": "Pregnant",
        "q:uncertain": "Uncertain information", "q:low_completeness": "Incomplete information", "q:conflict": "Conflicting information",
        "q:suspicious": "Suspicious input", "q:unreadable_source": "Unreadable report or recording",
        "bias": "Baseline",
    }
    if name in fixed:
        return fixed[name]
    if kind == "engine":
        return f"Rules suggested {key}"
    if kind == "age":
        return f"Age {key}"
    if kind == "hist":
        return f"History: {key}"
    if kind == "lab":
        lab, _, direction = key.rpartition("_")
        return f"{'Low' if direction == 'low' else 'High'} {lab.replace('hb', 'haemoglobin')}"
    return name


def build(ex: Extraction, tri: TriageOutput, validation: Optional[ValidationReport] = None, text: str = "") -> dict[str, float]:
    """Sparse feature dict (only non-zero entries)."""
    f: dict[str, float] = {"bias": 1.0, f"engine:{tri.priority}": 1.0}
    for flag in tri.red_flags:
        f[f"flag:{flag.rule_id}"] = 1.0
    present = [s for s in ex.symptoms if not s.negated and s.canonical_id]
    for s in present:
        f[f"sym:{s.canonical_id}"] = 1.0
    if any((s.severity or "") == "severe" for s in present):
        f["sym:any_severe"] = 1.0
    if any((s.progression or "") == "worsening" for s in present):
        f["sym:any_worsening"] = 1.0

    v = ex.vitals

    def num(x):
        return float(x.value) if isinstance(x.value, (int, float)) and not isinstance(x.value, bool) else None

    sp, pu, rr, sb, tc = num(v.spo2), num(v.pulse), num(v.resp_rate), num(v.systolic_bp), num(v.temperature_c)
    if sp is not None:
        f["v:spo2_low"] = max(0.0, (96 - sp) / 10)
    if pu is not None:
        f["v:pulse_high"] = max(0.0, (pu - 100) / 30)
        f["v:pulse_low"] = max(0.0, (50 - pu) / 20)
    if rr is not None:
        f["v:rr_high"] = max(0.0, (rr - 20) / 10)
    if sb is not None:
        f["v:sbp_low"] = max(0.0, (110 - sb) / 30)
        f["v:sbp_high"] = max(0.0, (sb - 160) / 40)
    if tc is not None:
        f["v:temp_high"] = max(0.0, (tc - 37.5) / 2)
    if v.consciousness.value not in (None, "A"):
        f["v:not_alert"] = 1.0
    if all(getattr(v, k).value is None for k in type(v).model_fields):
        f["v:none_measured"] = 1.0
    if tri.news2:
        f["v:news2"] = min(1.5, tri.news2.total / 10)

    labs = {lab.canonical_id: lab for lab in ex.labs if lab.canonical_id}
    for name, (lab_id, fn) in LAB_FEATURES.items():
        lab = labs.get(lab_id)
        if lab is not None and isinstance(lab.value, (int, float)):
            f[name] = fn(float(lab.value))
    if labs.get("troponin") and labs["troponin"].value == "positive":
        f["lab:troponin_pos"] = 1.0

    age = ex.age_years.value if isinstance(ex.age_years.value, (int, float)) else None
    if age is None:
        f["age:unknown"] = 1.0
    else:
        for band, lo, hi in AGE_BANDS:
            if lo <= age <= hi:
                f[band] = 1.0
    if ex.sex.value == "female":
        f["sex:female"] = 1.0
    if ex.pregnancy_status.value == "pregnant":
        f["pregnant"] = 1.0

    blob = " ".join([text, *(str(h.value) for h in (*ex.medical_history, *ex.medications) if h.value)]).lower()
    for name, pattern in HISTORY.items():
        if re.search(pattern, blob):
            f[name] = 1.0

    if tri.data_quality.uncertain:
        f["q:uncertain"] = 1.0
    if validation:
        f["q:low_completeness"] = round(1 - validation.completeness, 3)
        if validation.conflicts:
            f["q:conflict"] = 1.0
        if validation.injections:
            f["q:suspicious"] = 1.0
    if any(s.severity == "critical" for s in ex.source_flags):
        f["q:unreadable_source"] = 1.0
    return {k: round(val, 4) for k, val in f.items() if val}
