"""Evaluation metrics over gold-labelled cases (data/eval/eval_cases.json).

The headline safety metric is UNDER-TRIAGE: how often a patient whose gold priority is urgent
(P1/P2) is suggested as less urgent. Over-triage costs clinician time; under-triage can cost a life.
"""
import json
import statistics
from pathlib import Path
from typing import Any, Optional

from app.config import DATA_DIR

EVAL_DIR = DATA_DIR / "eval"
RESULTS_DIR = EVAL_DIR / "results"
ORDER = ["P1", "P2", "P3", "P4"]
FLAG_TYPES = ["suspicious", "conflicting", "unclear"]


def _rank(p: str) -> int:
    return ORDER.index(p)


def weighted_kappa(gold: list[str], pred: list[str]) -> Optional[float]:
    """Linear-weighted Cohen's kappa for ordinal priorities."""
    n, k = len(gold), len(ORDER)
    if n == 0:
        return None
    obs = [[0.0] * k for _ in range(k)]
    for g, p in zip(gold, pred):
        obs[_rank(g)][_rank(p)] += 1
    row = [sum(r) for r in obs]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = [[abs(i - j) / (k - 1) for j in range(k)] for i in range(k)]
    num = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * row[i] * col[j] / n for i in range(k) for j in range(k))
    return round(1 - num / den, 3) if den else None


def _rate(num: int, den: int) -> Optional[float]:
    return round(num / den, 3) if den else None


def compute(rows: list[dict[str, Any]], with_splits: bool = True) -> dict[str, Any]:
    ok = [r for r in rows if r.get("got")]
    gold = [r["expected"] for r in ok]
    pred = [r["got"] for r in ok]
    diff = [_rank(p) - _rank(g) for g, p in zip(gold, pred)]  # >0: suggested less urgent than gold
    urgent = [r for r in ok if r["expected"] in ("P1", "P2")]
    under_urgent = [r for r in urgent if _rank(r["got"]) > _rank(r["expected"])]

    confusion = {g: {p: 0 for p in ORDER} for g in ORDER}
    for g, p in zip(gold, pred):
        confusion[g][p] += 1

    def group(key: str) -> dict:
        out = {}
        for val in sorted({r[key] for r in ok}):
            sub = [r for r in ok if r[key] == val]
            out[val] = {"n": len(sub),
                        "accuracy": _rate(sum(1 for r in sub if r["got"] == r["expected"]), len(sub)),
                        "under_triage": sum(1 for r in sub if _rank(r["got"]) > _rank(r["expected"]))}
        return out

    exp_flags = [(r, f) for r in ok for f in r["expected_flags"]]
    flag_recall = _rate(sum(1 for r, f in exp_flags if f in r["fired_flags"]), len(exp_flags))
    routine = [r for r in ok if r["expected"] == "P4"]
    false_alarms = [r for r in routine if r["got"] in ("P1", "P2")]

    flag_types = {}
    for t in FLAG_TYPES:
        tp = sum(1 for r in ok if t in r["expected_flag_types"] and t in r["detected_flag_types"])
        fn = sum(1 for r in ok if t in r["expected_flag_types"] and t not in r["detected_flag_types"])
        fp = sum(1 for r in ok if t not in r["expected_flag_types"] and t in r["detected_flag_types"])
        flag_types[t] = {"tp": tp, "fn": fn, "fp": fp, "recall": _rate(tp, tp + fn), "precision": _rate(tp, tp + fp)}

    lat = [r["latency_ms"] for r in ok if r.get("latency_ms") is not None]
    ext = [r["extraction_ms"] for r in ok if r.get("extraction_ms") is not None]

    def pctl(xs, q):
        if not xs:
            return None
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]

    misses = [{"id": r["id"], "category": r["category"], "language": r["language"], "expected": r["expected"], "got": r["got"],
               "direction": "under" if _rank(r["got"]) > _rank(r["expected"]) else "over",
               "reasons": r.get("reasons", [])[:2], "note": r.get("note")}
              for r in ok if r["got"] != r["expected"]]
    misses.sort(key=lambda m: (m["direction"] != "under", m["id"]))

    return {
        "n": len(rows), "scored": len(ok), "errors": len(rows) - len(ok),
        "accuracy": _rate(sum(1 for d in diff if d == 0), len(ok)),
        "within_one": _rate(sum(1 for d in diff if abs(d) <= 1), len(ok)),
        "under_triage": _rate(sum(1 for d in diff if d > 0), len(ok)),
        "under_triage_urgent": _rate(len(under_urgent), len(urgent)),
        "urgent_cases": len(urgent),
        "severe_under_triage": sum(1 for d in diff if d >= 2),
        "over_triage": _rate(sum(1 for d in diff if d < 0), len(ok)),
        "weighted_kappa": weighted_kappa(gold, pred),
        "confusion": confusion,
        "by_category": group("category"),
        "by_language": group("language"),
        "red_flag_recall": flag_recall,
        "false_alarms_on_routine": len(false_alarms),
        "routine_cases": len(routine),
        "flag_types": flag_types,
        "latency_ms": {"mean": round(statistics.mean(lat)) if lat else None, "p50": pctl(lat, 0.5), "p95": pctl(lat, 0.95)},
        "extraction_ms": {"mean": round(statistics.mean(ext)) if ext else None, "p50": pctl(ext, 0.5), "p95": pctl(ext, 0.95)},
        "fallbacks": sum(1 for r in ok if r.get("fallback_used")),
        "misses": misses,
        "by_split": ({sp: {k: v for k, v in compute([r for r in rows if r.get("split") == sp], with_splits=False).items()
                           if k in ("n", "accuracy", "within_one", "under_triage_urgent", "urgent_cases", "severe_under_triage",
                                    "over_triage", "weighted_kappa", "red_flag_recall")}
                      for sp in sorted({r.get("split", "dev") for r in rows})} if with_splits else None),
        "nurse_baseline": _nurse_baseline(ok) if with_splits else None,
    }


def _nurse_baseline(ok: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Real-data sets (KTAS) carry the triage nurse's own decision: score it exactly like the system."""
    rows = [{**r, "got": r["nurse"], "fired_flags": [], "detected_flag_types": []} for r in ok if r.get("nurse")]
    if not rows:
        return None
    m = compute(rows, with_splits=False)
    return {k: m[k] for k in ("n", "accuracy", "within_one", "under_triage_urgent", "urgent_cases",
                              "severe_under_triage", "over_triage", "weighted_kappa", "confusion")}


def load_results() -> list[dict[str, Any]]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(RESULTS_DIR.glob("*.json")):
        try:
            out.append(json.loads(Path(p).read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out
