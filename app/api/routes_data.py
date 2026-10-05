from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_db, get_repository, get_sync_service, resolve_game
from app.data.errors import DataFetchError
from app.data.repository import SqliteCoverageRepository, SqliteDrawRepository
from app.data.sync import DrawSyncService
from app.domain.games import LotteryGameConfig, list_games

router = APIRouter(prefix="/api", tags=["data"])


class DrawOut(BaseModel):
    draw_id: str
    draw_date: date
    numbers: List[int]
    bonus_number: Optional[int] = None


class DataSummary(BaseModel):
    game: str
    total_draws: int
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    first_draw_id: Optional[str] = None
    last_draw_id: Optional[str] = None
    # Draws numbered before the first stored one (the source does not have them).
    missing_before_first: int = 0
    # Draw numbers absent between the first and last stored draw.
    missing_draw_count: int = 0
    missing_draw_ids: List[int] = []
    covered_ranges: List[List[date]] = []


class FetchRequest(BaseModel):
    game: str
    start: date
    end: date
    force: bool = False


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/games")
def games() -> List[dict]:
    return [g.to_dict() for g in list_games()]


@router.get("/data/summary", response_model=DataSummary)
def data_summary(
    game: LotteryGameConfig = Depends(resolve_game),
    conn=Depends(get_db),
) -> DataSummary:
    repo = SqliteDrawRepository(conn)
    bounds = repo.date_bounds(game)
    ids = repo.first_last_draw_ids(game)
    gaps = repo.draw_id_gaps(game)
    return DataSummary(
        game=game.key,
        total_draws=repo.count(game),
        first_date=bounds[0] if bounds else None,
        last_date=bounds[1] if bounds else None,
        first_draw_id=ids[0] if ids else None,
        last_draw_id=ids[1] if ids else None,
        missing_before_first=int(ids[0]) - 1 if ids else 0,
        missing_draw_count=len(gaps),
        missing_draw_ids=gaps[:50],
        covered_ranges=[[s, e] for s, e in SqliteCoverageRepository(conn).get(game)],
    )


@router.post("/data/fetch")
def fetch_data(body: FetchRequest, sync: DrawSyncService = Depends(get_sync_service)) -> dict:
    game = resolve_game(body.game)
    if body.start > body.end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    try:
        report = sync.sync(game, body.start, body.end, force=body.force)
    except DataFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return report.to_dict()


@router.get("/data/draws", response_model=List[DrawOut])
def draws(
    game: LotteryGameConfig = Depends(resolve_game),
    start: Optional[date] = Query(None, alias="from"),
    end: Optional[date] = Query(None, alias="to"),
    repo: SqliteDrawRepository = Depends(get_repository),
) -> List[DrawOut]:
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="'from' must be on or before 'to'")
    return [
        DrawOut(draw_id=d.draw_id, draw_date=d.draw_date, numbers=list(d.numbers), bonus_number=d.bonus_number)
        for d in repo.get_draws(game, start, end)
    ]
