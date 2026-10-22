import json
from pathlib import Path

from sqlmodel import Session

from app.db import engine
from app.models import AuditLog
from app.services.ingestion.storage import absolute
from app.services.privacy.redaction import redact


def _case_with_file(client, sample_reports, as_role):
    payload = {"patient": {"name": "Erase Me", "age_years": 33, "sex": "female"}, "consent_given": True,
               "message": "Bukhar hai, report attach hai"}
    r = client.post("/api/cases/intake", data={"payload": json.dumps(payload)}, headers=as_role("intake"),
                    files=[("files", ("cbc.png", (sample_reports / "cbc_dengue.png").read_bytes(), "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()


def test_withdraw_then_erase(client, sample_reports, as_role):
    d = _case_with_file(client, sample_reports, as_role)
    cid, pid = d["id"], d["patient"]["id"]
    report = next(s for s in d["sources"] if s["kind"] == "report")

    from app.models import Source
    with Session(engine) as s:
        file_path = absolute(s.get(Source, report["id"]).file_path)
    assert file_path.exists()

    # erasing without a recorded withdrawal is refused
    assert client.delete(f"/api/patients/{pid}", headers=as_role("admin")).status_code == 409

    r = client.post(f"/api/cases/{cid}/withdraw", json={"reason": "Patient request at desk"}, headers=as_role("intake"))
    assert r.status_code == 200
    # leaves the queue, processing stops, clinicians can no longer open it
    assert cid not in [c["id"] for c in client.get("/api/cases").json()]
    assert client.post(f"/api/cases/{cid}/retriage").status_code == 409
    assert client.get(f"/api/cases/{cid}").status_code == 410
    assert any(x["patient_id"] == pid for x in client.get("/api/privacy/requests", headers=as_role("admin")).json())

    # only the data protection officer can erase
    assert client.delete(f"/api/patients/{pid}").status_code == 403
    r = client.delete(f"/api/patients/{pid}", headers=as_role("admin"))
    assert r.status_code == 200 and r.json()["files"] == 1 and r.json()["cases"] == 1
    assert not file_path.exists()
    assert client.get(f"/api/cases/{cid}", headers=as_role("admin")).status_code == 404

    # the audit log keeps a tombstone without personal data, and its chain still verifies
    tomb = [a for a in client.get("/api/audit", params={"action": "patient_data_erased"}).json() if a["patient_id"] == pid]
    assert tomb and "Erase Me" not in json.dumps(tomb)
    assert client.get("/api/audit/verify").json()["ok"] is True


def test_patient_self_withdrawal_with_code(client, as_role):
    body = {"patient": {"name": "Self Withdraw", "age_years": 50}, "consent_given": True, "message": "cough"}
    d = client.post("/api/cases", json=body, headers=as_role("intake")).json()
    code = d["receipt"]["access_code"]
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as anon:
        assert anon.post("/api/public/withdraw", json={"case_id": d["id"], "access_code": "WRONG-CODE"}).status_code == 404
        r = anon.post("/api/public/withdraw", json={"case_id": d["id"], "access_code": code.lower()})
        assert r.status_code == 200 and r.json()["withdrawn"]
    assert d["id"] not in [c["id"] for c in client.get("/api/cases").json()]


def test_audit_chain_detects_tampering(client):
    assert client.get("/api/audit/verify").json()["ok"] is True
    with Session(engine) as s:
        row = s.get(AuditLog, 3)
        original = dict(row.details or {})
        row.details = {**original, "priority": "P4"}
        s.add(row)
        s.commit()
    v = client.get("/api/audit/verify").json()
    assert v["ok"] is False and v["broken_at_id"] == 3
    with Session(engine) as s:  # restore for other tests
        row = s.get(AuditLog, 3)
        row.details = original
        s.add(row)
        s.commit()
    assert client.get("/api/audit/verify").json()["ok"] is True


def test_audit_has_no_free_text_from_overrides(client):
    body = {"patient": {"name": "Reason Privacy", "age_years": 30}, "consent_given": True, "message": "runny nose 2 days"}
    cid = client.post("/api/cases", json=body).json()["id"]
    client.post(f"/api/cases/{cid}/review", json={"action": "override", "final_priority": "P3",
                                                   "reason": "Reason Privacy's mother called, very worried"})
    entries = client.get("/api/audit", params={"case_id": cid}).json()
    assert "mother called" not in json.dumps(entries)
    assert any(e["details"].get("reason_given") for e in entries if e["action"] == "priority_overridden")


def test_redaction_of_indian_identifiers():
    r = redact("Mrs. Sita Devi, UHID: AB12345, mob +91 98765 43210, Aadhaar 2345 6789 0123, PAN ABCDE1234F, "
               "ABHA 12-3456-7890-1234. Platelets 18,000, BP 120/80. Sita ko bukhar.", ["Sita Devi"])
    t = r.text
    for secret in ("Sita", "Devi", "AB12345", "98765", "2345 6789", "ABCDE1234F", "12-3456-7890-1234"):
        assert secret not in t, secret
    assert "18,000" in t and "120/80" in t and "bukhar" in t  # clinical content untouched
    assert r.counts["NAME"] >= 2


def test_gemini_calls_are_redacted_and_logged(monkeypatch, client):
    """External calls carry no patient name and are recorded in the audit log."""
    from app.services.llm import gemini as G
    from app.services.extraction import extractor

    sent: list = []

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps({"symptoms": []})}]}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json["contents"][0]["parts"][0]["text"])
        return Resp()

    monkeypatch.setattr(G.httpx, "post", fake_post)
    monkeypatch.setattr(G.get_settings(), "gemini_api_key", "fake-key")
    monkeypatch.setattr(extractor, "provider_chain", lambda: [G.GeminiProvider()])
    monkeypatch.setattr(extractor.get_settings(), "llm_provider", "gemini")

    body = {"patient": {"name": "Kavita Joshi", "age_years": 44, "phone": "9123456789"}, "consent_given": True,
            "message": "Main Kavita Joshi, mera number 9123456789, seene mein dard hai"}
    cid = client.post("/api/cases", json=body).json()["id"]
    assert sent and all("Kavita" not in t and "Joshi" not in t and "9123456789" not in t for t in sent)
    assert any("seene mein dard" in t for t in sent)  # clinical content still reaches the model
    ext = [a for a in client.get("/api/audit", params={"case_id": cid}).json() if a["action"] == "data_sent_external"]
    assert ext and ext[0]["details"]["calls"][0]["redactions"]["NAME"] >= 1
