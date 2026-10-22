"""Six months of shadow learning, compressed into seconds.

Synthetic cases are generated as structured extractions, run through the REAL triage engine and
validation layer, and labelled by a simulated clinician. The simulated clinician mostly agrees with
the rules, but also applies judgement the rules do not encode, the kind of local practice the
shadow agent is meant to pick up:

  - Elderly (65+) with fever          -> clinicians review sooner (P2)      [rules: P4/P3]
  - Diabetes + vomiting / stomach pain -> P2 (possible DKA)                  [rules: P4/P3]
  - Pregnant + headache                -> P2 (possible pre-eclampsia)        [rules: P4/P3]
  - Child under 5 with fever + vomiting -> P2 (dehydration risk)             [rules: P3/P4]
  - Young adult, isolated chest pain, normal vitals -> often P3             [rules: P2]
    (the agent should NOT learn to downgrade this: a 30% chance of P2 makes under-triage too costly)
plus ~8% inter-clinician variability.

Nothing here touches the database; results are returned for the Learning page.
"""
import random
from dataclasses import dataclass

from app.schemas.extraction import Evidence, ExtractedValue, Extraction, LabResult, Symptom, Vitals
from app.schemas.triage import PRIORITY_ORDER
from app.services.learning import features as F
from app.services.learning.bandit import ACTIONS, Agent, reward
from app.services.triage.engine import compute_triage
from app.services.validation import validate


def _sym(cid: str, severity: str | None = None) -> Symptom:
    return Symptom(name=cid.replace("_", " "), canonical_id=cid, confidence=0.9, severity=severity,
                   evidence=Evidence(source_id=1, quote=cid, grounded=True, origin="lexicon"))


def _v(**kw) -> Vitals:
    return Vitals(**{k: ExtractedValue(value=v, confidence=1.0, evidence=Evidence(origin="form", grounded=True)) for k, v in kw.items()})


def _normal_vitals(r: random.Random, temp: float | None = None) -> Vitals:
    return _v(spo2=r.randint(96, 99), pulse=r.randint(70, 95), resp_rate=r.randint(14, 19),
              systolic_bp=r.randint(112, 138), temperature_c=temp or round(r.uniform(36.5, 37.3), 1), consciousness="A")


@dataclass
class SimCase:
    profile: str
    ex: Extraction
    history: str  # free-text history the feature builder reads
    hidden_rule: str | None = None  # which clinician judgement pattern applies


