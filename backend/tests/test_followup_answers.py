def test_answers_close_gaps_and_retriage(client):
    body = {"patient": {"name": "Answer Flow", "age_years": 55, "sex": "male", "preferred_language": "en"},
            "consent_given": True, "message": "Chest pain since 1 hour."}
    d = client.post("/api/cases", json=body).json()
    v = d["triage"]["validation"]
    ids = {q["id"] for q in v["followups"]}
    assert {"q:cp_sweating", "q:cp_radiation", "q:cp_vitals"} <= ids
    before = v["completeness"]

    r = client.post(f"/api/cases/{d['id']}/answers", json={"answers": [
        {"question_id": "q:cp_sweating", "answer": "yes"},
        {"question_id": "q:cp_radiation", "yes": False},
        {"question_id": "q:cp_vitals", "answer": "pulse 112, BP 150/94, SpO2 95%"},
    ]})
    assert r.status_code == 200, r.text
    d2 = r.json()
    ex = d2["extraction"]
    by = {s["canonical_id"]: s for s in ex["symptoms"]}
    assert by["sweating"]["negated"] is False
    assert any(s["canonical_id"] == "arm_jaw_radiation" and s["negated"] for s in ex["symptoms"])
    assert ex["vitals"]["pulse"]["value"] == 112 and ex["vitals"]["systolic_bp"]["value"] == 150
    remaining = {m["id"] for m in d2["triage"]["validation"]["missing"]}
    assert not {"cp_sweating", "cp_radiation", "cp_vitals"} & remaining
    assert d2["triage"]["validation"]["completeness"] > before
    assert d2["triage"]["priority"] == "P1"  # chest pain + sweating
    answer_src = next(s for s in d2["sources"] if s["kind"] == "followup_answer")
    assert "Patient denies" in answer_src["original_text"]


def test_unknown_question_rejected(client):
    body = {"patient": {"name": "Bad Q", "age_years": 30}, "consent_given": True, "message": "fever"}
    d = client.post("/api/cases", json=body).json()
    r = client.post(f"/api/cases/{d['id']}/answers", json={"answers": [{"question_id": "q:nope", "answer": "x"}]})
    assert r.status_code == 422
