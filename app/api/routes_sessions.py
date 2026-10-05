"""Combination generation and stored sessions."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.analysis.features import FeatureConfig, InsufficientDataError
from app.analysis.pipeline import GenerationRequest, generate, new_seed, request_from_params
from app.api.deps import get_db, resolve_game
from app.api.routes_analysis import merge_weights
from app.api.schemas import RulesBody, rules_from_body
from app.data.repository import SqliteDrawRepository
from app.data.sessions import SqliteSessionRepository, StoredSession, session_csv

router = APIRouter(prefix="/api", tags=["generation"])


class GenerateBody(BaseModel):
    game: str
    start: Optional[date] = None
    end: Optional[date] = None
    window: int = Field(100, ge=1, le=5000)
    strategy: str = "balanced"
    weights: Dict[str, Optional[float]] = {}
    intensity: Optional[float] = Field(None, ge=0, le=5)
    gap_mode: Optional[str] = None
    count: int = Field(100, ge=1, le=1000)
    seed: Optional[int] = Field(None, ge=0, lt=2**63)
    rules: RulesBody = RulesBody()


def _load(conn: sqlite3.Connection, session_id: int) -> StoredSession:
    session = SqliteSessionRepository(conn).get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session


@router.post("/generate", status_code=201)
def generate_combinations(body: GenerateBody, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    game = resolve_game(body.game)
    if body.start and body.end and body.start > body.end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    weights = merge_weights(body.strategy, body.weights)
    try:
        request = GenerationRequest(
            game=game, strategy=body.strategy, count=body.count,
            seed=body.seed if body.seed is not None else new_seed(),
            start=body.start, end=body.end, feature_config=FeatureConfig(hot_cold_window=body.window),
            weights=weights, intensity=body.intensity, gap_mode=body.gap_mode, rules=rules_from_body(body.rules),
        )
        result = generate(SqliteDrawRepository(conn).get_draws(game, body.start, body.end), request)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=f"{exc}. Fetch data for this range first.") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    repo = SqliteSessionRepository(conn)
    return repo.get(repo.save(result)).to_dict()


@router.get("/sessions")
def list_sessions(game: Optional[str] = None, limit: int = 20, conn: sqlite3.Connection = Depends(get_db)) -> list:
    if game:
        resolve_game(game)
    return [s.summary() for s in SqliteSessionRepository(conn).list(game, min(max(limit, 1), 100))]


@router.get("/sessions/{session_id}")
def get_session(session_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    return _load(conn, session_id).to_dict()


@router.get("/sessions/{session_id}/export.csv")
def export_session(session_id: int, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    session = _load(conn, session_id)
    filename = f"vietlott_{session.game}_{session.strategy}_seed{session.seed}_s{session.id}.csv"
    return Response(
        session_csv(session),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/sessions/{session_id}/reproduce")
def reproduce_session(session_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Regenerate from the stored parameters and compare with the stored combinations."""
    session = _load(conn, session_id)
    game = resolve_game(session.game)
    request = request_from_params(game, session.params)
    try:
        result = generate(SqliteDrawRepository(conn).get_draws(game, request.start, request.end), request)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    stored = [c["numbers"] for c in session.combinations]
    fresh = [c.numbers for c in result.combinations]
    same_data = result.params["dataset_fingerprint"] == session.dataset_fingerprint
    return {
        "session_id": session.id,
        "matches": stored == fresh,
        "dataset_matches": same_data,
        "stored_fingerprint": session.dataset_fingerprint,
        "current_fingerprint": result.params["dataset_fingerprint"],
        "differing_rows": sum(1 for a, b in zip(stored, fresh) if a != b) + abs(len(stored) - len(fresh)),
        "note": None if same_data else "Stored draws for this range have changed since the session was created.",
    }
