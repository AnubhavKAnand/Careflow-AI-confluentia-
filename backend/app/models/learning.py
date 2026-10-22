from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.patient import utcnow


class AgentConfig(SQLModel, table=True):
    """Single row: which mode the learned agent runs in, and who signed off graduation."""

    id: Optional[int] = Field(default=None, primary_key=True)
    mode: str = "shadow"  # shadow | recommend
    changed_at: datetime = Field(default_factory=utcnow)
    changed_by: Optional[str] = None
    graduation_snapshot: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


class ShadowPrediction(SQLModel, table=True):
    """What the agent would have said for a case, recorded before the clinician decides.

    Reviewed rows ARE the training set: the model is recomputed from them, so erasing a patient's
    rows removes their influence from the model too."""

    id: Optional[int] = Field(default=None, primary_key=True)
    # None for synthetic pre-training examples (no real patient behind them)
    case_id: Optional[int] = Field(default=None, foreign_key="case.id", index=True, unique=True)
    synthetic: bool = False
    features: dict[str, float] = Field(sa_column=Column(JSON))  # sparse: only non-zero features
    engine_priority: str  # rules + NEWS2 suggestion at the time
    predicted: Optional[str] = None  # None when the agent abstained
    scores: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    confidence: float = 0.0
    abstained: bool = False
    mode: str = "shadow"  # mode at prediction time
    hidden: bool = True  # whether the clinician could see it (always hidden in shadow mode)
    model_version: int = 0
    explanation: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    final_priority: Optional[str] = None  # filled when the clinician finalizes
    reward: Optional[float] = None
    created_at: datetime = Field(default_factory=utcnow)
    reviewed_at: Optional[datetime] = None
