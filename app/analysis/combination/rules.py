from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class CombinationRules:
    """Configurable statistical filters for whole combinations.

    Penalties lower a combination's score; they do not claim such combinations cannot
    be drawn (every combination is equally likely in a fair draw). Set a penalty to 0 to
    disable that filter.
    """

    # Odd-number counts to penalize. None = the extremes (0 and numbers_per_draw: all even / all odd).
    odd_counts: Optional[Tuple[int, ...]] = None
    odd_penalty: float = 1.0
    # Low-number counts to penalize. None = the extremes (all high / all low).
    low_counts: Optional[Tuple[int, ...]] = None
    low_penalty: float = 1.0
    # Penalize combinations whose max − min is below this share of the pool span.
    min_spread_fraction: float = 0.3
    spread_penalty: float = 1.0
    # Penalize sums outside these historical percentiles.
    sum_percentiles: Tuple[int, int] = (5, 95)
    sum_penalty: float = 1.0
    # Weight of the pair term: mean over the combination's pairs of (count / expected − 1).
    pair_weight: float = 1.0
    # Generate `oversample × count` unique candidates and keep the best `count` by combination
    # score. 1 = keep the sampled combinations as they are (no selection).
    oversample: int = 1

    def __post_init__(self) -> None:
        if self.oversample < 1:
            raise ValueError("oversample must be >= 1")
        if not 0 <= self.min_spread_fraction <= 1:
            raise ValueError("min_spread_fraction must be in [0, 1]")
        lo, hi = self.sum_percentiles
        if not 0 <= lo < hi <= 100:
            raise ValueError("sum_percentiles must satisfy 0 <= low < high <= 100")
        if min(self.odd_penalty, self.low_penalty, self.spread_penalty, self.sum_penalty, self.pair_weight) < 0:
            raise ValueError("penalties and weights must be non-negative")
        for name in ("odd_counts", "low_counts"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, tuple(sorted(set(value))))

    def counts_for(self, name: str, numbers_per_draw: int) -> Tuple[int, ...]:
        value = getattr(self, name)
        return (0, numbers_per_draw) if value is None else value

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("odd_counts", "low_counts", "sum_percentiles"):
            if d[key] is not None:
                d[key] = list(d[key])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CombinationRules":
        d = dict(d)
        for key in ("odd_counts", "low_counts", "sum_percentiles"):
            if d.get(key) is not None:
                d[key] = tuple(d[key])
        return cls(**d)
