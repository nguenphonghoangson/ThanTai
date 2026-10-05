"""Draw-level distributions: odd/even, low/high, sums."""
from __future__ import annotations

from math import comb
from typing import List

import numpy as np

from app.analysis.features.models import CountDistribution, SumStats
from app.domain.games import LotteryGameConfig

PERCENTILES = (1, 2, 5, 10, 25, 50, 75, 90, 95, 98, 99)
SUM_BIN_WIDTH = 10


def hypergeometric_pct(pool: int, successes: int, draws: int) -> List[float]:
    """P(X = x) * 100 for x in 0..draws when drawing without replacement."""
    total = comb(pool, draws)
    return [100 * comb(successes, x) * comb(pool - successes, draws - x) / total for x in range(draws + 1)]


def count_distribution(label: str, per_draw: np.ndarray, game: LotteryGameConfig, successes: int) -> CountDistribution:
    k = game.numbers_per_draw
    counts = np.bincount(per_draw, minlength=k + 1)[: k + 1]
    n = int(counts.sum())
    expected = hypergeometric_pct(game.pool_size, successes, k)
    return CountDistribution(
        label=label,
        counts=[int(c) for c in counts],
        observed_pct=[100 * float(c) / n if n else 0.0 for c in counts],
        expected_pct=expected,
        mean=float(per_draw.mean()) if n else 0.0,
        expected_mean=k * successes / game.pool_size,
    )


def odd_even(game: LotteryGameConfig, matrix: np.ndarray) -> CountDistribution:
    odd_cols = np.array([n % 2 == 1 for n in game.numbers])
    return count_distribution("odd", matrix[:, odd_cols].sum(axis=1), game, int(odd_cols.sum()))


def low_high(game: LotteryGameConfig, matrix: np.ndarray) -> CountDistribution:
    low_cols = np.array([game.is_low(n) for n in game.numbers])
    return count_distribution("low", matrix[:, low_cols].sum(axis=1), game, int(low_cols.sum()))


def sum_stats(game: LotteryGameConfig, matrix: np.ndarray) -> SumStats:
    values = np.arange(game.min_number, game.max_number + 1)
    sums = matrix.astype(np.int64) @ values
    lo, hi = int(sums.min()), int(sums.max())
    start = lo - lo % SUM_BIN_WIDTH
    edges = np.arange(start, hi + SUM_BIN_WIDTH + 1, SUM_BIN_WIDTH)
    hist, _ = np.histogram(sums, bins=edges)
    return SumStats(
        count=int(sums.size),
        min=lo,
        max=hi,
        mean=float(sums.mean()),
        median=float(np.median(sums)),
        std=float(sums.std(ddof=1)) if sums.size > 1 else 0.0,
        percentiles=dict(zip(PERCENTILES, map(float, np.percentile(sums, PERCENTILES)))),
        theoretical_mean=game.numbers_per_draw * (game.min_number + game.max_number) / 2,
        histogram=[(int(a), int(a) + SUM_BIN_WIDTH - 1, int(c)) for a, c in zip(edges[:-1], hist)],
    )
