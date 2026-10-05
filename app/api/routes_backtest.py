"""Walk-forward backtests, run as background jobs (one at a time) with progress in SQLite."""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.analysis.backtesting import Backtester, BacktestConfig, StrategySpec
from app.analysis.features import FeatureConfig
from app.analysis.scoring import RANDOM
from app.api.deps import get_db, resolve_game
from app.api.routes_analysis import merge_weights
from app.api.schemas import RulesBody, rules_from_body
from app.data.backtests import SqliteBacktestRepository, backtest_csv
from app.data.repository import SqliteDrawRepository
from app.database.sqlite import connect
from app.domain.games import LotteryGameConfig
from app.logging_config import log_event

router = APIRouter(prefix="/api/backtests", tags=["backtest"])
logger = logging.getLogger(__name__)

PRESET_LABELS = ("frequency", "recent", "balanced")


class CustomStrategyBody(BaseModel):
    base: str = "balanced"
    weights: Dict[str, Optional[float]] = {}
    intensity: Optional[float] = Field(None, ge=0, le=5)
    gap_mode: Optional[str] = None


class BacktestBody(BaseModel):
    game: str
    start: date
    end: date
    training_start: Optional[date] = None
    strategies: List[str] = list(PRESET_LABELS)  # the random baseline is always included
    custom: Optional[CustomStrategyBody] = None
    combinations_per_draw: int = Field(100, ge=1, le=1000)
    min_history: int = Field(100, ge=10, le=5000)
    history_window: Optional[int] = Field(None, ge=10, le=5000)
    step: int = Field(1, ge=1, le=100)
    base_seed: int = Field(20240101, ge=0, lt=2**63)
    window: int = Field(100, ge=1, le=5000)
    rules: RulesBody = RulesBody()


def build_config(body: BacktestBody) -> BacktestConfig:
    unknown = set(body.strategies) - set(PRESET_LABELS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown strategies: {', '.join(sorted(unknown))}")
    specs = [StrategySpec(RANDOM, RANDOM)] + [StrategySpec(s, s) for s in PRESET_LABELS if s in body.strategies]
    if body.custom:
        if body.custom.base not in PRESET_LABELS:
            raise HTTPException(status_code=422, detail="custom.base must be frequency, recent or balanced")
        weights = merge_weights(body.custom.base, body.custom.weights)
        specs.append(StrategySpec("custom", body.custom.base, weights, body.custom.intensity, body.custom.gap_mode))
    try:
        return BacktestConfig(
            start=body.start, end=body.end, training_start=body.training_start, strategies=tuple(specs),
            combinations_per_draw=body.combinations_per_draw, min_history=body.min_history,
            history_window=body.history_window, step=body.step, base_seed=body.base_seed,
            feature_config=FeatureConfig(hot_cold_window=body.window), rules=rules_from_body(body.rules),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def run_job(db_path: Path, run_id: int, game: LotteryGameConfig, config: BacktestConfig) -> None:
    """Executed in the worker thread with its own connection."""
    conn = connect(db_path)
    runs = SqliteBacktestRepository(conn)
    last_write = [0.0]

    def progress(done: int, total: int) -> None:
        now = time.monotonic()
        if now - last_write[0] > 0.5 or done == total:
            runs.progress(run_id, done, total)
            last_write[0] = now

    try:
        draws = SqliteDrawRepository(conn).get_draws(game, config.training_start, config.end)
        result = Backtester().run(game, draws, config, progress=progress)
        runs.finish(run_id, result.to_dict())
    except Exception as exc:  # noqa: BLE001 — any failure must be recorded on the run
        log_event(logger, "backtest.failed", logging.ERROR, run_id=run_id, error=repr(exc))
        runs.fail(run_id, f"{type(exc).__name__}: {exc}")
    finally:
        conn.close()


@router.post("", status_code=202)
def start_backtest(body: BacktestBody, request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    game = resolve_game(body.game)
    config = build_config(body)
    repo = SqliteDrawRepository(conn)
    targets = [d for d in repo.get_draws(game, config.start, config.end)][:: config.step]
    if not targets:
        raise HTTPException(status_code=422, detail="No stored draws in the backtest period. Fetch data first.")
    run_id = SqliteBacktestRepository(conn).create(game.key, config.to_dict())
    request.app.state.executor.submit(run_job, request.app.state.settings.db_path, run_id, game, config)
    log_event(logger, "backtest.queued", run_id=run_id, game=game.key, targets=len(targets))
    return {"id": run_id, "status": "running", "targets": len(targets)}


@router.get("")
def list_backtests(game: Optional[str] = None, limit: int = 20, conn: sqlite3.Connection = Depends(get_db)) -> list:
    if game:
        resolve_game(game)
    return [r.summary() for r in SqliteBacktestRepository(conn).list(game, min(max(limit, 1), 100))]


def _load(conn: sqlite3.Connection, run_id: int):
    run = SqliteBacktestRepository(conn).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Backtest {run_id} not found")
    return run


@router.get("/{run_id}")
def get_backtest(run_id: int, targets: bool = False, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    return _load(conn, run_id).to_dict(include_targets=targets)


@router.get("/{run_id}/export.csv")
def export_backtest(run_id: int, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    run = _load(conn, run_id)
    if run.result is None:
        raise HTTPException(status_code=409, detail=f"Backtest {run_id} is {run.status}")
    return Response(backtest_csv(run), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="vietlott_{run.game}_backtest_{run.id}.csv"'})
