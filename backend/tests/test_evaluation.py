import json
import subprocess
import sys
from pathlib import Path

from app.services.evaluation import compute, weighted_kappa

BACKEND = Path(__file__).resolve().parent.parent


def row(id, exp, got, split="dev", cat="urgent", flags=(), fired=(), types=(), det=()):
    return {"id": id, "split": split, "category": cat, "language": "en", "expected": exp, "got": got,
            "expected_flags": list(flags), "fired_flags": list(fired), "expected_flag_types": list(types),
            "detected_flag_types": list(det), "latency_ms": 100, "extraction_ms": 10}


def test_kappa_bounds():
    assert weighted_kappa(["P1", "P2", "P3", "P4"], ["P1", "P2", "P3", "P4"]) == 1.0
    assert weighted_kappa(["P1", "P4", "P1", "P4"], ["P4", "P1", "P4", "P1"]) < 0


def test_under_triage_is_counted_on_urgent_cases():
    rows = [row("a", "P1", "P1"), row("b", "P1", "P3"), row("c", "P2", "P1"), row("d", "P4", "P3", cat="routine")]
    m = compute(rows)
    assert m["urgent_cases"] == 3 and m["under_triage_urgent"] == round(1 / 3, 3)
    assert m["severe_under_triage"] == 1 and m["over_triage"] == 0.5
    assert m["misses"][0]["id"] == "b" and m["misses"][0]["direction"] == "under"  # under-triage listed first


def test_flag_type_precision_recall_and_splits():
    rows = [row("a", "P3", "P3", types=["suspicious"], det=["suspicious"]),
            row("b", "P3", "P3", types=["suspicious"], det=[]),
            row("c", "P4", "P4", det=["suspicious"], split="holdout")]
    m = compute(rows)
    assert m["flag_types"]["suspicious"] == {"tp": 1, "fn": 1, "fp": 1, "recall": 0.5, "precision": 0.5}
    assert set(m["by_split"]) == {"dev", "holdout"}


def test_eval_runner_end_to_end(tmp_path):
    out = subprocess.run([sys.executable, "-m", "scripts.run_eval", "--only", "e01,n02,i01", "--name", "pytest-run"],
                         cwd=BACKEND, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    f = BACKEND / "data" / "eval" / "results" / "pytest-run.json"
    try:
        r = json.loads(f.read_text())
        assert r["metrics"]["n"] == 3 and r["metrics"]["errors"] == 0
        assert {x["id"] for x in r["rows"]} == {"e01", "n02", "i01"}
    finally:
        f.unlink(missing_ok=True)
