"""Backtest metrics and comparison against the random baseline.

The unit of analysis is the target draw: all combinations generated for one draw are
compared against the same result, so they are not independent. Comparisons therefore use
the per-draw mean match count, paired across strategies (all strategies share the same
random numbers for a given draw).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.analysis.features.distributions import hypergeometric_pct
from app.domain.games import LotteryGameConfig

ALPHA = 0.05
PRIZE_MIN_MATCHES = 3  # lowest prize tier for both Mega 6/45 and Power 6/55


def match_counts(combos: Sequence[Sequence[int]], actual: Sequence[int]) -> np.ndarray:
    """Number of actual numbers in each combination."""
    arr = np.asarray(combos, dtype=np.int16)
    return np.isin(arr, np.asarray(actual, dtype=np.int16)).sum(axis=1)


class StrategyAccumulator:
    def __init__(self, k: int) -> None:
        self.k = k
        self.hist = np.zeros(k + 1, dtype=np.int64)
        self.per_draw_mean: List[float] = []
        self.per_draw_best: List[int] = []

    def add(self, matches: np.ndarray) -> None:
        self.hist += np.bincount(matches, minlength=self.k + 1)[: self.k + 1]
        self.per_draw_mean.append(float(matches.mean()))
        self.per_draw_best.append(int(matches.max()))

    def metrics(self, label: str) -> "StrategyMetrics":
        total = int(self.hist.sum())
        pct = [100 * float(c) / total if total else 0.0 for c in self.hist]
        best = max(self.per_draw_best) if self.per_draw_best else 0
        return StrategyMetrics(
            label=label,
            draws=len(self.per_draw_mean),
            combinations=total,
            average_match=float(np.dot(np.arange(self.k + 1), self.hist) / total) if total else 0.0,
            best_match=best,
            hit_counts=[int(c) for c in self.hist],
            hit_pct=pct,
            prize_rate_pct=sum(pct[PRIZE_MIN_MATCHES:]),
            draws_with_prize_pct=100 * float(np.mean(np.array(self.per_draw_best) >= PRIZE_MIN_MATCHES))
            if self.per_draw_best else 0.0,
        )


@dataclass
class StrategyMetrics:
    label: str
    draws: int
    combinations: int
    average_match: float
    best_match: int
    hit_counts: List[int]  # index = matches
    hit_pct: List[float]
    prize_rate_pct: float  # share of combinations with >= 3 matches
    draws_with_prize_pct: float  # share of draws where at least one combination had >= 3 matches


@dataclass
class Comparison:
    label: str
    baseline: str
    mean_difference: float  # strategy − baseline, matches per combination
    ci95: List[Optional[float]]  # None when there are too few draws to estimate
    z: float
    p_value: float
    p_adjusted: float  # Bonferroni across the strategies compared with the baseline
    significant: bool
    verdict: str


@dataclass
class Theory:
    expected_average: float
    hit_pct: List[float]
    prize_rate_pct: float


@dataclass
class Summary:
    strategies: Dict[str, StrategyMetrics]
    comparisons: List[Comparison]
    theory: Theory
    vs_theory: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def theory(game: LotteryGameConfig) -> Theory:
    k, n = game.numbers_per_draw, game.pool_size
    pct = hypergeometric_pct(n, k, k)
    return Theory(expected_average=k * k / n, hit_pct=pct, prize_rate_pct=sum(pct[PRIZE_MIN_MATCHES:]))


def _normal_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def paired_comparison(
    label: str, baseline: str, a: Sequence[float], b: Sequence[float], n_comparisons: int
) -> Comparison:
    d = np.asarray(a) - np.asarray(b)
    n = d.size
    mean = float(d.mean()) if n else 0.0
    se = float(d.std(ddof=1) / math.sqrt(n)) if n > 1 else float("inf")
    if se == 0:
        z, p = 0.0, 1.0  # identical per-draw results
    else:
        z = mean / se if math.isfinite(se) else 0.0
        p = _normal_p(z) if math.isfinite(se) else 1.0
    p_adj = min(1.0, p * max(n_comparisons, 1))
    ci = [mean - 1.96 * se, mean + 1.96 * se] if math.isfinite(se) else [None, None]
    significant = p_adj < ALPHA
    if n < 30:
        verdict = f"Too few draws ({n}) for a meaningful comparison."
    elif not significant:
        verdict = "No statistically significant difference from random."
    else:
        direction = "better" if mean > 0 else "worse"
        verdict = (f"Significantly {direction} than random at α={ALPHA} (Bonferroni) in this run. Re-run with a "
                   "different seed and on a later, untouched period before trusting it: one run in twenty "
                   "crosses this threshold by chance, and tuning settings on this period makes that likelier.")
    return Comparison(label, baseline, mean, ci, z, p, p_adj, significant, verdict)


def summarize(
    game: LotteryGameConfig, acc: Dict[str, StrategyAccumulator], baseline: str
) -> Summary:
    th = theory(game)
    strategies = {label: a.metrics(label) for label, a in acc.items()}
    others = [label for label in acc if label != baseline]
    comparisons = [
        paired_comparison(label, baseline, acc[label].per_draw_mean, acc[baseline].per_draw_mean, len(others))
        for label in others
    ]
    vs_theory = {}
    for label, a in acc.items():
        means = np.asarray(a.per_draw_mean)
        if means.size > 1:
            se = means.std(ddof=1) / math.sqrt(means.size)
            z = (means.mean() - th.expected_average) / se if se else 0.0
            vs_theory[label] = {"difference": float(means.mean() - th.expected_average), "z": float(z),
                                "p_value": _normal_p(z)}
    return Summary(strategies, comparisons, th, vs_theory)
