"""Evaluate the deterministic red-flag rules in rules/red_flags.yaml."""
from functools import lru_cache
from typing import Any, Optional

import yaml

from app.config import RULES_DIR
from app.schemas.extraction import Evidence, LabResult, Vitals
from app.schemas.triage import RedFlagHit
from app.services.triage.text_match import label_for

_OPS = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
}


@lru_cache
def load_rules() -> list[dict[str, Any]]:
    with open(RULES_DIR / "red_flags.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _labs_hit(cond: dict, labs: dict[str, LabResult]) -> tuple[bool, list[str], list[Evidence]]:
    for lab_id, ops in cond.items():
        lab = labs.get(lab_id)
        if lab is None or lab.value is None:
            continue
        for op, threshold in ops.items():
            if op == "eq":
                hit = str(lab.value).lower() == str(threshold).lower()
            else:
                try:
                    hit = _OPS[op](float(lab.value), float(threshold))
                except (TypeError, ValueError):
                    hit = False
            if hit:
                shown = f"{lab.value:g}" if isinstance(lab.value, float) else lab.value
                return True, [f"{lab.name} {shown}{(' ' + lab.unit) if lab.unit else ''}"], [lab.evidence] if lab.evidence else []
    return False, [], []


def _vitals_hit(cond: dict, vitals: Vitals) -> tuple[bool, list[str], list[Evidence]]:
    for field, ops in cond.items():
        ev = getattr(vitals, field, None)
        if ev is None or ev.value is None:
            continue
        for op, threshold in ops.items():
            if op == "in":
                if str(ev.value).upper() in {str(t).upper() for t in threshold}:
                    return True, [f"{field}={ev.value}"], [ev.evidence] if ev.evidence else []
                continue
            try:
                if _OPS[op](float(ev.value), float(threshold)):
                    return True, [f"{field}={ev.value}"], [ev.evidence] if ev.evidence else []
            except (TypeError, ValueError):
                continue
    return False, [], []


def evaluate(
    symptoms: dict[str, list[Evidence]],
    vitals: Vitals,
    age_years: Optional[float] = None,
    pregnant: bool = False,
    labs: Optional[dict[str, LabResult]] = None,
) -> list[RedFlagHit]:
    """symptoms: canonical id -> evidence list (only symptoms that are present, i.e. not negated)."""
    hits: list[RedFlagHit] = []
    for rule in load_rules():
        matched: list[str] = []
        evidence: list[Evidence] = []
        ok = True

        demo = rule.get("demographics") or {}
        if demo.get("pregnant") and not pregnant:
            ok = False
        if "age_max_years" in demo and (age_years is None or age_years > demo["age_max_years"]):
            ok = False
        if "age_min_years" in demo and (age_years is None or age_years < demo["age_min_years"]):
            ok = False

        if ok and rule.get("symptoms_all_of"):
            for group in rule["symptoms_all_of"]:
                present = [cid for cid in group if cid in symptoms]
                if not present:
                    ok = False
                    break
                matched.extend(label_for(c) for c in present)
                for c in present:
                    evidence.extend(symptoms[c])

        if ok and rule.get("symptoms_any_of"):
            present = [cid for cid in rule["symptoms_any_of"] if cid in symptoms]
            if not present:
                ok = False
            else:
                matched.extend(label_for(c) for c in present)
                for c in present:
                    evidence.extend(symptoms[c])

        if ok and rule.get("vitals"):
            vok, vm, vev = _vitals_hit(rule["vitals"], vitals)
            ok = vok
            matched.extend(vm)
            evidence.extend(vev)

        if ok and rule.get("labs"):
            lok, lm, lev = _labs_hit(rule["labs"], labs or {})
            ok = lok
            matched.extend(lm)
            evidence.extend(lev)

        has_condition = any(rule.get(k) for k in ("symptoms_all_of", "symptoms_any_of", "vitals", "labs"))
        if ok and has_condition:
            hits.append(
                RedFlagHit(
                    rule_id=rule["id"], label=rule["label"], priority=rule["priority"],
                    rationale=rule.get("rationale", ""), reference=rule.get("reference"),
                    matched=list(dict.fromkeys(matched)), evidence=evidence,
                )
            )
    return _drop_subsumed(hits)


def _drop_subsumed(hits: list[RedFlagHit]) -> list[RedFlagHit]:
    """If 'cardiac_chest_pain' (P1) fired, the generic 'chest_pain' (P2) adds nothing."""
    subsumes = {
        "cardiac_chest_pain": {"chest_pain", "palpitations", "palpitations_unstable"},
        "severe_breathing": {"breathlessness"},
        "hypoxia_severe": {"hypoxia"},
        "critical_platelets": {"low_platelets"},
        "critical_anaemia": {"severe_anaemia"},
        "palpitations_unstable": {"palpitations"},
        "acvpu_unresponsive": {"acvpu_voice_or_confused"},
        "unresponsive": {"acvpu_voice_or_confused"},
    }
    fired = {h.rule_id for h in hits}
    drop = set().union(*(subsumes.get(r, set()) for r in fired))
    return sorted([h for h in hits if h.rule_id not in drop], key=lambda h: (h.priority, h.rule_id))
