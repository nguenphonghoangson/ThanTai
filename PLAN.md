# Vietlott Analyzer — Implementation Plan

Experimental historical-statistics tool. It does not predict lottery results; every
scoring method must be backtested against a uniform random baseline.

## Status (2026-10-05)

All eight phases are complete; 189 tests pass. The current architecture and usage are in
`README.md`; the "Phase 1 file layout" section below is the original plan and has since grown
(sessions, backtests, charts, split frontend scripts).

## Constraints

- Runtime: Python 3.9 (system Python on this machine) → code avoids 3.10+ syntax
  at runtime (`Optional[...]` in FastAPI/pydantic signatures, `from __future__ import annotations` elsewhere).
- Stack: FastAPI, SQLite (stdlib `sqlite3`), Jinja2, vanilla JS/CSS, pandas/numpy for analysis.
- No global mutable state: `create_app(settings)` factory, per-request SQLite connection.

## Pipeline

```
Provider (fetch) → Repository (SQLite cache) → FeatureEngine → Scorer(strategy, weights)
      → CombinationGenerator(seed) → CombinationScorer → Backtester(walk-forward, strict "<" cutoff)
```

Each stage is a small module with a narrow input/output type, so ML scorers can later
plug in at the Scorer stage and be backtested the same way.

## Phases

| Phase | Scope | Exit check |
|---|---|---|
| 1 | Project skeleton, `LotteryGameConfig` + registry, `DrawResult` + validation, SQLite schema + repository, FastAPI app, dashboard shell, CLI skeleton, logging, tests | `pytest` green, server serves `/` and `/api/games` |
| 2 | `LotteryDataProvider` implementation(s), incremental fetch (only missing ranges), fetch log, network/malformed-data handling | Real Mega 6/45 + Power 6/55 history stored and spot-checked |
| 3 | Feature engine: frequency, recent windows, gap, avg gap, gap deviation, hot/cold, odd/even, low/high, sum stats, pairs (optional), triples (optional) | Unit tests on hand-computed fixtures |
| 4 | Scoring engine: per-feature normalized components, `ScoringWeights`, strategies Frequency / Recent / Balanced / Random; score breakdown | Determinism tests |
| 5 | Combination generator (weighted sampling w/o replacement, unique, seeded) + combination scoring with configurable penalties; analysis sessions persisted | Validity + reproducibility tests |
| 6 | Walk-forward backtester, match distribution metrics, strategy comparison vs random | Leakage tests (cutoff is strictly `<`) |
| 7 | Dashboard charts, score table sorting, breakdown view, CSV export | Manual UI check |
| 8 | Cleanup, performance (vectorized features), docs | — |

## Phase 1 file layout

```
app/
  __main__.py          CLI (games, initdb, serve; fetch/analyze/generate/backtest stubbed)
  main.py              create_app()
  settings.py          Settings (db path, host/port) from env
  logging_config.py    JSON structured logging
  domain/games.py      LotteryGameConfig + GAMES registry
  domain/models.py     DrawResult + validate_draw
  domain/interfaces.py LotteryDataProvider, DrawRepository protocols
  database/sqlite.py   connect(), init_schema()
  data/repository.py   SqliteDrawRepository
  api/routes_data.py   /api/health, /api/games, /api/data/summary, /api/data/draws
  api/deps.py          per-request SQLite connection, game resolution
                       (routes_analysis.py / routes_backtest.py added in Phases 3-6)
  web/templates, web/static
  tests/               pytest suite
```
