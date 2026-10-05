"""FastAPI dependencies. One SQLite connection per request; no module-level state."""
from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, HTTPException, Request

from app.data.repository import SqliteCoverageRepository, SqliteDrawRepository
from app.data.sync import DrawSyncService
from app.database.sqlite import connect
from app.domain.games import LotteryGameConfig, UnknownGameError, get_game


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_repository(conn: sqlite3.Connection = Depends(get_db)) -> SqliteDrawRepository:
    return SqliteDrawRepository(conn)


def resolve_game(game: str) -> LotteryGameConfig:
    try:
        return get_game(game)
    except UnknownGameError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from None


def get_sync_service(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> DrawSyncService:
    state = request.app.state
    return DrawSyncService(
        provider=state.provider,
        draws=SqliteDrawRepository(conn),
        coverage=SqliteCoverageRepository(conn),
        today=state.today(),
        settle_days=state.settings.settle_days,
    )
