from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

from app.analysis.features.models import FeatureSet
from app.analysis.scoring import components as comp
from app.analysis.scoring.models import ComponentScore, NumberScore, ScoreSet, ScoringConfig
from app.domain.games import LotteryGameConfig
from app.logging_config import log_event

logger = logging.getLogger(__name__)


class MissingFeatureError(ValueError):
    pass


class WeightedScorer:
    """Traditional statistical scorer: score = max(floor, 1 + intensity · Σ wᵢ·zᵢ)."""

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    def score(self, game: LotteryGameConfig, features: FeatureSet) -> ScoreSet:
        cfg = self.config
        w = cfg.weights.normalized().as_dict()
        notes: List[str] = []

        raw: Dict[str, comp.RawValues] = {
            "frequency": comp.frequency_raw(features),
            "recent_frequency": comp.recent_raw(features),
            "gap": comp.gap_ratio(features),
            "historical": comp.historical_raw(features),
        }
        signal = dict(raw)
        signal["gap"] = comp.gap_signal(raw["gap"], cfg.gap_mode)
        if w["historical"] and all(v is None for v in raw["historical"]):
            notes.append(f"History shorter than one {features.config.consistency_block}-draw block; "
                         "historical component is neutral.")
        z = {name: comp.zscores(values) for name, values in signal.items()}

        if w["pair"]:
            if features.pair_matrix is None:
                raise MissingFeatureError("pair weight > 0 requires features computed with pair analysis")
            anchors = self._anchors(game, features, z, w)
            raw["pair"] = comp.pair_raw(game, features, anchors)
            z["pair"] = comp.zscores(raw["pair"])
            notes.append("Pair component: co-occurrence with the top-ranked numbers "
                         f"{', '.join(f'{a:02d}' for a in anchors)} relative to uniform draws.")
        else:
            raw["pair"] = [None] * game.pool_size
            z["pair"] = np.zeros(game.pool_size)

        names = [n for n in ("frequency", "recent_frequency", "gap", "pair", "historical")]
        contributions = {n: cfg.intensity * w[n] * z[n] for n in names}
        totals = 1 + sum(contributions.values())
        final = np.maximum(totals, cfg.min_score)
        if (totals < cfg.min_score).any():
            notes.append(f"{int((totals < cfg.min_score).sum())} score(s) raised to the floor {cfg.min_score}.")

        ranks = _ranks(final)
        scores = [
            NumberScore(
                number=nf.number,
                score=float(final[j]),
                rank=int(ranks[j]),
                components=[
                    ComponentScore(n, _opt(raw[n][j]), float(z[n][j]), w[n], float(contributions[n][j]))
                    for n in names if w[n] > 0
                ],
            )
            for j, nf in enumerate(features.numbers)
        ]
        log_event(logger, "scoring.done", logging.DEBUG, game=game.key, strategy=cfg.strategy, n_draws=features.n_draws,
                  as_of=features.as_of, min=round(float(final.min()), 3), max=round(float(final.max()), 3))
        return _score_set(game, cfg, scores, features, notes)

    @staticmethod
    def _anchors(game, features, z, w) -> List[int]:
        """Top numbers by the non-pair components (frequency if those weights are all zero)."""
        base = sum(w[n] * z[n] for n in ("frequency", "recent_frequency", "gap", "historical"))
        if not np.any(base):
            base = z["frequency"]
        order = np.lexsort((np.arange(game.pool_size), -base))[: game.numbers_per_draw]
        return sorted(int(i) + game.min_number for i in order)


class UniformScorer:
    """Random baseline: every number has score 1.0, so sampling is uniform."""

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    def score(self, game: LotteryGameConfig, features: FeatureSet) -> ScoreSet:
        scores = [NumberScore(nf.number, 1.0, 1, []) for nf in features.numbers]
        return _score_set(game, self.config, scores, features,
                          ["Random baseline: all numbers weighted equally."])


def _score_set(game, cfg, scores, features: FeatureSet, notes) -> ScoreSet:
    return ScoreSet(
        game=game.key,
        config=cfg,
        scores=scores,
        dataset_fingerprint=features.dataset_fingerprint,
        n_draws=features.n_draws,
        as_of=features.as_of,
        feature_config=features.config.to_dict(),
        notes=notes,
    )


def _ranks(values: np.ndarray) -> np.ndarray:
    order = np.lexsort((np.arange(values.size), -values))  # score desc, then number asc
    ranks = np.empty(values.size, dtype=int)
    ranks[order] = np.arange(1, values.size + 1)
    return ranks


def _opt(v):
    return None if v is None else float(v)
