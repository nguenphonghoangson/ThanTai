"""Pair and triple co-occurrence counts."""
from __future__ import annotations

from collections import Counter
from itertools import combinations
from math import comb
from typing import Sequence

import numpy as np

from app.analysis.features.models import ComboCount, ComboStats
from app.domain.games import LotteryGameConfig
from app.domain.models import DrawResult


def expected_combo_count(game: LotteryGameConfig, n_draws: int, size: int) -> float:
    """Expected occurrences of one specific `size`-subset over `n_draws` uniform draws."""
    return n_draws * comb(game.numbers_per_draw, size) / comb(game.pool_size, size)


def pair_matrix(matrix: np.ndarray) -> np.ndarray:
    """Symmetric co-occurrence counts (pool × pool), zero diagonal."""
    # Float matmul uses BLAS (integer matmul does not), ~10x faster; 0/1 inputs keep counts exact.
    # Apple Accelerate (numpy 2.0 on macOS) sets spurious FP-exception flags on this call, so the
    # warnings are silenced here and finiteness is checked explicitly instead.
    m = matrix.astype(np.float64)
    with np.errstate(all="ignore"):
        product = m.T @ m
    if not np.isfinite(product).all():
        raise FloatingPointError("pair co-occurrence matrix is not finite")
    co = np.rint(product).astype(np.int64)
    np.fill_diagonal(co, 0)
    return co


def pair_stats(game: LotteryGameConfig, co: np.ndarray, n_draws: int, top: int) -> ComboStats:
    iu = np.triu_indices(game.pool_size, k=1)
    counts = co[iu]
    order = np.lexsort((iu[1], iu[0], -counts))[:top]  # count desc, then numbers asc
    off = game.min_number
    return ComboStats(
        size=2,
        expected_count=expected_combo_count(game, n_draws, 2),
        top=[ComboCount((int(iu[0][i]) + off, int(iu[1][i]) + off), int(counts[i])) for i in order],
    )


def triple_stats(
    game: LotteryGameConfig, draws: Sequence[DrawResult], top: int, min_support: int
) -> ComboStats:
    counter: Counter = Counter()
    for d in draws:
        counter.update(combinations(d.numbers, 3))
    expected = expected_combo_count(game, len(draws), 3)
    ranked = sorted(((c, t) for t, c in counter.items() if c >= min_support), key=lambda x: (-x[0], x[1]))
    note = ""
    if expected < 5:
        note = (f"Each triple is expected about {expected:.2f} times in {len(draws)} draws; "
                "counts this small are dominated by chance.")
    return ComboStats(
        size=3,
        expected_count=expected,
        top=[ComboCount(t, c) for c, t in ranked[:top]],
        note=note,
    )

