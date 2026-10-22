"""Phase 2 synthetic cases (reports) end to end through the multipart intake."""
import json

import pytest

from app.services.ingestion.documents import tesseract_available
from tests.conftest import BACKEND

pytestmark = pytest.mark.skipif(not tesseract_available(), reason="tesseract not installed")


def _post(client, c):
    uploads = [("files", (f.split("/")[-1], (BACKEND / "data" / f).read_bytes())) for f in c.get("files", [])]
    return client.post("/api/cases/intake", data={"payload": json.dumps(c["case"])}, files=uploads)


@pytest.mark.parametrize("idx", range(5))
def test_report_case_priority(client, synthetic_cases2, idx):
    c = synthetic_cases2[idx]
    r = _post(client, c)
    assert r.status_code == 201, r.text
    tri = r.json()["triage"]
    assert tri["priority"] == c["expected_priority"], f"{c['id']}: {tri['reasons']}"
    assert set(c["expected_flags"]) <= {f["rule_id"] for f in tri["red_flags"]}


def test_lab_evidence_points_at_report_line(client, synthetic_cases2):
    d = _post(client, synthetic_cases2[0]).json()
    plt = next(lab for lab in d["extraction"]["labs"] if lab["canonical_id"] == "platelets")
    ev = plt["evidence"]
    assert ev["locator"]["page"] == 1 and len(ev["locator"]["bbox"]) == 4
    report = next(s for s in d["sources"] if s["id"] == ev["source_id"])
    assert report["original_text"][ev["start"]:ev["end"]] == ev["quote"]


def test_report_age_conflict_flagged(client, synthetic_cases2):
    d = _post(client, synthetic_cases2[4]).json()
    assert any(x["field"] == "age_years" for x in d["extraction"]["discrepancies"])


def test_add_report_to_existing_case_retriages(client, sample_reports):
    body = {"patient": {"name": "Add Later", "age_years": 30, "sex": "male"}, "consent_given": True,
            "message": "Fever for 3 days."}
    d = client.post("/api/cases", json=body).json()
    assert d["triage"]["priority"] in ("P3", "P4")
    r = client.post(f"/api/cases/{d['id']}/sources",
                    files=[("files", ("cbc.png", (sample_reports / "cbc_dengue.png").read_bytes(), "image/png"))])
    assert r.status_code == 200 and r.json()["triage"]["priority"] == "P1"
