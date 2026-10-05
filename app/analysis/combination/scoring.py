"""Combination-level score: number_score + pair_score + distribution_score + sum_score."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import List, Sequence

import numpy as np

from app.analysis.combination.rules import CombinationRules
from app.analysis.features.combos import expected_combo_count
from app.analysis.features.models import FeatureSet
from app.analysis.scoring.models import ScoreSet
from app.domain.games import LotteryGameConfig


@dataclass
class CombinationScore:
    numbers: List[int]
    number_score: float  # sum of the numbers' scores (numbers_per_draw = neutral)
    pair_score: float  # pair_weight × mean(pair count / expected − 1)
    distribution_score: float  # −(odd/even + low/high + spread penalties)
    sum_score: float  # −sum penalty if the total is outside the configured percentiles
    total: float
    total_sum: int
    odd: int
    low: int
    spread: int
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class CombinationScorer:
    def __init__(self, game: LotteryGameConfig, scores: ScoreSet, features: FeatureSet, rules: CombinationRules):
        self._game = game
        self._rules = rules
        self._number_scores = {s.number: s.score for s in scores.scores}
        self._co = features.pair_matrix
        self._pair_expected = expected_combo_count(game, features.n_draws, 2)
        lo, hi = rules.sum_percentiles
        self._sum_bounds = (_percentile(features.sums.percentiles, lo), _percentile(features.sums.percentiles, hi))
        self._odd_counts = rules.counts_for("odd_counts", game.numbers_per_draw)
        self._low_counts = rules.counts_for("low_counts", game.numbers_per_draw)
        self._min_spread = rules.min_spread_fraction * (game.max_number - game.min_number)

    def score(self, combo: Sequence[int]) -> CombinationScore:
        g, r = self._game, self._rules
        flags: List[str] = []
        number_score = float(sum(self._number_scores[n] for n in combo))

        pair_score = 0.0
        if self._co is not None and r.pair_weight and self._pair_expected:
            off = g.min_number
            ratios = [self._co[a - off, b - off] / self._pair_expected - 1 for a, b in combinations(combo, 2)]
            pair_score = r.pair_weight * float(np.mean(ratios))

        odd = sum(n % 2 for n in combo)
        low = sum(1 for n in combo if g.is_low(n))
        spread = max(combo) - min(combo)
        distribution = 0.0
        if r.odd_penalty and odd in self._odd_counts:
            distribution -= r.odd_penalty
            flags.append(f"{odd} odd / {len(combo) - odd} even")
        if r.low_penalty and low in self._low_counts:
            distribution -= r.low_penalty
            flags.append(f"{low} low / {len(combo) - low} high")
        if r.spread_penalty and spread < self._min_spread:
            distribution -= r.spread_penalty
            flags.append(f"narrow range {min(combo)}–{max(combo)}")

        total_sum = int(sum(combo))
        sum_score = 0.0
        lo, hi = self._sum_bounds
        if r.sum_penalty and lo is not None and hi is not None and not lo <= total_sum <= hi:
            sum_score = -r.sum_penalty
            p_lo, p_hi = r.sum_percentiles
            flags.append(f"sum {total_sum} outside P{p_lo}–P{p_hi} ({lo:.0f}–{hi:.0f})")

        return CombinationScore(
            numbers=list(combo),
            number_score=number_score,
            pair_score=pair_score,
            distribution_score=distribution,
            sum_score=sum_score,
            total=number_score + pair_score + distribution + sum_score,
            total_sum=total_sum,
            odd=odd,
            low=low,
            spread=spread,
            flags=flags,
        )


def _percentile(percentiles: dict, p: int):
    """Look up a stored percentile, interpolating linearly between the nearest stored ones."""
    if p in percentiles:
        return percentiles[p]
    keys = sorted(percentiles)
    if not keys or p < keys[0] or p > keys[-1]:
        return None
    hi = next(k for k in keys if k > p)
    lo = max(k for k in keys if k < p)
    t = (p - lo) / (hi - lo)
    return percentiles[lo] + t * (percentiles[hi] - percentiles[lo])
