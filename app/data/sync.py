"""Incremental synchronisation: fetch only date ranges not yet covered locally."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import List
from zoneinfo import ZoneInfo

from app.data.coverage import DateRange, missing_ranges
from app.data.repository import SqliteCoverageRepository, SqliteDrawRepository
from app.domain.games import LotteryGameConfig
from app.domain.interfaces import LotteryDataProvider
from app.logging_config import log_event

logger = logging.getLogger(__name__)

VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def vietnam_today() -> date:
    """Draw dates are Vietnam-local; use that calendar regardless of the server's timezone."""
    return datetime.now(VIETNAM_TZ).date()


@dataclass
class SyncReport:
    game: str
    requested: DateRange
    fetched_ranges: List[DateRange] = field(default_factory=list)
    received: int = 0
    inserted: int = 0
    unchanged: int = 0
    conflicts: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)  # "ref: reason"
    stale_source: bool = False
    source: str = ""

    @property
    def up_to_date(self) -> bool:
        return not self.fetched_ranges

    def to_dict(self) -> dict:
        d = asdict(self)
        d["requested"] = [x.isoformat() for x in self.requested]
        d["fetched_ranges"] = [[s.isoformat(), e.isoformat()] for s, e in self.fetched_ranges]
        d["up_to_date"] = self.up_to_date
        return d


class DrawSyncService:
    def __init__(
        self,
        provider: LotteryDataProvider,
        draws: SqliteDrawRepository,
        coverage: SqliteCoverageRepository,
        today: date,
        settle_days: int = 2,
    ) -> None:
        self._provider = provider
        self._draws = draws
        self._coverage = coverage
        self._today = today
        self._settle_days = settle_days

    def sync(self, game: LotteryGameConfig, start: date, end: date, force: bool = False) -> SyncReport:
        if start > end:
            raise ValueError("start date must be on or before end date")
        end = min(end, self._today)
        report = SyncReport(game=game.key, requested=(start, end), source=self._provider.name)
        if start > end:
            return report

        covered = [] if force else self._coverage.get(game)
        gaps = missing_ranges((start, end), covered)
        log_event(logger, "sync.plan", game=game.key, start=start, end=end, force=force,
                  missing=[[s.isoformat(), e.isoformat()] for s, e in gaps])

        # Only dates older than the settle window are marked complete; recent days are re-checked.
        settled_until = self._today - timedelta(days=self._settle_days)
        for gap_start, gap_end in gaps:
            result = self._provider.fetch(game, gap_start, gap_end, refresh=force)
            saved = self._draws.save_draws(game, result.draws)

            report.fetched_ranges.append((gap_start, gap_end))
            report.received += len(result.draws)
            report.inserted += saved.inserted
            report.unchanged += saved.unchanged
            report.conflicts.extend(saved.conflicts)
            report.rejected.extend(f"{r.ref}: {r.reason}" for r in result.rejected)
            report.stale_source = report.stale_source or result.stale
            report.source = result.source or report.source

            # A stale (offline) copy is not proof of completeness, so don't record coverage.
            if not result.stale and gap_start <= settled_until:
                self._coverage.add(game, (gap_start, min(gap_end, settled_until)))

        # Providers that read a whole file report the same rejections for each gap.
        report.rejected = list(dict.fromkeys(report.rejected))
        log_event(logger, "sync.done", game=game.key, inserted=report.inserted, received=report.received,
                  conflicts=len(report.conflicts), rejected=len(report.rejected), stale=report.stale_source)
        return report
