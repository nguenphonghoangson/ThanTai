"""Raw component signals per number, each relative to what uniform random draws would give."""
from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from app.analysis.features.models import FeatureSet
from app.analysis.scoring.models import GapMode
from app.domain.games import LotteryGameConfig

GAP_CLIP = 3.0  # gap ratios above this are treated as 3 so one extreme gap cannot dominate

RawValues = List[Optional[float]]


def frequency_raw(fs: FeatureSet) -> RawValues:
    """Appearance rate / expected rate (1.0 = as expected)."""
    return [n.frequency_rate / fs.expected_rate for n in fs.numbers]


def recent_raw(fs: FeatureSet) -> RawValues:
    """Appearances in the hot/cold window / expected appearances."""
    return [n.temperature_ratio for n in fs.numbers]


def gap_ratio(fs: FeatureSet) -> RawValues:
    """Current gap relative to the number's own average gap (theoretical gap as fallback)."""
    out: RawValues = []
    for n in fs.numbers:
        if n.gap_deviation is not None:
            out.append(n.gap_deviation)
        else:
            out.append(n.gap / fs.expected_gap if fs.expected_gap else None)
    return out


def gap_signal(ratios: RawValues, mode: str) -> RawValues:
    sign = 1.0 if mode == GapMode.OVERDUE else -1.0
    return [None if r is None else sign * min(r, GAP_CLIP) for r in ratios]


def historical_raw(fs: FeatureSet) -> RawValues:
    """Share of past blocks in which the number beat its expected count."""
    return [n.consistency for n in fs.numbers]


def pair_raw(game: LotteryGameConfig, fs: FeatureSet, anchors: Sequence[int]) -> RawValues:
    """Co-occurrence with the anchor numbers relative to uniform.

    For number n and anchor m: co[n, m] / (freq_n * (k-1)/(N-1)), i.e. how often m showed up
    in draws containing n compared with uniform draws. Normalizing by freq_n keeps this
    independent of n's own frequency. Averaged over the anchors (excluding n itself).
    """
    co = fs.pair_matrix
    k, pool, off = game.numbers_per_draw, game.pool_size, game.min_number
    out: RawValues = []
    for nf in fs.numbers:
        others = [m for m in anchors if m != nf.number]
        expected = nf.frequency * (k - 1) / (pool - 1)
        if not others or expected == 0:
            out.append(None)
            continue
        out.append(float(np.mean([co[nf.number - off, m - off] for m in others])) / expected)
    return out


def zscores(values: RawValues) -> np.ndarray:
    """Standardize across numbers; missing values get z = 0 (neutral)."""
    arr = np.array([np.nan if v is None else v for v in values], dtype=float)
    present = ~np.isnan(arr)
    z = np.zeros_like(arr)
    if present.sum() >= 2:
        mean, std = arr[present].mean(), arr[present].std()
        if std > 1e-12:
            z[present] = (arr[present] - mean) / std
    return z