def _case(r: random.Random) -> SimCase:
    p = r.choices(
        ["cold", "viral_fever", "elderly_fever", "diabetic_gi", "pregnant_headache", "child_fever_vomit", "young_chest_pain",
         "cardiac", "stroke", "hypoxia", "dengue_low_plt", "dengue_mild", "gastro", "back_pain", "snake_bite", "asthma"],
        weights=[14, 10, 7, 6, 4, 5, 7, 5, 3, 4, 3, 5, 7, 6, 2, 5],
    )[0]
    age = r.randint(18, 60)
    sex = r.choice(["male", "female"])
    syms: list[Symptom] = []
    vit = _normal_vitals(r)
    labs: list[LabResult] = []
    hist, rule, preg = "", None, None
    if p == "cold":
        syms = [_sym(c) for c in r.sample(["runny_nose", "sore_throat", "cough", "headache", "body_ache"], 2)]
    elif p == "viral_fever":
        syms = [_sym("fever"), _sym("body_ache")]
        vit = _normal_vitals(r, temp=round(r.uniform(37.8, 38.9), 1))
    elif p == "elderly_fever":
        age = r.randint(66, 88)
        syms = [_sym("fever"), *([_sym("weakness")] if r.random() < 0.5 else [])]
        vit = _normal_vitals(r, temp=round(r.uniform(37.9, 39.0), 1))
        rule = "elderly_fever"
    elif p == "diabetic_gi":
        age = r.randint(35, 70)
        syms = [_sym(r.choice(["vomiting", "abdominal_pain"])), *([_sym("weakness")] if r.random() < 0.4 else [])]
        hist = "known diabetes, on insulin" if r.random() < 0.5 else "sugar ki dawai leta hai"
        rule = "diabetic_gi"
    elif p == "pregnant_headache":
        sex, age, preg = "female", r.randint(20, 36), "pregnant"
        syms = [_sym("headache")]
        rule = "pregnant_headache"
    elif p == "child_fever_vomit":
        age = r.randint(1, 4)
        syms = [_sym("fever"), _sym("vomiting")]
        vit = _v(temperature_c=round(r.uniform(38.0, 39.2), 1), consciousness="A")
        rule = "child_fever_vomit"
    elif p == "young_chest_pain":
        age = r.randint(19, 34)
        syms = [_sym("chest_pain")]
        rule = "young_chest_pain"
    elif p == "cardiac":
        age = r.randint(45, 75)
        syms = [_sym("chest_pain", "severe"), _sym(r.choice(["sweating", "breathlessness", "arm_jaw_radiation"]))]
        hist = r.choice(["", "BP ki dawai", "diabetes"])
    elif p == "stroke":
        age = r.randint(55, 85)
        syms = [_sym(r.choice(["face_droop", "slurred_speech", "one_sided_weakness"]))]
    elif p == "hypoxia":
        age = r.randint(40, 80)
        syms = [_sym("breathlessness"), _sym("cough"), _sym("fever")]
        vit = _v(spo2=r.randint(84, 91), pulse=r.randint(100, 125), resp_rate=r.randint(22, 30), systolic_bp=r.randint(100, 130),
                 temperature_c=round(r.uniform(38, 39.5), 1), consciousness="A")
    elif p in ("dengue_low_plt", "dengue_mild"):
        syms = [_sym("fever"), _sym("body_ache")]
        plt = r.randint(8_000, 45_000) if p == "dengue_low_plt" else r.randint(90_000, 180_000)
        labs = [LabResult(name="Platelet count", canonical_id="platelets", value=float(plt), unit="/µL", confidence=0.9,
                          evidence=Evidence(source_id=2, quote="Platelet", grounded=True, origin="regex"))]
        vit = _normal_vitals(r, temp=round(r.uniform(38.0, 39.4), 1))
    elif p == "gastro":
        syms = [_sym("diarrhoea"), *([_sym("vomiting")] if r.random() < 0.5 else [])]
    elif p == "back_pain":
        syms = [_sym("back_pain")]
    elif p == "snake_bite":
        syms = [_sym("snake_bite")]
    elif p == "asthma":
        syms = [_sym("wheeze"), _sym("cough")]
        hist = "asthma, uses inhaler"
        vit = _v(spo2=r.randint(93, 97), pulse=r.randint(85, 110), resp_rate=r.randint(18, 24), consciousness="A")
    ex = Extraction(
        symptoms=syms, vitals=vit, labs=labs,
        age_years=ExtractedValue(value=age, confidence=1, evidence=Evidence(origin="form", grounded=True)),
        sex=ExtractedValue(value=sex, confidence=1, evidence=Evidence(origin="form", grounded=True)),
        pregnancy_status=ExtractedValue(value=preg, confidence=0.9 if preg else 0, evidence=Evidence(origin="lexicon", grounded=True) if preg else None),
        timeline=[],
        chief_complaint=ExtractedValue(value=syms[0].name if syms else None, confidence=0.8),
    )
    if hist:
        ex.medical_history = [ExtractedValue(value=hist, confidence=0.8)]
    return SimCase(p, ex, hist, rule)


def _shift(p: str, levels: int) -> str:
    i = min(3, max(0, PRIORITY_ORDER.index(p) + levels))
    return PRIORITY_ORDER[i]


def clinician_label(case: SimCase, engine_priority: str, r: random.Random) -> str:
    final = engine_priority
    if case.hidden_rule in ("elderly_fever", "diabetic_gi", "pregnant_headache", "child_fever_vomit"):
        final = "P2" if PRIORITY_ORDER.index(engine_priority) > 1 else engine_priority
    elif case.hidden_rule == "young_chest_pain":
        final = "P3" if r.random() < 0.7 else "P2"
    if r.random() < 0.08:  # inter-clinician variability, slightly biased toward caution
        final = _shift(final, -1 if r.random() < 0.6 else 1)
    return final


