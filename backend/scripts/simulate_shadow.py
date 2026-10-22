"""Print a 6-month shadow-learning simulation (no database needed).

Usage (from backend/):  python -m scripts.simulate_shadow [--weeks 26] [--per-week 20] [--seed 7]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.learning.simulate import run  # noqa: E402


def pct(x):
    return "  -  " if x is None else f"{x * 100:4.0f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=26)
    ap.add_argument("--per-week", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    r = run(a.weeks, a.per_week, a.seed)
    print("week  agent-agrees  rules-agree  coverage  agent-under-triage")
    for c in r["curve"]:
        print(f"{c['week']:>4}  {pct(c['agent_agreement']):>12}  {pct(c['rules_agreement']):>11}  {pct(c['coverage']):>8}  {pct(c['agent_under_triage']):>18}")
    f = r["final"]
    print(f"\nLast 100 answered cases: agent agrees {pct(f['agent_agreement_last100'])}, rules {pct(f['rules_agreement_last100'])}")
    print(f"Under-triage of P1/P2: agent {pct(f['agent_under_triage_last100'])}, rules {pct(f['rules_under_triage_last100'])}")
    print(f"Mean reward: agent {f['mean_reward_agent']}, rules {f['mean_reward_rules']}")
    print("\nLocal judgement the rules miss (last 15 cases of each):")
    for k, v in r["patterns"].items():
        print(f"  {k:<20} agent says {v['agent_suggests']}, agent right {pct(v['agent'])}, rules right {pct(v['rules'])}")


if __name__ == "__main__":
    main()
