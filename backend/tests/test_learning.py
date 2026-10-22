import json

import pytest
from sqlmodel import Session, select

from app.db import engine
from app.models import ShadowPrediction
from app.schemas.triage import TriageOutput
from app.services.learning import shadow
from app.services.learning import simulate as S
from app.services.learning.bandit import MIN_TRAINING, Agent, reward


# ------------------------------------------------------------------ bandit unit tests
def test_reward_is_asymmetric():
    assert reward("P2", "P2") == 1
    assert reward("P1", "P2") == -1  # over-triage, one level
    assert reward("P3", "P2") == -5  # under-triage, one level
    assert reward("P4", "P2") == -10


def test_agent_abstains_until_trained_then_learns_a_pattern():
    a = Agent(["bias", "x"])
    assert a.predict({"bias": 1, "x": 1}).abstained
    for i in range(MIN_TRAINING + 10):
        a.update({"bias": 1, "x": 1}, "P2")
        a.update({"bias": 1}, "P4")
    assert a.predict({"bias": 1, "x": 1}).predicted == "P2"
    assert a.predict({"bias": 1}).predicted == "P4"


def test_asymmetric_reward_makes_the_agent_cautious():
    # clinicians say P3 70% of the time and P2 30%: guessing P3 risks under-triage, so the agent says P2
    a = Agent(["bias"])
    for i in range(100):
        a.update({"bias": 1}, "P3" if i % 10 < 7 else "P2")
    assert a.predict({"bias": 1}).predicted == "P2"


def test_novel_cases_are_not_guessed():
    a = Agent(["bias", "seen", "never_seen"])
    for _ in range(60):
        a.update({"bias": 1, "seen": 1}, "P3")
    p = a.predict({"bias": 1, "never_seen": 1})
    assert p.abstained and "unlike" in p.abstain_reason


# ------------------------------------------------------------------ simulation
def test_six_month_simulation_learns_local_judgement():
    r = S.run(weeks=26, per_week=20, seed=7)
    f = r["final"]
    assert f["agent_agreement_last100"] > f["rules_agreement_last100"]
    assert f["mean_reward_agent"] > f["mean_reward_rules"]
    assert f["agent_under_triage_last100"] < f["rules_under_triage_last100"]
    assert r["patterns"]["diabetic_gi"]["agent_suggests"] == "P2"
    assert r["patterns"]["pregnant_headache"]["agent_suggests"] == "P2"
    # early weeks: still learning (abstains), later full coverage
    assert r["curve"][0]["coverage"] == 0 and r["curve"][-1]["coverage"] >= 0.9


# ------------------------------------------------------------------ shadow mode through the API
@pytest.fixture
def restore_shadow():
    yield
    with Session(engine) as s:
        cfg = shadow.get_config(s)
        cfg.mode = "shadow"
        s.add(cfg)
        s.commit()


def _case(client, msg, **patient):
    body = {"patient": {"name": "Learn Test", "age_years": 40, **patient}, "consent_given": True, "message": msg}
    return client.post("/api/cases", json=body).json()


def test_shadow_prediction_is_recorded_blind_and_learned(client):
    d = _case(client, "Runny nose and sore throat since 2 days")
    assert d["learning_mode"] == "shadow" and d["agent"] is None
    with Session(engine) as s:
        row = s.exec(select(ShadowPrediction).where(ShadowPrediction.case_id == d["id"])).first()
        assert row and row.hidden and row.final_priority is None and row.features
    audit = client.get("/api/audit", params={"case_id": d["id"], "action": "agent_predicted"}).json()
    assert audit and "suggested" not in audit[0]["details"]  # the suggestion is not leaked via the audit log

    before = client.get("/api/learning/status").json()["metrics"]["reviews"]
    client.post(f"/api/cases/{d['id']}/review", json={"action": "approve", "final_priority": d["triage"]["priority"]})
    st = client.get("/api/learning/status").json()
    assert st["metrics"]["reviews"] == before + 1
    with Session(engine) as s:
        row = s.exec(select(ShadowPrediction).where(ShadowPrediction.case_id == d["id"])).first()
        assert row.final_priority == d["triage"]["priority"] and row.reviewed_at


def test_mode_switch_needs_graduation_and_clinical_lead(client, as_role, restore_shadow):
    assert client.post("/api/learning/mode", json={"mode": "recommend"}).status_code == 409
    assert client.post("/api/learning/mode", json={"mode": "recommend", "force": True}, headers=as_role("nurse")).status_code == 403
    assert client.post("/api/learning/mode", json={"mode": "recommend", "force": True}).status_code == 200
    actions = [a["details"] for a in client.get("/api/audit", params={"action": "agent_mode_changed"}).json()]
    assert actions[0]["forced"] is True


def test_recommendation_mode_can_raise_but_not_lower(client, monkeypatch, restore_shadow):
    client.post("/api/learning/bootstrap", params={"n": 400})
    client.post("/api/learning/mode", json={"mode": "recommend", "force": True})
    monkeypatch.setattr(shadow, "_blind", lambda case_id: False)
    d = _case(client, "Pregnant, 7 months. Headache since this morning.", sex="female", age_years=27)
    assert d["agent"] is not None and d["agent"]["predicted"] == "P2"
    assert d["triage"]["priority"] == "P2" and d["triage"]["reasons"][0]["kind"] == "learned"

    # unit check: a less urgent suggestion never lowers the rules priority
    row = ShadowPrediction(case_id=1, features={}, engine_priority="P2", predicted="P4", confidence=0.99,
                           mode="recommend", hidden=False)
    tri = TriageOutput.model_validate(d["triage"] | {"priority": "P2"})
    assert shadow.apply_to_triage(tri, row, type("P", (), {"explanation": []})()).priority == "P2"


def test_blind_checks_hide_the_suggestion(client, monkeypatch, restore_shadow):
    client.post("/api/learning/mode", json={"mode": "recommend", "force": True})
    monkeypatch.setattr(shadow, "_blind", lambda case_id: True)
    d = _case(client, "Pregnant, headache since morning", sex="female", age_years=25)
    assert d["agent"] is None
    assert all(r["kind"] != "learned" for r in d["triage"]["reasons"])


def test_similar_cases_come_from_finalized_decisions(client):
    first = _case(client, "Pet mein dard hai since morning, sugar ki dawai leta hoon", age_years=55)
    client.post(f"/api/cases/{first['id']}/review", json={"action": "override", "final_priority": "P2", "reason": "possible DKA"})
    second = _case(client, "Pet dard ho raha hai, diabetes hai", age_years=58)
    sim = client.get(f"/api/cases/{second['id']}/similar").json()
    ids = [c["case_id"] for c in sim["cases"]]
    assert first["id"] in ids
    hit = next(c for c in sim["cases"] if c["case_id"] == first["id"])
    assert hit["final_priority"] == "P2" and hit["changed_by_clinician"] and "Abdominal pain" in hit["shared"]
    assert "Learn Test" not in json.dumps(sim)  # no identifiers


def test_erasure_removes_learning_examples(client, as_role):
    d = _case(client, "Fever and cough for 3 days")
    client.post(f"/api/cases/{d['id']}/review", json={"action": "approve", "final_priority": d["triage"]["priority"]})
    n_before = client.get("/api/learning/status").json()["model"]["trained_on"]
    client.post(f"/api/cases/{d['id']}/withdraw", json={})
    r = client.delete(f"/api/patients/{d['patient']['id']}", headers=as_role("admin")).json()
    assert r["learning_examples"] == 1
    assert client.get("/api/learning/status").json()["model"]["trained_on"] == n_before - 1
