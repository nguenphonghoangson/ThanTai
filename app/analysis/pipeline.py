"""Features → scores → combinations, as one reproducible unit.

The web API, CLI and backtester all call this, so a generation is defined in exactly one place.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field, replace
from datetime import date
from typing import List, Optional, Sequence, Tuple

import numpy as np

from app.analysis.combination import (
    SAMPLER, Combination, CombinationRules, CombinationScore, CombinationScorer, sample_combinations,
)
from app.analysis.features import FeatureConfig, FeatureEngine, FeatureSet
from app.analysis.scoring import NumberScorer, ScoreSet, ScoringWeights, build_scorer
from app.domain.games import LotteryGameConfig
from app.domain.models import DrawResult
from app.logging_config import log_event

logger = logging.getLogger(__name__)


def new_seed() -> int:
    """A fresh 6-digit seed: short enough to read back and retype."""
    return secrets.randbelow(900_000) + 100_000


@dataclass(frozen=True)
class GenerationRequest:
    game: LotteryGameConfig
    strategy: str
    count: int
    seed: int
    start: Optional[date] = None
    end: Optional[date] = None
    feature_config: FeatureConfig = field(default_factory=FeatureConfig)
    weights: Optional[ScoringWeights] = None
    intensity: Optional[float] = None
    gap_mode: Optional[str] = None
    rules: CombinationRules = field(default_factory=CombinationRules)

    def __post_init__(self) -> None:
        if not 1 <= self.count <= 10_000:
            raise ValueError("count must be between 1 and 10000")
        if not 0 <= self.seed < 2**63:
            raise ValueError("seed must be a non-negative 63-bit integer")


@dataclass
class GenerationResult:
    features: FeatureSet
    scores: ScoreSet
    combinations: List[CombinationScore]  # best combination score first
    params: dict
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedRequest:
    scorer: NumberScorer
    rules: CombinationRules
    feature_config: FeatureConfig


def resolve(request: GenerationRequest) -> ResolvedRequest:
    """Scorer, effective rules and feature config for a request."""
    scorer = build_scorer(request.strategy, request.weights, request.intensity, request.gap_mode)
    # The random baseline must stay uniform: no candidate selection by combination score.
    rules = replace(request.rules, oversample=1) if scorer.config.uniform else request.rules
    needs_pairs = scorer.config.weights.pair > 0 or rules.pair_weight > 0
    feature_config = replace(request.feature_config, include_pairs=request.feature_config.include_pairs or needs_pairs)
    return ResolvedRequest(scorer, rules, feature_config)


def select_combinations(
    game: LotteryGameConfig,
    scores: ScoreSet,
    features: FeatureSet,
    rules: CombinationRules,
    count: int,
    seed: int,
    with_scores: bool = True,
) -> Tuple[List[Combination], Optional[List[CombinationScore]], List[str]]:
    """Sample candidates and apply oversample selection.

    Returns (combinations, combination scores or None, notes). With ``with_scores=False`` and
    no oversampling, combination scoring is skipped: it would only reorder the same set.
    """
    sample = sample_combinations(game, scores.weight_vector(), count * rules.oversample, seed)
    notes = list(sample.notes)
    if not with_scores and rules.oversample == 1:
        return sample.combinations, None, notes
    combo_scorer = CombinationScorer(game, scores, features, rules)
    scored = [combo_scorer.score(c) for c in sample.combinations]
    # Stable sort: ties keep sampling order, so output depends only on the seed.
    scored.sort(key=lambda c: -c.total)
    kept = scored[:count]
    if rules.oversample > 1:
        notes.append(f"Kept the best {len(kept)} of {len(scored)} sampled combinations by combination score.")
    return [tuple(c.numbers) for c in kept], kept, notes


def generate(
    draws: Sequence[DrawResult], request: GenerationRequest, as_of: Optional[date] = None
) -> GenerationResult:
    game = request.game
    resolved = resolve(request)
    features = FeatureEngine(resolved.feature_config).compute(game, draws, as_of=as_of)
    scores = resolved.scorer.score(game, features)
    _, kept, sample_notes = select_combinations(game, scores, features, resolved.rules, request.count, request.seed)

    params = {
        **scores.params(),
        "start": request.start.isoformat() if request.start else None,
        "end": request.end.isoformat() if request.end else None,
        "strategy": request.strategy,
        "count": request.count,
        "seed": request.seed,
        "rules": resolved.rules.to_dict(),
        "sampler": SAMPLER,
        "numpy_version": np.__version__,
    }
    log_event(logger, "generation.done", game=game.key, strategy=request.strategy, seed=request.seed,
              count=len(kept), n_draws=features.n_draws, as_of=as_of)
    return GenerationResult(features, scores, kept, params, list(scores.notes) + sample_notes)


def request_from_params(game: LotteryGameConfig, params: dict) -> GenerationRequest:
    """Rebuild the request that produced ``params`` (for reproducing a stored session)."""
    scoring = params["scoring"]
    return GenerationRequest(
        game=game,
        strategy=params["strategy"],
        count=params["count"],
        seed=params["seed"],
        start=date.fromisoformat(params["start"]) if params.get("start") else None,
        end=date.fromisoformat(params["end"]) if params.get("end") else None,
        feature_config=FeatureConfig.from_dict(params["feature_config"]),
        weights=None if scoring.get("uniform") else ScoringWeights(**scoring["weights"]),
        intensity=scoring.get("intensity"),
        gap_mode=scoring.get("gap_mode"),
        rules=CombinationRules.from_dict(params["rules"]),
    )
