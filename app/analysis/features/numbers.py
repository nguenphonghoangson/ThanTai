"""Per-number features: frequency, recent windows, gaps, hot/cold."""
from __future__ import annotations

from typing import List, Sequence

import numpy as np

from app.analysis.features.config import FeatureConfig, TemperatureThresholds
from app.analysis.features.models import NumberFeatures, Temperature
from app.domain.games import LotteryGameConfig
from app.domain.models import DrawResult


def draw_matrix(game: LotteryGameConfig, draws: Sequence[DrawResult]) -> np.ndarray:
    """Boolean matrix (n_draws × pool_size); column j is number ``game.min_number + j``."""
    m = np.zeros((len(draws), game.pool_size), dtype=bool)
    if draws:
        cols = np.array([d.numbers for d in draws], dtype=np.intp) - game.min_number
        m[np.arange(len(draws))[:, None], cols] = True
    return m


def classify_temperature(ratio: float, t: TemperatureThresholds) -> str:
    if ratio >= t.hot:
        return Temperature.HOT
    if ratio >= t.warm:
        return Temperature.WARM
    if ratio < t.cold:
        return Temperature.COLD
    return Temperature.NORMAL


def block_consistency(matrix: np.ndarray, block: int, expected_rate: float):
    """Per-number share of complete blocks with more appearances than expected, or None."""
    n_blocks = matrix.shape[0] // block
    if n_blocks == 0:
        return None
    recent = matrix[matrix.shape[0] - n_blocks * block:]  # drop the oldest partial block
    counts = recent.reshape(n_blocks, block, -1).sum(axis=1)
    return (counts > block * expected_rate).mean(axis=0)


def number_features(
    game: LotteryGameConfig, draws: Sequence[DrawResult], matrix: np.ndarray, config: FeatureConfig
) -> List[NumberFeatures]:
    n = len(draws)
    expected_rate = game.numbers_per_draw / game.pool_size
    freq = matrix.sum(axis=0)
    recent = {w: matrix[-w:].sum(axis=0) for w in config.recent_windows}
    hc_window = min(config.hot_cold_window, n)
    hc_expected = hc_window * expected_rate
    consistency = block_consistency(matrix, config.consistency_block, expected_rate)

    out: List[NumberFeatures] = []
    for j, number in enumerate(game.numbers):
        idx = np.flatnonzero(matrix[:, j])
        seen = idx.size > 0
        gap = int(n - 1 - idx[-1]) if seen else n
        # Missed draws between consecutive appearances; same unit as `gap`.
        average_gap = float(np.mean(np.diff(idx) - 1)) if idx.size >= 2 else None
        if average_gap is None or not seen:
            deviation = None
        elif average_gap == 0:
            deviation = 0.0 if gap == 0 else None
        else:
            deviation = gap / average_gap
        ratio = float(recent[config.hot_cold_window][j] / hc_expected) if hc_expected else 0.0
        last = draws[idx[-1]] if seen else None
        out.append(NumberFeatures(
            number=number,
            frequency=int(freq[j]),
            frequency_rate=float(freq[j] / n),
            recent={w: int(c[j]) for w, c in recent.items()},
            gap=gap,
            seen=seen,
            last_seen_date=last.draw_date if last else None,
            last_seen_draw_id=last.draw_id if last else None,
            average_gap=average_gap,
            gap_deviation=deviation,
            temperature_ratio=ratio,
            temperature=classify_temperature(ratio, config.temperature),
            consistency=float(consistency[j]) if consistency is not None else None,
        ))
    return out
