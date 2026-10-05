from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game          TEXT    NOT NULL,
    draw_id       TEXT    NOT NULL,
    draw_date     TEXT    NOT NULL,          -- ISO date, YYYY-MM-DD
    numbers_json  TEXT    NOT NULL,          -- sorted JSON array of main numbers
    bonus_number  INTEGER,                   -- Power 6/55 only
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (game, draw_id)
);
CREATE INDEX IF NOT EXISTS idx_draws_game      ON draws (game);
CREATE INDEX IF NOT EXISTS idx_draws_draw_date ON draws (draw_date);
CREATE INDEX IF NOT EXISTS idx_draws_draw_id   ON draws (draw_id);
CREATE INDEX IF NOT EXISTS idx_draws_game_date ON draws (game, draw_date);

-- Date ranges already fetched from a provider. Kept merged (non-overlapping) per game,
-- so an incremental fetch only requests the uncovered parts of a range.
CREATE TABLE IF NOT EXISTS fetch_coverage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game        TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_coverage_game ON fetch_coverage (game);

-- One row per generation run. params_json holds everything needed to reproduce it
-- (dataset fingerprint, feature config, strategy, weights, rules, seed, sampler version).
CREATE TABLE IF NOT EXISTS generation_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    game                TEXT    NOT NULL,
    start_date          TEXT,
    end_date            TEXT,
    strategy            TEXT    NOT NULL,
    seed                INTEGER NOT NULL,
    count               INTEGER NOT NULL,
    dataset_fingerprint TEXT    NOT NULL,
    params_json         TEXT    NOT NULL,
    combinations_json   TEXT    NOT NULL,
    notes_json          TEXT    NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_sessions_game_created ON generation_sessions (game, created_at);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    status      TEXT    NOT NULL,              -- running | done | failed
    game        TEXT    NOT NULL,
    params_json TEXT    NOT NULL,
    progress    INTEGER NOT NULL DEFAULT 0,
    total       INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_backtests_game ON backtest_runs (game, id);
"""


def connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a connection. ``":memory:"`` is accepted for tests."""
    in_memory = str(db_path) == ":memory:"
    if not in_memory:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not in_memory:
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(SCHEMA)
