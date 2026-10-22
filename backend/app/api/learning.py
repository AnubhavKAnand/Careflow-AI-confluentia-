"""Shadow-agent status, graduation, mode switch, simulation."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import Actor, require
from app.db import get_session
from app.services.learning import shadow, simulate
from app.services.learning.bandit import MIN_TRAINING, OVER_PENALTY, UNDER_PENALTY

router = APIRouter(prefix="/api/learning", tags=["learning"])


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(shadow|recommend)$")
    force: bool = False  # demo only: switch even if graduation criteria are not met (audited)


class SimIn(BaseModel):
    weeks: int = Field(default=26, ge=4, le=104)
    per_week: int = Field(default=20, ge=5, le=100)
    seed: int = 7


@router.get("/status")
def status(session: Session = Depends(get_session), _: Actor = Depends(require("learning:read"))):
    cfg = shadow.get_config(session)
    m = shadow.metrics(session)
    agent = shadow.live_agent(session)
    weights = {p: agent.top_weights(p, 6) for p in ("P1", "P2")} if agent.n >= MIN_TRAINING else {}
    return {
        "mode": cfg.mode, "changed_at": cfg.changed_at, "changed_by": cfg.changed_by,
        "model": {"trained_on": agent.n, "features": len(agent.names), "min_training": MIN_TRAINING},
        "reward": {"agree": 1, "over_triage_per_level": -OVER_PENALTY, "under_triage_per_level": -UNDER_PENALTY},
        "metrics": m, "graduation": shadow.graduation(m), "top_features": weights,
        "blind_check_share": shadow.BLIND_CHECK_SHARE,
    }


@router.post("/mode")
def set_mode(body: ModeIn, session: Session = Depends(get_session), actor: Actor = Depends(require("learning:manage"))):
    try:
        cfg = shadow.set_mode(session, body.mode, actor.username, force=body.force)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"mode": cfg.mode, "changed_by": cfg.changed_by}


@router.post("/simulate")
def run_simulation(body: SimIn, _: Actor = Depends(require("learning:read"))):
    """Replay synthetic months of shadow learning (nothing is stored)."""
    return simulate.run(body.weeks, body.per_week, body.seed)


@router.post("/bootstrap")
def bootstrap(n: int = 200, session: Session = Depends(get_session), actor: Actor = Depends(require("learning:manage"))):
    """Optional cold start with synthetic examples; they train the model but never count toward graduation."""
    added = shadow.bootstrap(session, min(max(n, 10), 2000))
    return {"added": added}
