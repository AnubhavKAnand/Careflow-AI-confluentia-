"""Import the public KTAS emergency-department triage dataset as a REAL-DATA evaluation set.

Dataset: Moon et al., "Emergency Service - Triage Application" (Kaggle / figshare, 1,267 adult ED visits,
two Korean EDs, 2016-2017), file `data.csv`. Each row has the patient's chief complaint, vital signs,
the triage nurse's KTAS level (KTAS_RN) and an expert panel's KTAS level (KTAS_expert).

We use:
  input  : sex, age, chief complaint, injury yes/no, pain score, mental state, SBP, DBP, HR, RR, BT, SpO2
  label  : KTAS_expert (ground truth)          -> 1 = P1, 2 = P2, 3 = P3, 4-5 = P4
  baseline: KTAS_RN (what the nurse decided)   -> same mapping, stored as `nurse_priority`
  never  : diagnosis, disposition, length of stay, mistriage, error group (outcomes would leak the answer)

Usage (from backend/):
    python -m scripts.import_ktas path/to/data.csv                  # all usable rows
    python -m scripts.import_ktas path/to/data.csv --sample 150     # stratified sample, for the slow model
    # a second, disjoint sample that was never looked at while fixing things:
    python -m scripts.import_ktas data.csv --sample 150 --seed 7 --split ktas-test \
        --exclude data/eval/ktas_cases.json --out data/eval/ktas_test.json
Writes data/eval/ktas_cases.json. Then:
    python -m scripts.run_eval --cases data/eval/ktas_cases.json --name ktas-rules
    python -m scripts.run_eval --cases data/eval/ktas_cases.json --provider ollama --name ktas-ollama
"""
import argparse
import csv
import hashlib
import io
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

BACKEND = Path(__file__).resolve().parent.parent
OUT = BACKEND / "data" / "eval" / "ktas_cases.json"

MISSING = {"", "??", "#BOŞ!", "#BOS!", "#NULL!", "NA", "nan"}
KTAS_TO_P = {1: "P1", 2: "P2", 3: "P3", 4: "P4", 5: "P4"}
MENTAL_TO_ACVPU = {1: "A", 2: "V", 3: "P", 4: "U"}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if s in MISSING:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None else None


def _col(row: dict, *names: str) -> Any:
    low = {k.strip().lower(): v for k, v in row.items() if k}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def row_to_case(row: dict, idx: int) -> Optional[dict]:
    expert = _int(_col(row, "KTAS_expert"))
    nurse = _int(_col(row, "KTAS_RN"))
    complaint = (str(_col(row, "Chief_complain") or "")).strip()
    if expert not in KTAS_TO_P or not complaint or complaint in MISSING:
        return None

    sex_code = _int(_col(row, "Sex"))
    sex = {1: "female", 2: "male"}.get(sex_code)
    age = _int(_col(row, "Age"))
    injury = _int(_col(row, "Injury")) == 2
    pain = _int(_col(row, "Pain")) == 1
    nrs = _int(_col(row, "NRS_pain"))
    mental = MENTAL_TO_ACVPU.get(_int(_col(row, "Mental")) or 0)

    vitals: dict[str, Any] = {}
    for key, col, lo, hi in (("systolic_bp", "SBP", 40, 300), ("diastolic_bp", "DBP", 20, 200), ("pulse", "HR", 20, 250),
                             ("resp_rate", "RR", 4, 70), ("temperature_c", "BT", 30, 45), ("spo2", "Saturation", 50, 100)):
        v = _num(_col(row, col))
        if v is not None and lo <= v <= hi:
            vitals[key] = v
    if mental:
        vitals["consciousness"] = mental

    # The message is what a patient / intake desk would type: the complaint plus what the patient reports.
    parts = [complaint[0].upper() + complaint[1:] + "."]
    if injury:
        parts.append("Came after an injury.")
    if pain and nrs is not None and 0 < nrs <= 10:
        parts.append(f"Pain {nrs}/10.")
    message = " ".join(parts)

    return {
        "id": f"ktas{idx:04d}",
        "split": "ktas-real",
        "category": "real-ed",
        "language": "en",
        "expected_priority": KTAS_TO_P[expert],
        "nurse_priority": KTAS_TO_P.get(nurse) if nurse else None,
        "ktas_expert": expert,
        "ktas_rn": nurse,
        "expected_flags": [],
        "expected_flag_types": [],
        "note": f"KTAS expert {expert}, nurse {nurse}. Real ED visit (Moon et al.).",
        "files": [],
        "case": {
            "patient": {"name": f"KTAS {idx}", "age_years": age, "sex": sex, "preferred_language": "en"},
            "consent_given": True,
            "message": message,
            "vitals": vitals,
        },
    }


def stratified(cases: list[dict], n: int, seed: int) -> list[dict]:
    """Keep every P1 (rare, and the ones that matter most), sample the rest proportionally."""
    rng = random.Random(seed)
    by: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        by[c["expected_priority"]].append(c)
    out = list(by.get("P1", []))
    rest = [c for p in ("P2", "P3", "P4") for c in by.get(p, [])]
    left = max(0, n - len(out))
    total = len(rest) or 1
    for p in ("P2", "P3", "P4"):
        pool = by.get(p, [])
        k = min(len(pool), round(left * len(pool) / total))
        out += rng.sample(pool, k)
    return sorted(out, key=lambda c: c["id"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--sample", type=int, help="stratified sample size (all P1 kept)")
    ap.add_argument("--seed", type=int, default=24)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--exclude", type=Path, action="append", default=[],
                    help="case file(s) whose ids must not be reused (keeps a test sample disjoint from the dev sample)")
    ap.add_argument("--split", default="ktas-real", help="split name stored on each case, e.g. ktas-dev / ktas-test")
    args = ap.parse_args()

    text = _read_text(args.csv)
    delim = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    cases = [c for i, r in enumerate(rows, 1) if (c := row_to_case(r, i))]
    skipped = len(rows) - len(cases)
    used = {c["id"] for f in args.exclude for c in json.loads(f.read_text(encoding="utf-8"))["cases"]}
    if used:
        cases = [c for c in cases if c["id"] not in used]
        print(f"Excluded {len(used)} cases already used in {', '.join(str(f) for f in args.exclude)}.")
    for c in cases:
        c["split"] = args.split
    if args.sample:
        cases = stratified(cases, args.sample, args.seed)

    nurse_under = sum(1 for c in cases if c["nurse_priority"] and c["nurse_priority"] > c["expected_priority"])
    data = {
        "version": "ktas-1",
        "source": "Moon S-H et al. (2019) KTAS triage dataset, 1,267 adult ED visits, Korea. Kaggle: "
                  "'Emergency Service - Triage Application'. Label = KTAS_expert; KTAS 4-5 merged into P4.",
        "csv_sha256": hashlib.sha256(args.csv.read_bytes()).hexdigest(),
        "sample": args.sample, "seed": args.seed, "split": args.split,
        "excluded_files": [f.name for f in args.exclude],
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Read {len(rows)} rows, skipped {skipped} without a usable label or complaint.")
    print(f"Wrote {len(cases)} cases to {args.out}")
    print("Expert priorities:", dict(sorted(Counter(c['expected_priority'] for c in cases).items())))
    print(f"Nurse under-triaged {nurse_under} of {len(cases)} ({nurse_under / max(1, len(cases)):.0%}) against the expert label.")


if __name__ == "__main__":
    main()
