from fastapi.testclient import TestClient

from app.main import app
from app.services.privacy.auth import hash_password, verify_password

CASE = {"patient": {"name": "Auth Test", "age_years": 40, "sex": "male", "phone": "9876543210"},
        "consent_given": True, "message": "Chest pain since 30 minutes"}


def test_password_hashing():
    h = hash_password("s3cret")
    assert h.startswith("pbkdf2_sha256$") and verify_password("s3cret", h) and not verify_password("nope", h)
    assert hash_password("s3cret") != h  # salted


def test_requests_without_token_are_rejected():
    with TestClient(app) as anon:
        assert anon.get("/api/cases").status_code == 401
        assert anon.get("/api/cases", headers={"Authorization": "Bearer forged.token.here"}).status_code == 401
        assert anon.get("/api/health").status_code == 200  # health stays public


def test_login_errors_and_lockout():
    with TestClient(app) as anon:
        assert anon.post("/api/auth/login", json={"username": "sr.thomas", "password": "wrong"}).status_code == 401
        for _ in range(5):
            anon.post("/api/auth/login", json={"username": "lock.me", "password": "x"})
        assert anon.post("/api/auth/login", json={"username": "lock.me", "password": "x"}).status_code == 429


def test_me_reports_role_permissions(client, as_role):
    me = client.get("/api/auth/me").json()
    assert me["role"] == "doctor" and "triage:finalize" in me["permissions"]
    intake = client.get("/api/auth/me", headers=as_role("intake")).json()
    assert "triage:finalize" not in intake["permissions"] and "case:create" in intake["permissions"]


def test_role_shaped_case_view(client, as_role):
    d = client.post("/api/cases", json=CASE, headers=as_role("intake")).json()
    cid = d["id"]
    # creation response carries the consent receipt
    assert d["receipt"]["access_code"] and d["receipt"]["case_id"] == cid

    doc = client.get(f"/api/cases/{cid}").json()
    assert doc["note"] is not None and doc["sources"][0]["original_text"]
    assert "phone" not in doc["patient"] and "access_code" not in doc["patient"]

    desk = client.get(f"/api/cases/{cid}", headers=as_role("intake")).json()
    assert desk["note"] is None  # intake desk cannot read the clinical note
    assert desk["patient"]["phone"] == "9876543210"  # but sees contact details

    dpo = client.get(f"/api/cases/{cid}", headers=as_role("admin")).json()
    assert dpo["note"] is None and dpo["extraction"] is None
    assert all(s["original_text"] == "" for s in dpo["sources"])  # no raw clinical text for the admin
    assert dpo["triage"]["priority"] == doc["triage"]["priority"]


def test_permission_matrix_enforced(client, as_role):
    cid = client.post("/api/cases", json=CASE).json()["id"]
    assert client.post(f"/api/cases/{cid}/review", json={"action": "approve", "final_priority": "P2"},
                       headers=as_role("admin")).status_code == 403
    assert client.put(f"/api/cases/{cid}/note", json={"content": "x"}, headers=as_role("intake")).status_code == 403
    assert client.post("/api/cases", json=CASE, headers=as_role("admin")).status_code == 403
    assert client.get("/api/audit", headers=as_role("intake")).status_code == 403
    assert client.get("/api/auth/users", headers=as_role("admin")).status_code == 200
    assert client.get("/api/auth/users").status_code == 403
