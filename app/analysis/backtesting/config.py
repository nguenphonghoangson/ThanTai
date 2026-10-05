from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Tuple

from app.analysis.combination import CombinationRules
from app.analysis.features import FeatureConfig
from app.analysis.scoring import RANDOM, ScoringWeights, get_preset


@dataclass(frozen=True)
class StrategySpec:
    """One strategy under test. ``label`` must be unique within a backtest."""

    label: str
    strategy: str
    weights: Optional[ScoringWeights] = None
    intensity: Optional[float] = None
    gap_mode: Optional[str] = None

    def __post_init__(self) -> None:
        get_preset(self.strategy)  # validates the name

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "strategy": self.strategy,
            "weights": self.weights.as_dict() if self.weights else None,
            "intensity": self.intensity,
            "gap_mode": self.gap_mode,
        }


DEFAULT_STRATEGIES: Tuple[StrategySpec, ...] = (
    StrategySpec(RANDOM, RANDOM),
    StrategySpec("frequency", "frequency"),
    StrategySpec("recent", "recent"),
    StrategySpec("balanced", "balanced"),
)


@dataclass(frozen=True)
class BacktestConfig:
    start: date  # first target draw date (inclusive)
    end: date  # last target draw date (inclusive)
    strategies: Tuple[StrategySpec, ...] = DEFAULT_STRATEGIES
    combinations_per_draw: int = 100
    # Skip targets with fewer prior draws than this (features would be too noisy).
    min_history: int = 100
    # None = expanding window from training_start; N = only the last N prior draws.
    history_window: Optional[int] = None
    training_start: Optional[date] = None
    step: int = 1  # evaluate every `step`-th draw in the period
    base_seed: int = 20240101
    feature_config: FeatureConfig = field(default_factory=FeatureConfig)
    rules: CombinationRules = field(default_factory=CombinationRules)
    baseline: str = RANDOM

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("backtest start must be on or before end")
        if self.training_start and self.training_start > self.start:
            raise ValueError("training start must be on or before the backtest start")
        if not 1 <= self.combinations_per_draw <= 5000:
            raise ValueError("combinations_per_draw must be between 1 and 5000")
        if self.min_history < 1 or self.step < 1 or (self.history_window is not None and self.history_window < 1):
            raise ValueError("min_history, step and history_window must be positive")
        labels = [s.label for s in self.strategies]
        if len(set(labels)) != len(labels):
            raise ValueError("strategy labels must be unique")
        if self.baseline not in labels:
            raise ValueError(f"baseline '{self.baseline}' must be one of the strategies")

    def seed_for(self, draw_id: str) -> int:
        """Per-target seed, shared by all strategies (common random numbers)."""
        digest = hashlib.sha256(f"{self.base_seed}:{draw_id}".encode()).digest()
        return int.from_bytes(digest[:8], "big") >> 1

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "strategies": [s.to_dict() for s in self.strategies],
            "combinations_per_draw": self.combinations_per_draw,
            "min_history": self.min_history,
            "history_window": self.history_window,
            "training_start": self.training_start.isoformat() if self.training_start else None,
            "step": self.step,
            "base_seed": self.base_seed,
            "feature_config": self.feature_config.to_dict(),
            "rules": self.rules.to_dict(),
            "baseline": self.baseline,
        }
