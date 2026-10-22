"""Shadow triage agent: a full-information contextual bandit with an asymmetric reward.

Actions are the four priorities. The reward for choosing priority `a` when the clinician decided
`final`:
    same priority                         +1
    more urgent than the clinician (over)  -1 per level
    less urgent than the clinician (under) -5 per level
Under-triage is the dangerous error, so the agent learns to be cautious when unsure. (The 6-month
simulation was used to pick 5: at 10 the agent over-triaged whole patient groups, e.g. elderly fever
to P1; at 5 it still refuses to downgrade young chest pain, where clinicians say P2 30% of the time.)

Because the clinician reveals the correct priority, every action's reward is known for every
reviewed case, not only the action taken ("full-information" feedback). That makes it a ridge
regression of expected reward per action on the case features, with one shared design matrix:
    A = lambda*I + sum x x^T,   theta_a = A^-1 sum r(a, final) x
The suggestion is the action with the highest expected reward. Uncertainty
sqrt(x^T A^-1 x) says how unlike past cases this one is; the agent abstains when it is too
novel or when it has seen too few cases.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.schemas.triage import PRIORITY_ORDER

ACTIONS = PRIORITY_ORDER  # ["P1", "P2", "P3", "P4"]
UNDER_PENALTY = 5.0
OVER_PENALTY = 1.0
RIDGE = 1.0
MIN_TRAINING = 30  # below this the agent abstains ("still learning")
MAX_NOVELTY = 0.9  # uncertainty width above which a case counts as unlike anything seen


def reward(action: str, final: str) -> float:
    diff = ACTIONS.index(action) - ACTIONS.index(final)  # >0: action less urgent than the clinician
    if diff == 0:
        return 1.0
    return -UNDER_PENALTY * diff if diff > 0 else -OVER_PENALTY * (-diff)


@dataclass
class Prediction:
    predicted: Optional[str]
    scores: dict[str, float]
    confidence: float
    novelty: float
    abstained: bool
    abstain_reason: Optional[str] = None
    explanation: list[dict] = field(default_factory=list)


class Agent:
    def __init__(self, names: list[str]):
        self.names = names
        self.index = {n: i for i, n in enumerate(names)}
        d = len(names)
        self.A = RIDGE * np.eye(d)
        self.B = np.zeros((d, len(ACTIONS)))
        self.n = 0
        self._theta: Optional[np.ndarray] = None
        self._A_inv: Optional[np.ndarray] = None

    def vector(self, feats: dict[str, float]) -> np.ndarray:
        x = np.zeros(len(self.names))
        for k, v in feats.items():
            i = self.index.get(k)
            if i is not None:
                x[i] = v
        return x

    def update(self, feats: dict[str, float], final: str) -> None:
        x = self.vector(feats)
        self.A += np.outer(x, x)
        self.B += np.outer(x, [reward(a, final) for a in ACTIONS])
        self.n += 1
        self._theta = self._A_inv = None

    def _fit(self) -> None:
        if self._theta is None:
            self._A_inv = np.linalg.inv(self.A)
            self._theta = self._A_inv @ self.B  # (d, 4)

    def predict(self, feats: dict[str, float]) -> Prediction:
        x = self.vector(feats)
        self._fit()
        scores = x @ self._theta
        width = float(np.sqrt(max(0.0, x @ self._A_inv @ x)))
        order = np.argsort(-scores)
        best, second = int(order[0]), int(order[1])
        margin = float(scores[best] - scores[second])
        confidence = round(margin / (margin + 2 * width + 1e-9), 3)
        out = Prediction(predicted=ACTIONS[best], scores={a: round(float(s), 3) for a, s in zip(ACTIONS, scores)},
                         confidence=confidence, novelty=round(width, 3), abstained=False)
        if self.n < MIN_TRAINING:
            out.abstained, out.abstain_reason = True, f"Still learning ({self.n} of {MIN_TRAINING} reviewed cases)."
        elif width > MAX_NOVELTY:
            out.abstained, out.abstain_reason = True, "This case is unlike the cases reviewed so far."
        out.explanation = self.explain(x, best, second)
        if out.abstained:
            out.predicted = None
        return out

    def explain(self, x: np.ndarray, best: int, second: int, k: int = 4) -> list[dict]:
        """Features that most separate the suggested priority from the runner-up."""
        contrib = (self._theta[:, best] - self._theta[:, second]) * x
        idx = [i for i in np.argsort(-np.abs(contrib)) if x[i] != 0 and not self.names[i].startswith("bias")][:k]
        from app.services.learning.features import label

        return [{"feature": self.names[i], "label": label(self.names[i]), "weight": round(float(contrib[i]), 3)} for i in idx]

    def top_weights(self, action: str = "P1", k: int = 8) -> list[dict]:
        """Features that most raise the expected reward of choosing `action` versus the average action."""
        self._fit()
        a = ACTIONS.index(action)
        rel = self._theta[:, a] - self._theta.mean(axis=1)
        from app.services.learning.features import label

        idx = [i for i in np.argsort(-rel) if not self.names[i].startswith(("bias", "engine:"))][:k]
        return [{"feature": self.names[i], "label": label(self.names[i]), "weight": round(float(rel[i]), 3)} for i in idx]
