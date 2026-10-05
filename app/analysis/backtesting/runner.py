"""Walk-forward backtester.

For each target draw T in the period:
  1. history = draws strictly before T's date (optionally from training_start / last N draws)
  2. features from history only (FeatureEngine also enforces as_of = T.date)
  3. scores and combinations for every strategy, with a per-T seed shared by all strategies
  4. compare combinations with T's numbers
T's own numbers are read only in step 4.
"""
from __future__ import annotations

import logging
import time
from bisect import bisect_left
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from app.analysis.backtesting.config import BacktestConfig
from app.analysis.backtesting.metrics import StrategyAccumulator, Summary, match_counts, summarize
from app.analysis.combination import SAMPLER
from app.analysis.features import FeatureEngine
from app.analysis.features.engine import dataset_fingerprint
from app.analysis.pipeline import GenerationRequest, resolve, select_combinations
from app.domain.games import LotteryGameConfig
from app.domain.models import DrawResult
from app.logging_config import log_event

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]


class BacktestCancelled(Exception):
    pass


@dataclass
class TargetResult:
    draw_id: str
    draw_date: str
    actual: List[int]
    history: int
    seed: int
    mean: Dict[str, float]
    best: Dict[str, int]


@dataclass
class BacktestResult:
    game: str
    config: dict
    targets: List[TargetResult]
    skipped: int
    summary: Summary
    dataset_fingerprint: str
    duration_s: float
    notes: List[str] = field(default_factory=list)

    def to_dict(self, include_targets: bool = True) -> dict:
        d = {
            "game": self.game,
            "config": self.config,
            "n_targets": len(self.targets),
            "skipped": self.skipped,
            "first_target": self.targets[0].draw_date if self.targets else None,
            "last_target": self.targets[-1].draw_date if self.targets else None,
            "summary": self.summary.to_dict(),
            "dataset_fingerprint": self.dataset_fingerprint,
            "duration_s": self.duration_s,
            "notes": self.notes,
            "sampler": SAMPLER,
            "numpy_version": np.__version__,
        }
        if include_targets:
            d["targets"] = [t.__dict__ for t in self.targets]
        return d


class Backtester:
    def __init__(self, engine_factory: Callable[..., FeatureEngine] = FeatureEngine) -> None:
        self._engine_factory = engine_factory

    def run(
        self,
        game: LotteryGameConfig,
        draws: Sequence[DrawResult],
        config: BacktestConfig,
        progress: Optional[ProgressCallback] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> BacktestResult:
        started = time.perf_counter()
        ordered = sorted(draws, key=lambda d: (d.draw_date, d.draw_id))
        if config.training_start:
            ordered = [d for d in ordered if d.draw_date >= config.training_start]
        dates = [d.draw_date for d in ordered]
        targets = [d for d in ordered if config.start <= d.draw_date <= config.end][:: config.step]

        resolved = {}
        for spec in config.strategies:
            req = GenerationRequest(game=game, strategy=spec.strategy, count=config.combinations_per_draw, seed=0,
                                    feature_config=config.feature_config, weights=spec.weights,
                                    intensity=spec.intensity, gap_mode=spec.gap_mode, rules=config.rules)
            resolved[spec.label] = resolve(req)
        # One feature computation per target serves every strategy: include pairs if any needs them.
        feature_config = config.feature_config
        if any(r.feature_config.include_pairs for r in resolved.values()):
            feature_config = replace(feature_config, include_pairs=True)
        engine = self._engine_factory(feature_config)

        acc = {label: StrategyAccumulator(game.numbers_per_draw) for label in resolved}
        rows: List[TargetResult] = []
        skipped = 0
        log_event(logger, "backtest.start", game=game.key, targets=len(targets), start=config.start,
                  end=config.end, strategies=list(resolved), per_draw=config.combinations_per_draw)

        for i, target in enumerate(targets):
            if should_cancel and should_cancel():
                raise BacktestCancelled()
            cut = bisect_left(dates, target.draw_date)  # index of first draw on/after the target date
            history = ordered[:cut]
            if config.history_window:
                history = history[-config.history_window:]
            if len(history) < config.min_history:
                skipped += 1
                continue

            features = engine.compute(game, history, as_of=target.draw_date, fingerprint=False)
            seed = config.seed_for(target.draw_id)
            means, bests = {}, {}
            for label, r in resolved.items():
                scores = r.scorer.score(game, features)
                combos, _, _ = select_combinations(game, scores, features, r.rules,
                                                   config.combinations_per_draw, seed, with_scores=False)
                matches = match_counts(combos, target.numbers)  # the only use of the target's numbers
                acc[label].add(matches)
                means[label] = float(matches.mean())
                bests[label] = int(matches.max())
            rows.append(TargetResult(target.draw_id, target.draw_date.isoformat(), list(target.numbers),
                                     len(history), seed, means, bests))
            if progress and (i % 10 == 0 or i == len(targets) - 1):
                progress(i + 1, len(targets))

        notes = []
        if skipped:
            notes.append(f"{skipped} target draw(s) skipped: fewer than {config.min_history} prior draws.")
        if not rows:
            notes.append("No target draws were evaluated.")
        summary = summarize(game, acc, config.baseline)
        duration = time.perf_counter() - started
        log_event(logger, "backtest.done", game=game.key, evaluated=len(rows), skipped=skipped,
                  seconds=round(duration, 1))
        return BacktestResult(
            game=game.key,
            config=config.to_dict(),
            targets=rows,
            skipped=skipped,
            summary=summary,
            # Every draw the run could read: history plus targets up to the period end.
            dataset_fingerprint=dataset_fingerprint(game, [d for d in ordered if d.draw_date <= config.end]),
            duration_s=duration,
            notes=notes,
        )
