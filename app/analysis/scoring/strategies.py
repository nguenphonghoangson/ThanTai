"""Built-in strategies. Each is just a named ScoringConfig preset."""
from __future__ import annotations

from typing import Dict, Optional

from app.analysis.scoring.models import NumberScorer, ScoringConfig, ScoringWeights
from app.analysis.scoring.scorer import UniformScorer, WeightedScorer

RANDOM = "random"

PRESETS: Dict[str, ScoringConfig] = {
    # A — long-run frequency over the selected period.
    "frequency": ScoringConfig("frequency", ScoringWeights(frequency=1.0)),
    # B — mostly the analysis window, with a little long-run frequency.
    "recent": ScoringConfig("recent", ScoringWeights(frequency=0.2, recent_frequency=0.8)),
    # C — blend of all components.
    "balanced": ScoringConfig(
        "balanced",
        ScoringWeights(frequency=0.30, recent_frequency=0.25, gap=0.15, pair=0.15, historical=0.15),
    ),
    # D — uniform random baseline. Every other strategy must beat this in backtests to mean anything.
    RANDOM: ScoringConfig(RANDOM, uniform=True),
}

DESCRIPTIONS = {
    "frequency": "Long-run frequency over the selected period",
    "recent": "Mostly the analysis window, some long-run frequency",
    "balanced": "Frequency, recent, gap, pair and historical consistency",
    RANDOM: "Uniform random baseline (all numbers equal)",
}


class UnknownStrategyError(KeyError):
    pass


def get_preset(name: str) -> ScoringConfig:
    try:
        return PRESETS[name]
    except KeyError:
        raise UnknownStrategyError(f"Unknown strategy '{name}'. Available: {', '.join(PRESETS)}") from None


def build_scorer(
    strategy: str,
    weights: Optional[ScoringWeights] = None,
    intensity: Optional[float] = None,
    gap_mode: Optional[str] = None,
) -> NumberScorer:
    config = get_preset(strategy)
    if config.uniform:
        return UniformScorer(config)
    return WeightedScorer(config.with_overrides(weights=weights, intensity=intensity, gap_mode=gap_mode))


def list_strategies() -> list:
    return [
        {"key": k, "description": DESCRIPTIONS[k], **PRESETS[k].to_dict()}
        for k in PRESETS
    ]
