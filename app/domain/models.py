"""Core domain records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Optional, Tuple

from app.domain.games import LotteryGameConfig


class DrawValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DrawResult:
    """One official draw. ``numbers`` are the main balls, always sorted ascending.

    Draws happen at most once per day per game, so ``draw_date`` is a ``date``;
    leakage rules in backtesting compare on this field with a strict ``<``.
    """

    draw_id: str
    draw_date: date
    numbers: Tuple[int, ...]
    bonus_number: Optional[int] = None

    @classmethod
    def create(
        cls,
        game: LotteryGameConfig,
        draw_id: str,
        draw_date: date,
        numbers: Iterable[int],
        bonus_number: Optional[int] = None,
    ) -> "DrawResult":
        """Build a validated, normalized draw for ``game``."""
        nums = tuple(sorted(_as_int(n) for n in numbers))
        bonus = _as_int(bonus_number) if bonus_number is not None else None
        draw = cls(str(draw_id).strip(), draw_date, nums, bonus)
        validate_draw(game, draw)
        return draw


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        raise DrawValidationError(f"Invalid number: {value!r}")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise DrawValidationError(f"Invalid number: {value!r}") from None
    if isinstance(value, float) and value != result:
        raise DrawValidationError(f"Invalid number: {value!r}")
    return result


def validate_draw(game: LotteryGameConfig, draw: DrawResult) -> None:
    """Raise ``DrawValidationError`` if ``draw`` is not a legal result for ``game``."""
    if not draw.draw_id:
        raise DrawValidationError("draw_id is empty")
    if not isinstance(draw.draw_date, date):
        raise DrawValidationError("draw_date must be a date")

    nums = draw.numbers
    if len(nums) != game.numbers_per_draw:
        raise DrawValidationError(
            f"{game.name} draw must have {game.numbers_per_draw} numbers, got {len(nums)}"
        )
    if len(set(nums)) != len(nums):
        raise DrawValidationError(f"Duplicate numbers in draw {draw.draw_id}: {list(nums)}")
    out_of_range = [n for n in nums if not game.is_valid_number(n)]
    if out_of_range:
        raise DrawValidationError(
            f"Numbers out of range {game.min_number}-{game.max_number}: {out_of_range}"
        )
    if list(nums) != sorted(nums):
        raise DrawValidationError("numbers must be sorted ascending")

    if draw.bonus_number is not None:
        if not game.has_bonus_number:
            raise DrawValidationError(f"{game.name} has no bonus number")
        if not game.is_valid_number(draw.bonus_number):
            raise DrawValidationError(f"Bonus number out of range: {draw.bonus_number}")
        if draw.bonus_number in nums:
            raise DrawValidationError("Bonus number duplicates a main number")


@dataclass(frozen=True)
class RejectedRecord:
    """A source record that was skipped, kept for diagnostics."""

    ref: str  # line number or draw id
    reason: str


@dataclass
class FetchResult:
    draws: List[DrawResult]  # validated, deduplicated, chronological
    rejected: List[RejectedRecord] = field(default_factory=list)
    source: str = ""
    stale: bool = False  # served from an expired cache because the source was unreachable
