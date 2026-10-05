from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.analysis.features import FeatureConfig, FeatureEngine, FeatureSet, InsufficientDataError
from app.analysis.scoring.models import COMPONENTS
from app.analysis.scoring import (
    ScoringWeights, UnknownStrategyError, build_scorer, get_preset, list_strategies,
)
from app.api.deps import get_repository, resolve_game
from app.data.repository import SqliteDrawRepository
from app.domain.games import LotteryGameConfig

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def summary(fs: FeatureSet, numbers_per_draw: int) -> dict:
    avg_odd = fs.odd_even.mean
    return {
        "total_draws": fs.n_draws,
        "total_numbers": fs.n_draws * numbers_per_draw,
        "average_sum": fs.sums.mean,
        "theoretical_sum": fs.sums.theoretical_mean,
        "average_odd": avg_odd,
        "average_even": numbers_per_draw - avg_odd,
        "average_low": fs.low_high.mean,
        "average_high": numbers_per_draw - fs.low_high.mean,
    }


@router.get("/features")
def features(
    game: LotteryGameConfig = Depends(resolve_game),
    start: Optional[date] = Query(None, alias="from"),
    end: Optional[date] = Query(None, alias="to"),
    window: int = Query(100, ge=1, le=5000, description="Hot/cold window in draws"),
    pairs: bool = True,
    triples: bool = False,
    repo: SqliteDrawRepository = Depends(get_repository),
) -> dict:
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="'from' must be on or before 'to'")
    config = FeatureConfig(hot_cold_window=window, include_pairs=pairs, include_triples=triples)
    try:
        fs = FeatureEngine(config).compute(game, repo.get_draws(game, start, end))
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=f"{exc}. Fetch data for this range first.") from None
    return {"summary": summary(fs, game.numbers_per_draw), "features": fs.to_dict()}


def merge_weights(strategy: str, overrides: Dict[str, Optional[float]]) -> Optional[ScoringWeights]:
    """Preset weights with any provided overrides applied; None when nothing is overridden."""
    try:
        preset = get_preset(strategy)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from None
    unknown = set(overrides) - set(COMPONENTS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown weight(s): {', '.join(sorted(unknown))}")
    if all(v is None for v in overrides.values()):
        return None
    base = preset.weights.as_dict()
    try:
        weights = ScoringWeights(**{k: overrides[k] if overrides.get(k) is not None else base[k] for k in COMPONENTS})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if weights.total == 0 and not preset.uniform:
        raise HTTPException(status_code=422, detail="At least one weight must be positive")
    return weights


@router.get("/strategies")
def strategies() -> list:
    return list_strategies()


@router.get("/scores")
def scores(
    game: LotteryGameConfig = Depends(resolve_game),
    start: Optional[date] = Query(None, alias="from"),
    end: Optional[date] = Query(None, alias="to"),
    window: int = Query(100, ge=1, le=5000),
    strategy: str = "balanced",
    w_frequency: Optional[float] = Query(None, ge=0),
    w_recent: Optional[float] = Query(None, ge=0),
    w_gap: Optional[float] = Query(None, ge=0),
    w_pair: Optional[float] = Query(None, ge=0),
    w_historical: Optional[float] = Query(None, ge=0),
    intensity: Optional[float] = Query(None, ge=0, le=5),
    gap_mode: Optional[str] = None,
    repo: SqliteDrawRepository = Depends(get_repository),
) -> dict:
    """Per-number scores with component breakdown. Omitted weights fall back to the preset."""
    weights = merge_weights(strategy, {"frequency": w_frequency, "recent_frequency": w_recent, "gap": w_gap,
                                       "pair": w_pair, "historical": w_historical})
    try:
        scorer = build_scorer(strategy, weights=weights, intensity=intensity, gap_mode=gap_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    config = FeatureConfig(hot_cold_window=window, include_pairs=scorer.config.weights.pair > 0)
    try:
        fs = FeatureEngine(config).compute(game, repo.get_draws(game, start, end))
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=f"{exc}. Fetch data for this range first.") from None
    result = scorer.score(game, fs)
    body = result.to_dict()
    for row, nf in zip(body["scores"], fs.numbers):
        row.update(frequency=nf.frequency, recent=nf.recent[window], gap=nf.gap, seen=nf.seen)
    body["strategy"] = strategy
    body["customized"] = not scorer.config.uniform and (
        weights is not None or intensity is not None or gap_mode is not None)
    return body
