"""Developer tool: capture real API responses for the frontend page tests (frontend/src/__tests__/fixtures.json).

Usage (from backend/, after `python -m scripts.seed_db --reset --bootstrap 300`):
    python -m scripts.capture_ui_fixtures
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import app.services.learning.shadow as sh  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

OUT = BACKEND.parent / "frontend" / "src" / "__tests__" / "fixtures.json"


def main() -> None:
    c = TestClient(app)

    def tok(u):
        r = c.post("/api/auth/login", json={"username": u, "password": get_settings().demo_password}).json()
        return {"Authorization": "Bearer " + r["access_token"]}, r["user"]

    fx = {"health": c.get("/api/health").json()}
    H = {}
    for role, u in (("doctor", "dr.mehra"), ("intake", "desk.ravi"), ("admin", "admin")):
        H[role], fx[f"user_{role}"] = tok(u)
    for cid in (2, 3, 9):
        d = c.get(f"/api/cases/{cid}", headers=H["doctor"]).json()
        c.post(f"/api/cases/{cid}/review", json={"action": "approve", "final_priority": d["triage"]["priority"]}, headers=H["doctor"])
    for role in ("doctor", "intake", "admin"):
        h = H[role]
        fx[f"list_{role}"] = c.get("/api/cases", headers=h).json()
        for cid in (1, 11, 14, 15):
            fx[f"case{cid}_{role}"] = c.get(f"/api/cases/{cid}", headers=h).json()
        if role != "intake":
            fx[f"audit_{role}"] = c.get("/api/audit", params={"limit": 50}, headers=h).json()
            fx[f"learning_{role}"] = c.get("/api/learning/status", headers=h).json()
    fx["evaluation"] = c.get("/api/evaluation", headers=H["doctor"]).json()
    fx["similar1"] = c.get("/api/cases/1/similar", headers=H["doctor"]).json()
    fx["simulation"] = c.post("/api/learning/simulate", json={"weeks": 26, "per_week": 20, "seed": 7}, headers=H["doctor"]).json()
    c.post("/api/learning/mode", json={"mode": "recommend", "force": True}, headers=H["doctor"])
    sh._blind = lambda cid: False
    body = {"patient": {"name": "Rec Mode", "age_years": 27, "sex": "female"}, "consent_given": True,
            "message": "7 months pregnant, headache since morning"}
    fx["case_rec_doctor"] = c.post("/api/cases", json=body, headers=H["doctor"]).json()
    c.post("/api/learning/mode", json={"mode": "shadow"}, headers=H["doctor"])
    c.post("/api/cases/6/withdraw", json={"reason": "asked at desk"}, headers=H["intake"])
    fx["requests"] = c.get("/api/privacy/requests", headers=H["admin"]).json()
    fx["verify"] = c.get("/api/audit/verify", headers=H["admin"]).json()
    OUT.write_text(json.dumps(fx), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
