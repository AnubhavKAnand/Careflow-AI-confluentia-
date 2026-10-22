"""Stored evaluation results (produced by scripts/run_eval.py)."""
import json

from fastapi import APIRouter, Depends

from app.api.deps import Actor, require
from app.services.evaluation import EVAL_DIR, load_results

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("")
def results(_: Actor = Depends(require("evaluation:read"))):
    data = json.loads((EVAL_DIR / "eval_cases.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    return {
        "dataset": {"version": data["version"], "description": data["description"], "n": len(cases),
                    "by_split": {s: sum(1 for c in cases if c.get("split") == s) for s in ("dev", "holdout")},
                    "by_category": {k: sum(1 for c in cases if c["category"] == k) for k in sorted({c["category"] for c in cases})}},
        "results": [{k: v for k, v in r.items() if k != "rows"} | {"rows": r.get("rows", [])} for r in load_results()],
    }
