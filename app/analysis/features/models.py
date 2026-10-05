"""Feature engine output. Pure descriptions of past draws; no scores or predictions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.analysis.features.config import FeatureConfig


class Temperature:
    HOT = "HOT"
    WARM = "WARM"
    NORMAL = "NORMAL"
    COLD = "COLD"


@dataclass
class NumberFeatures:
    number: int
    frequency: int
    frequency_rate: float  # appearances per draw
    recent: Dict[int, int]  # window size → appearances in the last `window` draws
    gap: int  # draws since last appearance (0 = in the latest draw); draws observed if never seen
    seen: bool
    last_seen_date: Optional[date]
    last_seen_draw_id: Optional[str]
    average_gap: Optional[float]  # mean draws missed between consecutive appearances
    gap_deviation: Optional[float]  # gap / average_gap — descriptive only, not "due-ness"
    temperature_ratio: float  # observed / expected appearances in the hot/cold window
    temperature: str
    # Share of complete past blocks (consistency_block draws each, aligned to the latest draw)
    # in which the number appeared more often than expected. None if no complete block.
    consistency: Optional[float] = None


@dataclass
class CountDistribution:
    """Per-draw count of some property (odd numbers, low numbers) with its theoretical baseline."""

    label: str
    counts: List[int]  # index = how many numbers in the draw have the property
    observed_pct: List[float]
    expected_pct: List[float]  # hypergeometric, i.e. what uniform random draws produce
    mean: float
    expected_mean: float


@dataclass
class SumStats:
    count: int
    min: int
    max: int
    mean: float
    median: float
    std: float
    percentiles: Dict[int, float]
    theoretical_mean: float
    histogram: List[Tuple[int, int, int]]  # (bin_start, bin_end_inclusive, count)


@dataclass
class ComboCount:
    numbers: Tuple[int, ...]
    count: int


@dataclass
class ComboStats:
    size: int
    expected_count: float  # per combination under uniform random draws
    top: List[ComboCount]
    note: str = ""


@dataclass
class FeatureSet:
    game: str
    config: FeatureConfig
    as_of: Optional[date]  # features use only draws strictly before this date
    n_draws: int
    dataset_fingerprint: str  # sha256 of the exact draws used; pins reproducibility
    first_draw: Optional[Tuple[str, date]]
    last_draw: Optional[Tuple[str, date]]
    numbers: List[NumberFeatures]
    expected_rate: float  # numbers_per_draw / pool_size
    expected_gap: float  # mean missed draws between appearances under uniform draws
    odd_even: CountDistribution
    low_high: CountDistribution
    sums: SumStats
    pairs: Optional[ComboStats] = None
    triples: Optional[ComboStats] = None
    # Full co-occurrence matrix (pool × pool, 0-based) for the scoring engine; not serialized.
    pair_matrix: Optional[np.ndarray] = field(default=None, repr=False)

    def by_number(self, number: int) -> NumberFeatures:
        return self.numbers[number - self.numbers[0].number]

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("pair_matrix")
        d["config"] = self.config.to_dict()
        return _jsonable(d)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value
