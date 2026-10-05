from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Sequence, Tuple

from app.data.coverage import DateRange, merge_ranges
from app.domain.games import LotteryGameConfig
from app.domain.models import DrawResult, validate_draw
from app.logging_config import log_event

logger = logging.getLogger(__name__)


@dataclass
class SaveResult:
    inserted: int = 0
    unchanged: int = 0
    # Stored draws whose incoming version differs. The stored version is kept;
    # these are surfaced so a source correction is never applied silently.
    conflicts: List[str] = field(default_factory=list)


class SqliteDrawRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_draws(self, game: LotteryGameConfig, draws: Sequence[DrawResult]) -> SaveResult:
        for d in draws:
            validate_draw(game, d)
        existing = self._existing(game, [d.draw_id for d in draws])
        result = SaveResult()
        new_rows = []
        for d in draws:
            stored = existing.get(d.draw_id)
            if stored is None:
                new_rows.append(
                    (game.key, d.draw_id, d.draw_date.isoformat(), json.dumps(list(d.numbers)), d.bonus_number)
                )
                existing[d.draw_id] = d  # guards against duplicates within the batch
            elif stored == d:
                result.unchanged += 1
            else:
                result.conflicts.append(d.draw_id)
        with self._conn:
            self._conn.executemany(
                # OR IGNORE: a concurrent fetch may have inserted the same draw meanwhile.
                "INSERT OR IGNORE INTO draws (game, draw_id, draw_date, numbers_json, bonus_number) VALUES (?, ?, ?, ?, ?)",
                new_rows,
            )
        result.inserted = len(new_rows)
        log_event(logger, "repository.save", game=game.key, received=len(draws), inserted=result.inserted,
                  unchanged=result.unchanged, conflicts=len(result.conflicts))
        if result.conflicts:
            log_event(logger, "repository.conflicts", logging.WARNING, game=game.key,
                      draw_ids=result.conflicts[:20])
        return result

    def _existing(self, game: LotteryGameConfig, draw_ids: List[str]) -> dict:
        found = {}
        for i in range(0, len(draw_ids), 500):  # stay under SQLite's variable limit
            chunk = draw_ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for row in self._conn.execute(
                "SELECT draw_id, draw_date, numbers_json, bonus_number FROM draws"
                f" WHERE game = ? AND draw_id IN ({marks})",
                [game.key, *chunk],
            ):
                found[row["draw_id"]] = _row_to_draw(row)
        return found

    def get_draws(
        self,
        game: LotteryGameConfig,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[DrawResult]:
        sql = "SELECT draw_id, draw_date, numbers_json, bonus_number FROM draws WHERE game = ?"
        params: list = [game.key]
        if start_date is not None:
            sql += " AND draw_date >= ?"
            params.append(start_date.isoformat())
        if end_date is not None:
            sql += " AND draw_date <= ?"
            params.append(end_date.isoformat())
        # draw_id tiebreak keeps ordering deterministic; ids are zero-padded by providers.
        sql += " ORDER BY draw_date, draw_id"
        return [_row_to_draw(r) for r in self._conn.execute(sql, params)]

    def count(self, game: LotteryGameConfig) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM draws WHERE game = ?", (game.key,)).fetchone()
        return int(row[0])

    def date_bounds(self, game: LotteryGameConfig) -> Optional[Tuple[date, date]]:
        row = self._conn.execute(
            "SELECT MIN(draw_date), MAX(draw_date) FROM draws WHERE game = ?", (game.key,)
        ).fetchone()
        if row[0] is None:
            return None
        return date.fromisoformat(row[0]), date.fromisoformat(row[1])

    def draw_id_gaps(self, game: LotteryGameConfig) -> List[int]:
        """Draw numbers missing between the first and last stored draw."""
        ids = sorted(int(r[0]) for r in self._conn.execute("SELECT draw_id FROM draws WHERE game = ?", (game.key,)))
        if not ids:
            return []
        present = set(ids)
        return [i for i in range(ids[0], ids[-1] + 1) if i not in present]

    def first_last_draw_ids(self, game: LotteryGameConfig) -> Optional[Tuple[str, str]]:
        row = self._conn.execute(
            "SELECT MIN(draw_id), MAX(draw_id) FROM draws WHERE game = ?", (game.key,)
        ).fetchone()
        return (row[0], row[1]) if row[0] is not None else None


class SqliteCoverageRepository:
    """Tracks which date ranges have been fetched per game."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, game: LotteryGameConfig) -> List[DateRange]:
        rows = self._conn.execute(
            "SELECT start_date, end_date FROM fetch_coverage WHERE game = ? ORDER BY start_date", (game.key,)
        )
        return [(date.fromisoformat(r[0]), date.fromisoformat(r[1])) for r in rows]

    def add(self, game: LotteryGameConfig, new: DateRange) -> None:
        merged = merge_ranges(self.get(game) + [new])
        with self._conn:
            self._conn.execute("DELETE FROM fetch_coverage WHERE game = ?", (game.key,))
            self._conn.executemany(
                "INSERT INTO fetch_coverage (game, start_date, end_date) VALUES (?, ?, ?)",
                [(game.key, s.isoformat(), e.isoformat()) for s, e in merged],
            )

    def clear(self, game: LotteryGameConfig) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM fetch_coverage WHERE game = ?", (game.key,))


def _row_to_draw(row: sqlite3.Row) -> DrawResult:
    return DrawResult(
        draw_id=row["draw_id"],
        draw_date=date.fromisoformat(row["draw_date"]),
        numbers=tuple(json.loads(row["numbers_json"])),
        bonus_number=row["bonus_number"],
    )
