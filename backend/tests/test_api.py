"""End-to-end: every synthetic case through the API with the offline (rules) extractor."""
import pytest


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_consent_required(client, synthetic_cases):
    body = dict(synthetic_cases[0]["case"], consent_given=False)
    assert client.post("/api/cases", json=body).status_code == 422


@pytest.mark.parametrize("idx", range(10))
def test_synthetic_case_priority(client, synthetic_cases, idx):
    c = synthetic_cases[idx]
    r = client.post("/api/cases", json=c["case"])
    assert r.status_code == 201, r.text
    d = r.json()
    tri = d["triage"]
    assert tri["priority"] == c["expected_priority"], f"{c['id']}: {tri['reasons']}"
    fired = {f["rule_id"] for f in tri["red_flags"]}
    assert set(c["expected_flags"]) <= fired, f"{c['id']}: fired {fired}"
    assert d["note"]["status"] == "draft" and "DRAFT" in d["note"]["content"]
    # every red-flag evidence item that has a span must point at real source text
    texts = {s["id"]: s["original_text"] for s in d["sources"]}
    for f in tri["red_flags"]:
        for e in f["evidence"]:
            if e.get("source_id") and e.get("start") is not None:
                assert texts[e["source_id"]][e["start"]:e["end"]].lower() == e["quote"].lower()


def test_conflicting_vitals_flagged(client, synthetic_cases):
    c = next(x for x in synthetic_cases if x["id"] == "c07_conflicting_vitals")
    d = client.post("/api/cases", json=c["case"]).json()
    disc = d["extraction"]["discrepancies"]
    assert any(x["field"] == "vitals.spo2" for x in disc)
    assert d["extraction"]["vitals"]["spo2"]["value"] == 86  # more concerning value used


def test_queue_sorted_by_urgency(client):
    items = client.get("/api/cases", params={"status": "awaiting_review"}).json()
    scores = [i["sort_score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    assert items[0]["priority"] == "P1"


def test_review_flow_and_audit(client, synthetic_cases, as_role):
    d = client.post("/api/cases", json=synthetic_cases[5]["case"]).json()
    cid = d["id"]
    # intake role cannot approve
    r = client.post(f"/api/cases/{cid}/review", json={"action": "approve", "final_priority": "P4"},
                    headers=as_role("intake"))
    assert r.status_code == 403
    # override needs a reason
    r = client.post(f"/api/cases/{cid}/review", json={"action": "override", "final_priority": "P3"})
    assert r.status_code == 422
    r = client.put(f"/api/cases/{cid}/note", json={"content": "Edited by clinician."})
    assert r.json()["note"]["version"] == 2
    r = client.post(f"/api/cases/{cid}/review",
                    json={"action": "override", "final_priority": "P3", "reason": "Elderly relative at home, review today"})
    assert r.status_code == 200
    assert r.json()["status"] == "finalized" and r.json()["final_priority"] == "P3"
    assert r.json()["note"]["status"] == "approved"
    actions = [a["action"] for a in client.get("/api/audit", params={"case_id": cid}).json()]
    for a in ("case_created", "extraction_completed", "triage_suggested", "note_drafted", "note_edited", "priority_overridden"):
        assert a in actions


def test_waiting_escalation_stays_within_band():
    from app.api.cases import MAX_ESCALATION, queue_score, waiting_escalation
    from app.services.triage.engine import BASE_SCORE

    assert waiting_escalation(70, 60) > 0  # 10 min over a 60-min target
    assert waiting_escalation(10_000, 60) < MAX_ESCALATION
    # an overdue P3 case climbs, but a P3 case waiting forever still ranks below a fresh P2 case
    assert queue_score(55, "P3", 90, 60, True) > 55
    assert queue_score(65, "P3", 10_000, 60, True) < BASE_SCORE["P2"]
    assert queue_score(95, "P1", 30, 0, True) > 95  # P1 has no ceiling


def test_queue_items_carry_flag_counts(client):
    items = client.get("/api/cases").json()
    assert all({"flag_counts", "completeness", "queue_score", "target_minutes"} <= set(i) for i in items)
    assert any(i["flag_counts"].get("missing", 0) > 0 for i in items)
