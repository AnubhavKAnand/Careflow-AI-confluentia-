"""Does an extraction contain anything a clinician can triage on?"""
from app.schemas.extraction import Extraction

# Free-text "symptoms" that say nothing specific: a message reduced to these is still vague.
_VAGUE = {"unwell", "not well", "feeling unwell", "sick", "ill", "problem", "issue", "pain", "discomfort", "tired",
          "weak", "weakness", "not feeling well", "theek nahi", "tabiyat kharab", "other", "unknown", "symptoms"}


def has_clinical_content(ex: Extraction) -> bool:
    """True if at least one recognised symptom (stated or denied), a lab result, or a specific
    model-extracted complaint whose quote was found in the text (e.g. "toe pain", "otalgia")."""
    if ex.labs or any(s.canonical_id for s in ex.symptoms):
        return True
    return any(
        s.evidence is not None and s.evidence.grounded and (s.name or "").strip().lower() not in _VAGUE
        and len((s.name or "").strip()) >= 3
        for s in ex.symptoms
    )
