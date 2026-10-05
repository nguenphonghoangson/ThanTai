"""Lottery game definitions.

Everything game-specific (number range, draw size, low/high split) is derived
from a ``LotteryGameConfig`` so no module hardcodes Mega 6/45 rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class LotteryGameConfig:
    key: str
    name: str
    min_number: int
    max_number: int
    numbers_per_draw: int
    # Power 6/55 draws an extra bonus ball (used only for the Jackpot 2 prize).
    # It is stored but excluded from the main-number analysis.
    has_bonus_number: bool = False

    def __post_init__(self) -> None:
        if self.min_number > self.max_number:
            raise ValueError("min_number must be <= max_number")
        if not 0 < self.numbers_per_draw <= self.pool_size:
            raise ValueError("numbers_per_draw must be in 1..pool_size")

    @property
    def pool_size(self) -> int:
        return self.max_number - self.min_number + 1

    @property
    def numbers(self) -> range:
        return range(self.min_number, self.max_number + 1)

    @property
    def low_max(self) -> int:
        """Largest number classified as LOW (lower half of the pool, rounded down)."""
        return self.min_number - 1 + self.pool_size // 2

    def is_low(self, number: int) -> bool:
        return number <= self.low_max

    def is_valid_number(self, number: int) -> bool:
        return self.min_number <= number <= self.max_number

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "min_number": self.min_number,
            "max_number": self.max_number,
            "numbers_per_draw": self.numbers_per_draw,
            "has_bonus_number": self.has_bonus_number,
            "low_range": [self.min_number, self.low_max],
            "high_range": [self.low_max + 1, self.max_number],
        }


MEGA_645 = LotteryGameConfig(
    key="mega645", name="Mega 6/45", min_number=1, max_number=45, numbers_per_draw=6
)
POWER_655 = LotteryGameConfig(
    key="power655",
    name="Power 6/55",
    min_number=1,
    max_number=55,
    numbers_per_draw=6,
    has_bonus_number=True,
)

GAMES: Dict[str, LotteryGameConfig] = {g.key: g for g in (MEGA_645, POWER_655)}


class UnknownGameError(KeyError):
    pass


def get_game(key: str) -> LotteryGameConfig:
    try:
        return GAMES[key]
    except KeyError:
        raise UnknownGameError(f"Unknown game '{key}'. Supported: {', '.join(GAMES)}") from None


def list_games() -> List[LotteryGameConfig]:
    return list(GAMES.values())
