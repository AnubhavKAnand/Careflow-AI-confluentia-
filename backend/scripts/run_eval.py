"""Run the gold-labelled evaluation set through the full pipeline and save metrics.

Usage (from backend/):
    python -m scripts.run_eval                       # deterministic rules only (offline baseline)
    python -m scripts.run_eval --provider ollama     # your local small model (Gemini fallback off)
    python -m scripts.run_eval --provider gemini     # Gemini only
    python -m scripts.run_eval --provider configured # whatever backend/.env says

Results go to data/eval/results/<name>.json and appear on the Evaluation page. Each run uses a fresh
temporary database, so your demo data is untouched.
"""
import argparse
import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="rules", choices=["rules", "ollama", "gemini", "configured"])
    ap.add_argument("--name", help="result file name (default: the provider)")
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--cases", help="case file (default data/eval/eval_cases.json; e.g. data/eval/ktas_cases.json)")
    ap.add_argument("--with-ai-questions", action="store_true", help="include small-model follow-up questions in latency")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="careflow-eval-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'eval.db'}"
    os.environ["UPLOAD_DIR"] = str(tmp / "uploads")
    os.environ["DEMO_PASSWORD"] = "eval-run"
    os.environ.setdefault("JWT_SECRET", "eval-run-secret-0123456789abcdef")
    if not args.with_ai_questions:
        os.environ["AI_FOLLOWUPS"] = "false"
    if args.provider != "configured":
        os.environ["LLM_PROVIDER"] = args.provider
        os.environ["LLM_FALLBACK_PROVIDER"] = ""
    sys.path.insert(0, str(BACKEND))

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app
    from app.services.evaluation import RESULTS_DIR, compute

    case_file = (BACKEND / args.cases) if args.cases else (BACKEND / "data" / "eval" / "eval_cases.json")
    data = json.loads(case_file.read_text(encoding="utf-8"))
    cases = data["cases"]
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep]

    rows = []
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        tok = client.post("/api/auth/login", json={"username": "desk.ravi", "password": "eval-run"}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        print(f"Evaluating {len(cases)} cases with provider={args.provider} {health['providers']}\n")
        for c in cases:
            t0 = time.perf_counter()
            if c["files"]:
                ups = [("files", (Path(f).name, (BACKEND / "data" / f).read_bytes())) for f in c["files"]]
                r = client.post("/api/cases/intake", data={"payload": json.dumps(c["case"])}, files=ups, headers=h)
            else:
                r = client.post("/api/cases/intake", data={"payload": json.dumps(c["case"])}, headers=h)
            ms = int((time.perf_counter() - t0) * 1000)
            row = {"id": c["id"], "split": c.get("split", "dev"), "category": c["category"], "language": c["language"], "expected": c["expected_priority"],
                   "expected_flags": c["expected_flags"], "expected_flag_types": c["expected_flag_types"], "note": c["note"],
                   "latency_ms": ms}
            if c.get("nurse_priority"):
                row["nurse"] = c["nurse_priority"]
            if r.status_code != 201:
                row["error"] = f"{r.status_code}: {r.text[:200]}"
                rows.append(row)
                print(f"  ERROR {c['id']}: {row['error']}")
                continue
            d = r.json()
            tri = d["triage"]
            flags = (tri.get("validation") or {}).get("flags") or []
            row.update({
                "got": tri["priority"],
                "fired_flags": [f["rule_id"] for f in tri["red_flags"]],
                "detected_flag_types": sorted({f["type"] for f in flags if f["severity"] != "info" and f["type"] != "missing"}),
                "reasons": [x["text"][:140] for x in tri["reasons"]],
                "extraction_ms": d.get("extraction_latency_ms"),
                "provider": d.get("extraction_provider"),
                "fallback_used": (d.get("extraction") or {}).get("fallback_used", False),
                "symptoms": [f"{'NO ' if s.get('negated') else ''}{s.get('canonical_id') or s.get('name')} "
                             f"[{(s.get('evidence') or {}).get('origin', '?')}: {((s.get('evidence') or {}).get('quote') or '')[:50]}]"
                             for s in (d.get("extraction") or {}).get("symptoms", [])],
                "signals": [u.get("signal") for u in (d.get("extraction") or {}).get("urgency_signals", [])],
                "uncertainties": (d.get("extraction") or {}).get("uncertainties", [])[:6],
            })
            rows.append(row)
            mark = "OK  " if row["got"] == row["expected"] else ("UNDER" if "P1P2P3P4".index(row["got"]) > "P1P2P3P4".index(row["expected"]) else "over")
            print(f"  {mark} {c['id']:<26} expected {row['expected']} got {row['got']}  {ms:>6} ms  [{row['provider']}]")

    m = compute(rows)
    result = {
        "name": args.name or args.provider,
        "provider": args.provider,
        "models": sorted({r.get("provider") for r in rows if r.get("provider")}),
        "engine_version": get_settings().engine_version,
        "dataset_version": data["version"],
        "case_file": case_file.name,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "machine": {"platform": platform.platform(), "python": platform.python_version(), "cpus": os.cpu_count()},
        "metrics": m,
        "rows": rows,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{result['name']}.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    pct = lambda x: "n/a" if x is None else f"{x * 100:.0f}%"  # noqa: E731
    print(f"\nExact priority {pct(m['accuracy'])}, within one level {pct(m['within_one'])}, weighted kappa {m['weighted_kappa']}")
    print(f"Under-triage of urgent (P1/P2) cases: {pct(m['under_triage_urgent'])} of {m['urgent_cases']}; "
          f"severe (2+ levels): {m['severe_under_triage']}; over-triage {pct(m['over_triage'])}")
    print(f"Red-flag recall {pct(m['red_flag_recall'])}; false alarms on routine cases {m['false_alarms_on_routine']}/{m['routine_cases']}")
    for t, v in m["flag_types"].items():
        print(f"  {t:<12} recall {pct(v['recall'])} precision {pct(v['precision'])}")
    print(f"Latency per case: mean {m['latency_ms']['mean']} ms, p95 {m['latency_ms']['p95']} ms")
    nb = m.get("nurse_baseline")
    if nb:
        print(f"Nurse baseline on the same cases: exact {pct(nb['accuracy'])}, urgent under-triage {pct(nb['under_triage_urgent'])} "
              f"of {nb['urgent_cases']}, severe {nb['severe_under_triage']}, kappa {nb['weighted_kappa']}")
    for sp, v in (m.get("by_split") or {}).items():
        print(f"  {sp:<8} n={v['n']:<3} exact {pct(v['accuracy'])}, urgent under-triage {pct(v['under_triage_urgent'])} of {v['urgent_cases']}, kappa {v['weighted_kappa']}")
    print(f"\nSaved {out.relative_to(BACKEND)}")


if __name__ == "__main__":
    main()
