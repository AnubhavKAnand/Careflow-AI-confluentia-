"""Missing-information checks driven by rules/complaint_checklists.yaml."""
import re
from functools import lru_cache
from typing import Any, Optional

import yaml

from app.config import RULES_DIR
from app.models.case import Source
from app.schemas.extraction import Extraction
from app.schemas.validation import MissingItem

WEIGHT = {"critical": 3, "important": 2, "nice": 1}

_TIME = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|baje|o'?clock)\b|\b\d+\s*(?:min(?:ute)?s?|hours?|hrs?|ghante|ghanta|minat)\s*(?:ago|pehle|se|back)\b"
    r"|\b(?:half|aadha|adha)\s+(?:an\s+)?(?:hour|ghanta)\b|\b(?:abhi|just now|thodi der pehle|subah|raat|shaam|morning|night|evening)\b"
    r"|\d{1,2}\s*बजे|घंटे\s+पहले",
    re.I,
)
_GESTATION = re.compile(
    r"\b\d{1,2}\s*(?:weeks?|wks?|months?|mahine|mahina|hafte|hafta)\b(?:\s*(?:pregnant|ki\s+pregnancy|ka\s+garbh|gestation))?"
    r"|\b(?:first|second|third|1st|2nd|3rd)\s+trimester\b|\d{1,2}\s*(?:महीने|हफ़्ते|सप्ताह)",
    re.I,
)
_ABD_SITE = re.compile(
    r"\b(?:upper|lower|right|left|central|middle|around\s+(?:the\s+)?navel|all\s+over|epigastric|daayen|baayen|daayi|baayi|upar|neeche|"
    r"naabhi|beech\s+mein|poore\s+pet)\b|ऊपर|नीचे|दाएँ|बाएँ",
    re.I,
)


@lru_cache
def load_checklists() -> dict[str, Any]:
    with open(RULES_DIR / "complaint_checklists.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _texts(sources: list[Source]) -> str:
    return "\n".join(f"{s.original_text}\n{s.translated_text or ''}" for s in sources if s.kind != "intake_form")


def _get(ex: Extraction, path: str) -> Any:
    obj: Any = ex
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return getattr(obj, "value", obj)


def _applies(cond: Any, ex: Extraction, red_flag_ids: set[str]) -> bool:
    if cond in (None, "always"):
        return True
    age = ex.age_years.value if isinstance(ex.age_years.value, (int, float)) else None
    present = {s.canonical_id for s in ex.symptoms if not s.negated and s.canonical_id}
    if "symptoms_any" in cond and not (present & set(cond["symptoms_any"])):
        return False
    if "red_flags_any" in cond and not (red_flag_ids & set(cond["red_flags_any"])):
        return False
    if "sex" in cond and ex.sex.value != cond["sex"]:
        return False
    if "age_min" in cond and (age is None or age < cond["age_min"]):
        return False
    if "age_max" in cond and (age is None or age > cond["age_max"]):
        return False
    if cond.get("pregnant") and ex.pregnancy_status.value != "pregnant":
        return False
    return True


def _satisfied(check: dict, ex: Extraction, text: str) -> bool:
    if "never" in check:
        return False
    if "field" in check:
        v = _get(ex, check["field"])
        return v not in (None, "", "unknown")
    if "list" in check:
        return bool(getattr(ex, check["list"], []))
    if check.get("chief_onset"):
        present = [s for s in ex.symptoms if not s.negated]
        return bool(ex.timeline) or any(s.onset or s.duration for s in present)
    if "symptom_known" in check:
        known = {s.canonical_id for s in ex.symptoms if s.canonical_id}  # reported OR denied
        return bool(known & set(check["symptom_known"]))
    if "history_any" in check:
        blob = " ".join(str(v.value) for v in (*ex.medical_history, *ex.medications) if v.value).lower()
        blob += " " + text.lower()
        return any(w.lower() in blob for w in check["history_any"])
    if "vitals_all" in check:
        return all(getattr(ex.vitals, v).present for v in check["vitals_all"])
    if check.get("vitals_any"):
        return any(getattr(ex.vitals, f).present for f in type(ex.vitals).model_fields)
    if "labs_known" in check:
        return any(lab.canonical_id in check["labs_known"] for lab in ex.labs)
    if check.get("time_mentioned"):
        return bool(_TIME.search(text)) or bool(ex.timeline)
    if check.get("gestation"):
        return bool(_GESTATION.search(text))
    if check.get("abdominal_site"):
        sites = [s.body_site for s in ex.symptoms if s.canonical_id == "abdominal_pain" and s.body_site]
        return bool(sites) or bool(_ABD_SITE.search(text))
    return True


def find_missing(ex: Extraction, sources: list[Source], red_flag_ids: set[str]) -> tuple[list[MissingItem], float, list[str], dict]:
    """Returns (missing items, completeness 0-1, checklists applied, item definitions by id)."""
    cfg = load_checklists()
    text = _texts(sources)
    missing: list[MissingItem] = []
    applied: list[str] = []
    defs: dict[str, dict] = {}
    total = got = 0
    seen: set[str] = set()
    for name, cl in cfg["checklists"].items():
        if not _applies(cl.get("applies"), ex, red_flag_ids):
            continue
        applied.append(name)
        for item in cl["items"]:
            if item["id"] in seen or not _applies(item.get("applies"), ex, red_flag_ids):
                continue
            seen.add(item["id"])
            w = WEIGHT[item["priority"]]
            total += w
            if _satisfied(item["check"], ex, text):
                got += w
            else:
                defs[item["id"]] = item
                missing.append(MissingItem(id=item["id"], checklist=name, label=item["label"],
                                           priority=item["priority"], target=item["target"]))
    # The generic "record vitals" item is redundant when a specific vitals item is already missing
    specific_vitals = any("vitals_all" in defs[m.id]["check"] or "field" in defs[m.id]["check"]
                          and str(defs[m.id]["check"]["field"]).startswith("vitals.") for m in missing)
    if specific_vitals:
        missing = [m for m in missing if m.id != "vitals"]
        defs.pop("vitals", None)
    order = {"critical": 0, "important": 1, "nice": 2}
    missing.sort(key=lambda m: order[m.priority])
    return missing, round(got / total, 3) if total else 1.0, applied, defs


def question(qid: str) -> Optional[dict]:
    return load_checklists()["questions"].get(qid)
