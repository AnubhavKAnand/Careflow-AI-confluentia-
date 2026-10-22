"""Load the synthetic demo cases through the full pipeline and print a priority check.

Usage (from backend/):  python -m scripts.seed_db [--reset] [--file data/synthetic_cases/phase2_cases.json ...]
Run `python -m scripts.make_samples` first so the sample report files exist.
Uses whatever LLM_PROVIDER is configured in backend/.env (set LLM_PROVIDER=rules to run offline).
"""
import argparse
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", help="case file(s); default: all data/synthetic_cases/*.json")
    ap.add_argument("--reset", action="store_true", help="delete the SQLite database first")
    ap.add_argument("--bootstrap", type=int, default=0, help="also pre-train the shadow agent on N synthetic examples")
    args = ap.parse_args()

    url = get_settings().database_url
    if args.reset and url.startswith("sqlite:///"):
        db = Path(url.removeprefix("sqlite:///"))
        db = db if db.is_absolute() else BACKEND / db
        db.unlink(missing_ok=True)
        print(f"Removed {db}")

    from app.main import app

    files = args.file or sorted(str(p) for p in (BACKEND / "data" / "synthetic_cases").glob("*.json"))
    cases = [c for f in files for c in json.loads(Path(f).read_text(encoding="utf-8"))]
    ok = 0
    with TestClient(app) as client:
        print(f"Providers: {client.get('/api/health').json()['providers']}\n")
        tok = client.post("/api/auth/login", json={"username": "desk.ravi", "password": get_settings().demo_password})
        if tok.status_code != 200:
            sys.exit(f"Login as desk.ravi failed ({tok.status_code}). Check DEMO_PASSWORD in backend/.env.")
        auth = {"Authorization": f"Bearer {tok.json()['access_token']}"}
        for c in cases:
            t0 = time.perf_counter()
            headers = auth
            if c.get("files"):
                uploads = [("files", (Path(f).name, (BACKEND / "data" / f).read_bytes())) for f in c["files"]]
                r = client.post("/api/cases/intake", data={"payload": json.dumps(c["case"])}, files=uploads, headers=headers)
            else:
                r = client.post("/api/cases", json=c["case"], headers=headers)
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 201:
                print(f"  ERROR {c['id']}: {r.status_code} {r.text[:200]}")
                continue
            d = r.json()
            got = d["triage"]["priority"]
            match = got == c.get("expected_priority")
            ok += match
            flags = ", ".join(f["rule_id"] for f in d["triage"]["red_flags"]) or "-"
            print(f"  {'OK ' if match else 'DIFF'} {c['id']:<26} expected {c.get('expected_priority')}  got {got}  "
                  f"[{d['extraction_provider']}, {ms} ms]  flags: {flags}")
        if args.bootstrap:
            doc = client.post("/api/auth/login", json={"username": "dr.mehra", "password": get_settings().demo_password}).json()
            r = client.post("/api/learning/bootstrap", params={"n": args.bootstrap},
                            headers={"Authorization": f"Bearer {doc['access_token']}"})
            print(f"\nShadow agent pre-trained on {r.json().get('added')} synthetic examples (not counted toward graduation).")
    print(f"\n{ok}/{len(cases)} match the expected priority.")


if __name__ == "__main__":
    main()
