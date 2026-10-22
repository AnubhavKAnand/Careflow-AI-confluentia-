"""Similar-case memory: past cases a clinician has already decided, ranked by how alike they are.

Similarity is cosine over the clinical features (symptoms, warning signs, vitals pattern, labs,
age band, history), not over free text, so it is explainable ("shared: fever, age 65+,
history: diabetes") and contains no patient identifiers.
"""
import math

from sqlmodel import Session, select

from app.models import Case, Patient, ShadowPrediction
from app.services.learning.features import NON_CLINICAL_PREFIXES, label


def _clinical(f: dict[str, float]) -> dict[str, float]:
    return {k: v for k, v in f.items() if not k.startswith(NON_CLINICAL_PREFIXES)}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def similar_cases(session: Session, case_id: int, k: int = 5, min_similarity: float = 0.35) -> list[dict]:
    me = session.exec(select(ShadowPrediction).where(ShadowPrediction.case_id == case_id)).first()
    if not me:
        return []
    mine = _clinical(me.features)
    rows = session.exec(
        select(ShadowPrediction, Case, Patient)
        .join(Case, Case.id == ShadowPrediction.case_id)
        .join(Patient, Patient.id == Case.patient_id)
        .where(ShadowPrediction.final_priority.is_not(None), ShadowPrediction.case_id != case_id)  # type: ignore[union-attr]
    ).all()
    scored = []
    for pred, case, patient in rows:
        if patient.withdrawn_at:
            continue
        theirs = _clinical(pred.features)
        sim = cosine(mine, theirs)
        if sim < min_similarity:
            continue
        shared = sorted(set(mine) & set(theirs), key=lambda n: -min(mine[n], theirs[n]))
        scored.append({
            "case_id": case.id,
            "similarity": round(sim, 3),
            "final_priority": pred.final_priority,
            "rules_priority": pred.engine_priority,
            "changed_by_clinician": pred.final_priority != pred.engine_priority,
            "chief_complaint": case.chief_complaint,
            "age_band": next((label(n) for n in theirs if n.startswith("age:")), None),
            "shared": [label(n) for n in shared[:5]],
            "reviewed_at": pred.reviewed_at,
        })
    scored.sort(key=lambda x: -x["similarity"])
    top = scored[:k]
    summary = None
    if top:
        counts: dict[str, int] = {}
        for t in top:
            counts[t["final_priority"]] = counts.get(t["final_priority"], 0) + 1
        common = max(counts, key=counts.get)
        summary = f"{counts[common]} of {len(top)} similar past cases were finalized as {common}."
    return [{"summary": summary, "cases": top}] if top else []
