"""Provider backed by the public vietvudanh/vietlott-data dataset (JSONL, refreshed daily).

The dataset publishes one file per game, so a fetch downloads (or reuses the cached)
whole file and filters it to the requested range. Normalization runs on the full
file before filtering because chronology checks need each draw's neighbours.
"""
from __future__ import annotations

import logging
from datetime import date

from app.data.cache import CachedHttpClient
from app.data.errors import DataFetchError
from app.data.providers.base import filter_range
from app.data.providers.jsonl_format import parse_jsonl
from app.domain.games import LotteryGameConfig
from app.domain.models import FetchResult
from app.logging_config import log_event

logger = logging.getLogger(__name__)

# The dataset names Mega 6/45 "power645".
DATASET_FILES = {"mega645": "power645.jsonl", "power655": "power655.jsonl"}


class GithubDatasetProvider:
    name = "github-dataset"

    def __init__(self, http: CachedHttpClient, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    def fetch(self, game: LotteryGameConfig, start_date: date, end_date: date, refresh: bool = False) -> FetchResult:
        filename = DATASET_FILES.get(game.key)
        if filename is None:
            raise DataFetchError(f"{self.name} has no data for {game.name}")
        url = f"{self._base_url}/{filename}"
        response = self._http.get_text(url, force_revalidate=refresh)
        parsed = parse_jsonl(game, response.text, source=url)
        draws = filter_range(parsed.draws, start_date, end_date)
        log_event(logger, "provider.fetch", provider=self.name, game=game.key,
                  start=start_date, end=end_date, returned=len(draws),
                  rejected=len(parsed.rejected), from_cache=response.from_cache, stale=response.stale)
        return FetchResult(draws=draws, rejected=parsed.rejected, source=url, stale=response.stale)
