"""NEWS2 (National Early Warning Score 2, Royal College of Physicians, 2017), SpO2 scale 1.

Missing parameters are NOT assumed normal: the score is labelled partial and the
missing vitals become follow-up items. NEWS2 is not validated for under-16s or in
pregnancy, so it is shown for reference only in those cases.
"""
from typing import Optional

from app.schemas.extraction import Vitals
from app.schemas.triage import News2Result


def _rr(v: float) -> int:
    return 3 if v <= 8 else 1 if v <= 11 else 0 if v <= 20 else 2 if v <= 24 else 3


def _spo2(v: float) -> int:
    return 3 if v <= 91 else 2 if v <= 93 else 1 if v <= 95 else 0


def _sbp(v: float) -> int:
    return 3 if v <= 90 else 2 if v <= 100 else 1 if v <= 110 else 0 if v <= 219 else 3


def _pulse(v: float) -> int:
    return 3 if v <= 40 else 1 if v <= 50 else 0 if v <= 90 else 1 if v <= 110 else 2 if v <= 130 else 3


def _temp(v: float) -> int:
    return 3 if v <= 35.0 else 1 if v <= 36.0 else 0 if v <= 38.0 else 1 if v <= 39.0 else 2


def _conscious(v: str) -> int:
    return 0 if str(v).upper() == "A" else 3


def compute_news2(vitals: Vitals, age_years: Optional[float] = None, pregnant: bool = False) -> Optional[News2Result]:
    comps: dict[str, int] = {}
    pairs = [
        ("resp_rate", _rr), ("spo2", _spo2), ("systolic_bp", _sbp),
        ("pulse", _pulse), ("temperature_c", _temp), ("consciousness", _conscious),
    ]
    for field, fn in pairs:
        v = getattr(vitals, field).value
        if v is None:
            continue
        try:
            comps[field] = fn(v)
        except (TypeError, ValueError):
            continue
    if vitals.on_oxygen.value is not None:
        comps["on_oxygen"] = 2 if vitals.on_oxygen.value is True else 0

    if not comps:
        return None

    total = sum(comps.values())
    present = len(comps)
    if total >= 7:
        band = "high"
    elif total >= 5:
        band = "medium"
    elif any(v == 3 for v in comps.values()):
        band = "low-medium"
    elif total >= 1:
        band = "low"
    else:
        band = "none"

    applicable = not pregnant and (age_years is None or age_years >= 16)
    note = None
    if not applicable:
        note = "NEWS2 is not validated for patients under 16 or in pregnancy; shown for reference only."
    elif present < 7:
        note = f"Partial score: {present}/7 parameters available. Missing parameters are not assumed normal."
    return News2Result(
        total=total, components=comps, params_present=present, band=band,
        partial=present < 7, applicable=applicable, note=note,
    )


def news2_priority(n: News2Result) -> Optional[str]:
    """Map a NEWS2 band to a queue priority (RCP clinical-response thresholds)."""
    return {"high": "P1", "medium": "P2", "low-medium": "P2", "low": "P3"}.get(n.band)
