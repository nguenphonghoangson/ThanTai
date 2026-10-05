"""Scoring types. A score is a relative sampling weight (1.0 = neutral), not a probability."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date
from typing import Dict, List, Optional, Protocol

import numpy as np

from app.analysis.features.models import FeatureSet
from app.domain.games import LotteryGameConfig

COMPONENTS = ("frequency", "recent_frequency", "gap", "pair", "historical")


class GapMode:
    # Both are hypotheses for backtesting; neither is assumed to work.
    OVERDUE = "overdue"  # longer-than-usual gap scores higher
    RECENCY = "recency"  # shorter-than-usual gap scores higher
    ALL = (OVERDUE, RECENCY)


@dataclass(frozen=True)
class ScoringWeights:
    frequency: float = 0.0
    recent_frequency: float = 0.0
    gap: float = 0.0
    pair: float = 0.0
    historical: float = 0.0

    def __post_init__(self) -> None:
        if any(v < 0 for v in self.as_dict().values()):
            raise ValueError("weights must be non-negative")

    def as_dict(self) -> Dict[str, float]:
        return {name: float(getattr(self, name)) for name in COMPONENTS}

    @property
    def total(self) -> float:
        return sum(self.as_dict().values())

    def normalized(self) -> "ScoringWeights":
        """Weights are relative; they are rescaled to sum to 1 before use."""
        total = self.total
        if total == 0:
            return self
        return ScoringWeights(**{k: v / total for k, v in self.as_dict().items()})


@dataclass(frozen=True)
class ScoringConfig:
    strategy: str
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    # Size of the deviation from neutral: score = 1 + intensity * Σ weight·z.
    intensity: float = 0.25
    gap_mode: str = GapMode.OVERDUE
    # Floor so every number keeps a non-zero sampling weight.
    min_score: float = 0.05
    uniform: bool = False  # random baseline: every number scores exactly 1.0

    def __post_init__(self) -> None:
        if self.gap_mode not in GapMode.ALL:
            raise ValueError(f"gap_mode must be one of {GapMode.ALL}")
        if self.intensity < 0 or not 0 < self.min_score <= 1:
            raise ValueError("intensity must be >= 0 and 0 < min_score <= 1")

    def with_overrides(self, **changes) -> "ScoringConfig":
        return replace(self, **{k: v for k, v in changes.items() if v is not None})

    def to_dict(self) -> dict:
        d = asdict(self)
        d["weights"] = self.weights.as_dict()
        d["effective_weights"] = self.weights.normalized().as_dict()
        return d


@dataclass
class ComponentScore:
    name: str
    raw: Optional[float]  # interpretable statistic the component is built from
    z: float  # standardized across all numbers in the pool
    weight: float  # normalized weight
    contribution: float  # intensity * weight * z; contributions sum to score - 1 (before the floor)


@dataclass
class NumberScore:
    number: int
    score: float
    rank: int
    components: List[ComponentScore]


@dataclass
class ScoreSet:
    game: str
    config: ScoringConfig
    scores: List[NumberScore]  # ordered by number
    dataset_fingerprint: str
    n_draws: int
    as_of: Optional[date]
    feature_config: dict
    notes: List[str] = field(default_factory=list)

    def weight_vector(self) -> np.ndarray:
        """Scores in number order, for weighted sampling."""
        return np.array([s.score for s in self.scores], dtype=float)

    def ranked(self) -> List[NumberScore]:
        return sorted(self.scores, key=lambda s: s.rank)

    def params(self) -> dict:
        """Everything needed to reproduce these scores from the same stored draws."""
        return {
            "game": self.game,
            "dataset_fingerprint": self.dataset_fingerprint,
            "n_draws": self.n_draws,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "feature_config": self.feature_config,
            "scoring": self.config.to_dict(),
        }

    def to_dict(self) -> dict:
        return {"params": self.params(), "notes": self.notes, "scores": [asdict(s) for s in self.scores]}


class NumberScorer(Protocol):
    """Anything that turns features into per-number scores (traditional or, later, ML)."""

    config: ScoringConfig

    def score(self, game: LotteryGameConfig, features: FeatureSet) -> ScoreSet:
        ...
