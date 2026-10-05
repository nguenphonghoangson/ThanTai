from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class TemperatureThresholds:
    """Hot/cold bands as a ratio of observed to expected appearances in the hot/cold window.

    ratio >= hot → HOT, >= warm → WARM, < cold → COLD, otherwise NORMAL.
    These are descriptive labels for recent history, not signals about future draws.
    """

    hot: float = 1.5
    warm: float = 1.15
    cold: float = 0.6

    def __post_init__(self) -> None:
        if not 0 <= self.cold <= self.warm <= self.hot:
            raise ValueError("thresholds must satisfy 0 <= cold <= warm <= hot")


@dataclass(frozen=True)
class FeatureConfig:
    recent_windows: Tuple[int, ...] = (10, 20, 50, 100)
    # The dashboard's "analysis window": drives hot/cold labels and the headline "recent" column.
    hot_cold_window: int = 100
    temperature: TemperatureThresholds = field(default_factory=TemperatureThresholds)
    include_pairs: bool = True
    include_triples: bool = False
    top_pairs: int = 20
    top_triples: int = 20
    # Triples are sparse (~2 expected occurrences each over the full history), so only
    # list those seen at least this often.
    triple_min_support: int = 3
    # Block length (draws) for the consistency feature: share of past blocks in which a
    # number appeared more often than expected.
    consistency_block: int = 50

    def __post_init__(self) -> None:
        windows = tuple(sorted(set(self.recent_windows) | {self.hot_cold_window}))
        if any(w <= 0 for w in windows) or self.consistency_block <= 0:
            raise ValueError("windows must be positive")
        object.__setattr__(self, "recent_windows", windows)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recent_windows"] = list(self.recent_windows)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureConfig":
        d = dict(d)
        d["recent_windows"] = tuple(d["recent_windows"])
        d["temperature"] = TemperatureThresholds(**d["temperature"])
        return cls(**d)
