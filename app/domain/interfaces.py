"""Ports between the domain and replaceable infrastructure."""
from __future__ import annotations

from datetime import date
from typing import Any, List, Optional, Protocol, Sequence, Tuple

from app.domain.games import LotteryGameConfig
from app.domain.models import DrawResult, FetchResult


class LotteryDataProvider(Protocol):
    """Retrieves historical draws from some source.

    Returned draws are validated against ``game``, deduplicated and chronological.
    Persistence and incremental-update logic live outside providers (``DrawSyncService``).
    ``refresh`` asks the provider to bypass any short-lived download cache.
    """

    name: str

    def fetch(
        self, game: LotteryGameConfig, start_date: date, end_date: date, refresh: bool = False
    ) -> FetchResult:
        ...


class DrawRepository(Protocol):
    def save_draws(self, game: LotteryGameConfig, draws: Sequence[DrawResult]) -> Any:
        """Insert new draws; never overwrite stored ones. Returns a save report."""
        ...

    def get_draws(
        self,
        game: LotteryGameConfig,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[DrawResult]:
        """Draws with start_date <= draw_date <= end_date, oldest first."""
        ...

    def count(self, game: LotteryGameConfig) -> int:
        ...

    def date_bounds(self, game: LotteryGameConfig) -> Optional[Tuple[date, date]]:
        ...