def sample(n: int, seed: int = 7) -> list[tuple[dict[str, float], str, str, SimCase]]:
    """n labelled examples: (features, engine priority, clinician priority, case)."""
    r = random.Random(seed)
    out = []
    for _ in range(n):
        c = _case(r)
        first = compute_triage(c.ex)
        report, _ = validate(c.ex, [], None, {f.rule_id for f in first.red_flags}, with_ai=False)
        tri = compute_triage(c.ex, report)
        feats = F.build(c.ex, tri, report, c.history)
        out.append((feats, tri.priority, clinician_label(c, tri.priority, r), c))
    return out


def run(weeks: int = 26, per_week: int = 20, seed: int = 7) -> dict:
    """Replay a stream of cases in shadow mode: predict blind, then learn from the clinician's decision."""
    agent = Agent(F.feature_names())
    stream = sample(weeks * per_week, seed)
    rows = []
    for i, (feats, engine_p, final, case) in enumerate(stream):
        pred = agent.predict(feats)
        rows.append({"week": i // per_week + 1, "engine": engine_p, "agent": pred.predicted, "final": final,
                     "abstained": pred.abstained, "profile": case.profile, "rule": case.hidden_rule})
        agent.update(feats, final)

    def rate(xs, ok):
        return round(sum(1 for x in xs if ok(x)) / len(xs), 3) if xs else None

    curve = []
    for w in range(1, weeks + 1):
        wk = [r for r in rows if r["week"] == w]
        answered = [r for r in wk if not r["abstained"]]
        urgent = [r for r in answered if r["final"] in ("P1", "P2")]
        curve.append({
            "week": w,
            "agent_agreement": rate(answered, lambda r: r["agent"] == r["final"]),
            "rules_agreement": rate(wk, lambda r: r["engine"] == r["final"]),
            "coverage": rate(wk, lambda r: not r["abstained"]),
            "agent_under_triage": rate(urgent, lambda r: ACTIONS.index(r["agent"]) > ACTIONS.index(r["final"])),
            "rules_under_triage": rate([r for r in wk if r["final"] in ("P1", "P2")],
                                       lambda r: ACTIONS.index(r["engine"]) > ACTIONS.index(r["final"])),
            "n": len(wk),
        })
    tail = [r for r in rows if not r["abstained"]][-100:]
    by_rule = {}
    for rule in ("elderly_fever", "diabetic_gi", "pregnant_headache", "child_fever_vomit", "young_chest_pain"):
        late = [r for r in rows if r["rule"] == rule and not r["abstained"]][-15:]
        by_rule[rule] = {"agent": rate(late, lambda r: r["agent"] == r["final"]),
                         "rules": rate(late, lambda r: r["engine"] == r["final"]),
                         "agent_suggests": max(set(r["agent"] for r in late), key=[r["agent"] for r in late].count) if late else None}
    return {
        "weeks": weeks, "per_week": per_week, "seed": seed, "curve": curve,
        "final": {
            "agent_agreement_last100": rate(tail, lambda r: r["agent"] == r["final"]),
            "rules_agreement_last100": rate(tail, lambda r: r["engine"] == r["final"]),
            "agent_under_triage_last100": rate([r for r in tail if r["final"] in ("P1", "P2")],
                                               lambda r: ACTIONS.index(r["agent"]) > ACTIONS.index(r["final"])),
            "rules_under_triage_last100": rate([r for r in tail if r["final"] in ("P1", "P2")],
                                               lambda r: ACTIONS.index(r["engine"]) > ACTIONS.index(r["final"])),
            "mean_reward_agent": round(sum(reward(r["agent"], r["final"]) for r in tail) / len(tail), 3) if tail else None,
            "mean_reward_rules": round(sum(reward(r["engine"], r["final"]) for r in tail) / len(tail), 3) if tail else None,
        },
        "patterns": by_rule,
        "top_p2_features": agent.top_weights("P2", 6),
    }
