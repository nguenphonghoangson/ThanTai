"""Feature Engine: describes a draw history. It never scores or predicts."""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date
from typing import List, Optional, Sequence

from app.analysis.features import combos, distributions
from app.analysis.features.config import FeatureConfig
from app.analysis.features.models import FeatureSet
from app.analysis.features.numbers import draw_matrix, number_features
from app.domain.games import LotteryGameConfig
from app.domain.models import DrawResult
from app.logging_config import log_event

logger = logging.getLogger(__name__)


class InsufficientDataError(ValueError):
    pass


def dataset_fingerprint(game: LotteryGameConfig, draws: Sequence[DrawResult]) -> str:
    h = hashlib.sha256(game.key.encode())
    for d in draws:
        h.update(f"|{d.draw_id},{d.draw_date},{','.join(map(str, d.numbers))}".encode())
    return h.hexdigest()[:16]


def draws_before(draws: Sequence[DrawResult], cutoff: date) -> List[DrawResult]:
    """Draws strictly before ``cutoff``. The single place the leakage rule is applied."""
    return [d for d in draws if d.draw_date < cutoff]


class FeatureEngine:
    def __init__(self, config: Optional[FeatureConfig] = None) -> None:
        self.config = config or FeatureConfig()

    def compute(
        self,
        game: LotteryGameConfig,
        draws: Sequence[DrawResult],
        as_of: Optional[date] = None,
        fingerprint: bool = True,
    ) -> FeatureSet:
        """Compute features from ``draws``.

        With ``as_of``, only draws dated strictly before it are used, so the result is
        exactly what was knowable before the draw on ``as_of`` took place.
        ``fingerprint=False`` skips hashing the history (the backtester fingerprints its
        whole input once instead of once per target).
        """
        started = time.perf_counter()
        history = draws_before(draws, as_of) if as_of is not None else list(draws)
        history.sort(key=lambda d: (d.draw_date, d.draw_id))
        if not history:
            raise InsufficientDataError(f"No {game.name} draws available" + (f" before {as_of}" if as_of else ""))

        cfg = self.config
        matrix = draw_matrix(game, history)
        n = len(history)
        expected_rate = game.numbers_per_draw / game.pool_size
        co = combos.pair_matrix(matrix) if cfg.include_pairs else None

        result = FeatureSet(
            game=game.key,
            config=cfg,
            as_of=as_of,
            n_draws=n,
            dataset_fingerprint=dataset_fingerprint(game, history) if fingerprint else "",
            first_draw=(history[0].draw_id, history[0].draw_date),
            last_draw=(history[-1].draw_id, history[-1].draw_date),
            numbers=number_features(game, history, matrix, cfg),
            expected_rate=expected_rate,
            expected_gap=(1 - expected_rate) / expected_rate,
            odd_even=distributions.odd_even(game, matrix),
            low_high=distributions.low_high(game, matrix),
            sums=distributions.sum_stats(game, matrix),
            pairs=combos.pair_stats(game, co, n, cfg.top_pairs) if co is not None else None,
            triples=(combos.triple_stats(game, history, cfg.top_triples, cfg.triple_min_support)
                     if cfg.include_triples else None),
            pair_matrix=co,
        )
        log_event(logger, "features.computed", logging.DEBUG, game=game.key, n_draws=n, as_of=as_of,
                  ms=round((time.perf_counter() - started) * 1000, 1))
        return result
