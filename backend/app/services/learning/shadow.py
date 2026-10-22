"""Shadow mode and recommendation mode for the learned agent.

Shadow mode (default): for every case the agent records what it WOULD suggest, before any clinician
decision, and nobody sees it. Clinicians triage independently; their final priority is the label.

Recommendation mode (after graduation and a clinical lead's sign-off): the suggestion is shown to
clinicians. It can raise a case's priority but never lower it below the rules/NEWS2 suggestion.
On ~10% of cases it is deliberately hidden ("blind checks") so automation bias can be measured.

The model is recomputed from the reviewed predictions in the database (cached until they change), so
it always reflects exactly the decisions that still exist; erasing a patient removes their influence.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, func, select

from app.models import AgentConfig, ShadowPrediction
from app.schemas.extraction import Extraction
from app.schemas.triage import PRIORITY_INFO, Reason, TriageOutput, more_urgent
from app.schemas.validation import ValidationReport
from app.services.learning import features as F
from app.services.learning.bandit import ACTIONS, MIN_TRAINING, Agent, Prediction, reward
from app.services.privacy import audit_logger
from app.services.triage.engine import BASE_SCORE

BLIND_CHECK_SHARE = 0.10
RAISE_MIN_CONFIDENCE = 0.5
GRADUATION = {"min_reviews": 150, "agreement": 0.80, "max_under_triage": 0.10, "coverage": 0.80}

_cache: dict[tuple, Agent] = {}


# ------------------------------------------------------------------ config + model
def get_config(session: Session) -> AgentConfig:
    cfg = session.exec(select(AgentConfig)).first()
    if not cfg:
        cfg = AgentConfig()
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


def _training_rows(session: Session) -> list[ShadowPrediction]:
    return list(session.exec(select(ShadowPrediction).where(ShadowPrediction.final_priority.is_not(None))  # type: ignore[union-attr]
                             .order_by(ShadowPrediction.reviewed_at, ShadowPrediction.id)).all())


def live_agent(session: Session) -> Agent:
    key_row = session.exec(select(func.count(ShadowPrediction.id), func.max(ShadowPrediction.reviewed_at))
                           .where(ShadowPrediction.final_priority.is_not(None))).one()  # type: ignore[union-attr]
    key = (str(session.get_bind().url), key_row[0], str(key_row[1]), tuple(F.feature_names()))
    if key not in _cache:
        agent = Agent(F.feature_names())
        for row in _training_rows(session):
            agent.update(row.features, row.final_priority)
        _cache.clear()
        _cache[key] = agent
    return _cache[key]


def _blind(case_id: int) -> bool:
    return int(hashlib.sha256(f"blind:{case_id}".encode()).hexdigest(), 16) % 100 < BLIND_CHECK_SHARE * 100


# ------------------------------------------------------------------ per case
def predict_for_case(session: Session, case_id: int, ex: Extraction, tri: TriageOutput,
                     validation: Optional[ValidationReport], text: str) -> tuple[ShadowPrediction, Prediction]:
    cfg = get_config(session)
    feats = F.build(ex, tri, validation, text)
    agent = live_agent(session)
    pred = agent.predict(feats)
    row = session.exec(select(ShadowPrediction).where(ShadowPrediction.case_id == case_id)).first() or ShadowPrediction(
        case_id=case_id, features={}, engine_priority=tri.priority)
    row.features, row.engine_priority = feats, tri.priority
    row.predicted, row.scores, row.confidence, row.abstained = pred.predicted, pred.scores, pred.confidence, pred.abstained
    row.mode = cfg.mode
    row.hidden = cfg.mode == "shadow" or _blind(case_id)
    row.model_version = agent.n
    row.explanation = pred.explanation
    row.final_priority, row.reward, row.reviewed_at = None, None, None
    session.add(row)
    session.flush()
    return row, pred


def apply_to_triage(tri: TriageOutput, row: ShadowPrediction, pred: Prediction) -> TriageOutput:
    """Recommendation mode only: a confident, visible suggestion may RAISE the priority, never lower it."""
    if row.mode != "recommend" or row.hidden or row.abstained or not row.predicted:
        return tri
    if row.predicted == more_urgent(row.predicted, tri.priority) and row.predicted != tri.priority \
            and row.confidence >= RAISE_MIN_CONFIDENCE:
        why = ", ".join(e["label"] for e in pred.explanation[:3])
        tri.reasons.insert(0, Reason(kind="learned", priority=row.predicted,
                                     text=f"Clinicians here usually review cases like this as {row.predicted} ({why}). "
                                          f"Learned from {row.model_version} past decisions."))
        tri.priority = row.predicted
        tri.priority_label = PRIORITY_INFO[row.predicted]["label"]
        tri.target_minutes = PRIORITY_INFO[row.predicted]["target_minutes"]
        tri.sort_score = float(max(tri.sort_score, BASE_SCORE[row.predicted]))
    return tri


def agent_view(row: Optional[ShadowPrediction]) -> Optional[dict]:
    """What a clinician may see about the agent for one case (nothing in shadow mode or on blind checks)."""
    if not row or row.hidden or row.mode != "recommend":
        return None
    return {"predicted": row.predicted, "confidence": row.confidence, "abstained": row.abstained,
            "rules_priority": row.engine_priority, "model_version": row.model_version,
            "explanation": row.explanation}


def learn_from_review(session: Session, case_id: int, final: str, actor: str) -> None:
    row = session.exec(select(ShadowPrediction).where(ShadowPrediction.case_id == case_id)).first()
    if not row:
        return
    row.final_priority = final
    row.reviewed_at = datetime.now(timezone.utc)
    row.reward = reward(row.predicted, final) if row.predicted else None
    session.add(row)
    audit_logger.log(session, actor="shadow-agent", actor_type="ai", action="agent_learned", case_id=case_id,
                     details={"mode": row.mode, "visible": not row.hidden, "agent": row.predicted,
                              "rules": row.engine_priority, "final": final, "reward": row.reward})


# ------------------------------------------------------------------ metrics + graduation
def _rate(xs, ok) -> Optional[float]:
    return round(sum(1 for x in xs if ok(x)) / len(xs), 3) if xs else None


def metrics(session: Session) -> dict:
    rows = [r for r in _training_rows(session) if not r.synthetic]
    answered = [r for r in rows if r.predicted]
    tail = answered[-100:]
    urgent_tail = [r for r in tail if r.final_priority in ("P1", "P2")]
    confusion = {a: {b: 0 for b in ACTIONS} for a in ACTIONS}  # agent -> clinician
    for r in answered:
        confusion[r.predicted][r.final_priority] += 1
    curve, bucket = [], 20
    for i in range(0, len(rows), bucket):
        chunk = rows[i:i + bucket]
        ans = [r for r in chunk if r.predicted]
        curve.append({"upto": i + len(chunk),
                      "agent_agreement": _rate(ans, lambda r: r.predicted == r.final_priority),
                      "rules_agreement": _rate(chunk, lambda r: r.engine_priority == r.final_priority),
                      "coverage": _rate(chunk, lambda r: r.predicted is not None)})
    visible = [r for r in answered if r.mode == "recommend" and not r.hidden]
    blind = [r for r in answered if r.mode == "recommend" and r.hidden]
    return {
        "reviews": len(rows),
        "synthetic_examples": sum(1 for r in _training_rows(session) if r.synthetic),
        "agreement_last100": _rate(tail, lambda r: r.predicted == r.final_priority),
        "rules_agreement_last100": _rate(rows[-100:], lambda r: r.engine_priority == r.final_priority),
        "under_triage_last100": _rate(urgent_tail, lambda r: ACTIONS.index(r.predicted) > ACTIONS.index(r.final_priority)),
        "rules_under_triage_last100": _rate([r for r in rows[-100:] if r.final_priority in ("P1", "P2")],
                                            lambda r: ACTIONS.index(r.engine_priority) > ACTIONS.index(r.final_priority)),
        "coverage_last100": _rate(rows[-100:], lambda r: r.predicted is not None),
        "clinician_changed_rules": _rate(rows, lambda r: r.final_priority != r.engine_priority),
        "confusion": confusion,
        "curve": curve,
        "automation_bias": {
            "agreement_when_visible": _rate(visible, lambda r: r.predicted == r.final_priority),
            "agreement_on_blind_checks": _rate(blind, lambda r: r.predicted == r.final_priority),
            "visible_n": len(visible), "blind_n": len(blind),
        },
    }


def graduation(m: dict) -> dict:
    g = GRADUATION
    under, rules_under = m["under_triage_last100"], m["rules_under_triage_last100"]
    checks = [
        {"id": "reviews", "label": f"At least {g['min_reviews']} clinician-reviewed cases", "value": m["reviews"],
         "target": g["min_reviews"], "met": m["reviews"] >= g["min_reviews"]},
        {"id": "agreement", "label": f"Agrees with clinicians on at least {g['agreement']:.0%} of recent cases",
         "value": m["agreement_last100"], "target": g["agreement"], "met": (m["agreement_last100"] or 0) >= g["agreement"]},
        {"id": "under_triage", "label": f"Rates urgent (P1/P2) cases as less urgent on at most {g['max_under_triage']:.0%}, and no more often than the rules",
         "value": under, "target": g["max_under_triage"],
         "met": under is not None and under <= g["max_under_triage"] and (rules_under is None or under <= rules_under)},
        {"id": "coverage", "label": f"Gives a suggestion (does not abstain) on at least {g['coverage']:.0%} of cases",
         "value": m["coverage_last100"], "target": g["coverage"], "met": (m["coverage_last100"] or 0) >= g["coverage"]},
    ]
    return {"checks": checks, "ready": all(c["met"] for c in checks),
            "note": "A clinical lead must still sign off; recommendation mode can be turned back to shadow at any time."}


def set_mode(session: Session, mode: str, actor: str, force: bool = False) -> AgentConfig:
    cfg = get_config(session)
    m = metrics(session)
    g = graduation(m)
    if mode == "recommend" and not g["ready"] and not force:
        raise ValueError("Graduation criteria are not met yet.")
    cfg.mode, cfg.changed_by, cfg.changed_at = mode, actor, datetime.now(timezone.utc)
    cfg.graduation_snapshot = {"metrics": {k: v for k, v in m.items() if k not in ("curve", "confusion")}, "graduation": g}
    session.add(cfg)
    audit_logger.log(session, actor=actor, actor_type="human", action="agent_mode_changed",
                     details={"mode": mode, "ready": g["ready"], "forced": force and not g["ready"],
                              "reviews": m["reviews"], "agreement": m["agreement_last100"]})
    session.commit()
    return cfg


def bootstrap(session: Session, n: int, seed: int = 101) -> int:
    """Optional cold start: add synthetic labelled examples (never counted in metrics or graduation)."""
    from app.services.learning.simulate import sample

    for feats, engine_p, final, _ in sample(n, seed):
        session.add(ShadowPrediction(case_id=None, synthetic=True, features=feats, engine_priority=engine_p,
                                     final_priority=final, reviewed_at=datetime.now(timezone.utc), mode="shadow"))
    session.commit()
    return n


MIN_TRAINING_INFO = MIN_TRAINING
