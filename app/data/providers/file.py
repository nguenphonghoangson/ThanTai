"""Provider reading local JSONL files (``<dir>/<game key>.jsonl``).

Used for offline work, tests, and manually importing draws the public dataset lacks.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from app.data.errors import DataFetchError
from app.data.providers.base import filter_range
from app.data.providers.jsonl_format import parse_jsonl
from app.domain.games import LotteryGameConfig
from app.domain.models import FetchResult


class JsonlFileProvider:
    name = "jsonl-file"

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def path_for(self, game: LotteryGameConfig) -> Path:
        return self._dir / f"{game.key}.jsonl"

    def fetch(self, game: LotteryGameConfig, start_date: date, end_date: date, refresh: bool = False) -> FetchResult:
        path = self.path_for(game)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DataFetchError(f"Cannot read {path}: {exc}") from exc
        parsed = parse_jsonl(game, text, source=str(path))
        return FetchResult(filter_range(parsed.draws, start_date, end_date), parsed.rejected, str(path))
