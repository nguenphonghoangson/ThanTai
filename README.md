# Vietlott Analyzer

Historical Vietlott draw analysis and statistically weighted candidate generation for
Mega 6/45 and Power 6/55.

This is an experimental statistics tool. It does not predict lottery results. Every scoring
strategy is backtested against a uniform random baseline. So far, no strategy has shown a
consistent advantage over random selection (see [Findings](#findings)).

## Quick start (Python 3.9+)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app fetch --game mega645 --from 2016-01-01
.venv/bin/python -m app fetch --game power655 --from 2016-01-01
.venv/bin/python -m app import --game power655 --file data/manual/power655.jsonl
.venv/bin/python -m app serve          # http://127.0.0.1:8000
```

## Dashboard

1. **Controls.** Game, date range, analysis window, strategy, scoring weights, combination
   filters, count and seed.
2. **Fetch data.** Downloads only the date ranges not already stored. A data-quality note
   lists draws missing from the source.
3. **Analyze.** Statistics and charts: frequency, recent frequency, gap, sum, odd/even and
   low/high, each compared with what uniform random draws would give. Also shows number
   scores with a per-number breakdown.
4. **Generate.** Seeded combinations with combination scores and flags. Includes "Generate
   again", "Use this seed", "Export CSV" and "Verify reproducible".
5. **Backtest.** Walk-forward evaluation of the strategies against the random baseline, with
   a cumulative-difference chart, significance tests and a per-draw CSV.

## CLI

```bash
python -m app games | initdb | status
python -m app fetch    --game mega645 --from 2020-01-01 --to 2026-10-01 [--force]
python -m app import   --game power655 --file extra.jsonl
python -m app analyze  --game mega645 --from 2020-01-01 [--window 100] [--sort frequency] [--triples] [--json]
python -m app score    --game mega645 --strategy balanced [--gap-mode recency] [--explain 7 22] [--json]
python -m app generate --game mega645 --strategy balanced --count 100 [--seed 12345] [--oversample 3] [--no-filters] [--csv out.csv]
python -m app backtest --game mega645 --from 2022-01-01 [--per-draw 100] [--seed 7] [--strategies frequency balanced] [--csv out.csv]
python -m app serve    [--port 8000] [--reload]
```

Environment variables:

| Variable | Default |
|---|---|
| `VIETLOTT_DB` | `data/vietlott.sqlite3` |
| `VIETLOTT_PROVIDER` | `github`; `file` reads `data/import/<game>.jsonl` |
| `VIETLOTT_DATASET_URL` | the vietvudanh/vietlott-data dataset |
| `VIETLOTT_CACHE_MAX_AGE` | 3600 (seconds) |
| `VIETLOTT_SETTLE_DAYS` | 2 |
| `VIETLOTT_LOG_LEVEL` | INFO |
| `VIETLOTT_HOST`, `VIETLOTT_PORT` | 127.0.0.1, 8000 |

## How it works

```
Provider ─► Repository (SQLite) ─► FeatureEngine ─► Scorer ─► CombinationGenerator ─► Backtester
 fetch       incremental cache      describes only    weights    seeded sampling        walk-forward
```

| Layer | Module | Notes |
|---|---|---|
| Games | `domain/games.py` | Range, draw size and low/high split all come from `LotteryGameConfig`. Adding a game means adding one config. |
| Data | `data/` | Providers are swappable. Downloads are cached with ETag revalidation and fall back to the cached copy if the network fails. Records are validated, and draws whose date is out of order with their neighbours are rejected. Coverage is tracked so only missing ranges are fetched. Stored draws are never overwritten; conflicting updates are reported. |
| Features | `analysis/features/` | Pure description of past draws: frequency, recent windows, gap, average gap, gap ratio, hot/cold, consistency, odd/even and low/high (each with its uniform-draw expectation), sum stats, pairs, and optional triples (flagged as sparse). `as_of=d` means only draws dated strictly before `d` are used. |
| Scoring | `analysis/scoring/` | `score = max(0.05, 1 + intensity · Σ wᵢ·zᵢ)`, where each component is standardized across all numbers. 1.0 is neutral. Scores are not probabilities. Strategies: frequency, recent, balanced, random. The `NumberScorer` protocol is where a future ML scorer would plug in. |
| Combinations | `analysis/combination/` | Numbers are drawn without replacement, weighted by score (Gumbel-top-k sampling on numpy's PCG64 generator). Combination score = Σ number scores + pair term − filter penalties. Penalties are labelled filters, not claims that a draw can't look that way. |
| Pipeline | `analysis/pipeline.py` | The single definition of a generation, shared by the web app, the CLI and the backtester. |
| Backtest | `analysis/backtesting/` | Walk-forward over target draws. All strategies share a per-draw seed. Each strategy is compared with random by a paired test on per-draw mean matches (95% CI, Bonferroni correction) and against the exact hypergeometric expectation. |
| Storage | `database/sqlite.py` | Tables: `draws`, `fetch_coverage`, `generation_sessions`, `backtest_runs` |
| Web | `api/`, `web/` | FastAPI and Jinja. Vanilla JS split by dashboard section; SVG charts in `charts.js` with no external dependencies. |

**Reproducibility.** Every generation session stores everything needed to repeat it: data
fingerprint (a hash of the exact draws used), date range, feature settings, strategy,
weights as entered and as applied, intensity, gap mode, filter rules, seed, count, sampling
method and numpy version. `POST /api/sessions/{id}/reproduce` regenerates from those
settings and confirms the output is identical, or reports that the stored draws changed.

**No look-ahead (leakage tests).** These check that a backtest never uses information from
the future:
- Every history passed to the feature engine ends strictly before its target's date.
- Changing the target draw and every later draw does not change what was generated for that
  target.
- Results for earlier targets do not depend on later data.

**Planted-signal test.** On synthetic draws biased toward 8 numbers, the frequency strategy
must beat random significantly. This shows the backtest can detect a real effect when one
exists.

## Data source

The default source is the public
[vietvudanh/vietlott-data](https://github.com/vietvudanh/vietlott-data) JSONL dataset, refreshed
daily. The official vietlott.vn site is behind a Cloudflare challenge and is not used for bulk
fetching.

Known gaps in the source, which `status` and the dashboard report:

- **Mega 6/45 draws #1–#197** (2016-07-20 → 2017-10-22) are absent; history starts at #198.
- **Power 6/55 draw #944** is malformed in the source and is rejected. The official result
  (2023-10-14, `08 23 30 34 38 47 | 10`) is kept in `data/manual/power655.jsonl`; import it as
  shown in Quick start.

Other missing draws can be added in the same format:
`{"id": "00944", "date": "2023-10-14", "result": [8, 23, 30, 34, 38, 47, 10]}`.
For Power 6/55, the last value in `result` is the bonus ball.

## Findings

These are walk-forward backtests over 2022–2026, 100 combinations per draw, with several base
seeds.

- **Matches with real data:** stored draws fall on each game's fixed draw days, and number
  frequencies, odd/even and low/high splits and sums all look as uniform random draws would.
- **Random baseline:** averages 0.80 matches per combination (Mega) and 0.655 (Power), equal to
  the exact theoretical value. This confirms the backtest itself works.
- **Strategies:** frequency, recent and balanced show no consistent, significant difference
  from random. Individual runs occasionally cross p(adj) < 0.05 by chance. The dashboard flags
  those and asks for a re-run with another seed and a later period.

## Performance

A full Mega 6/45 backtest (741 draws × 4 strategies × 100 combinations) takes about 2.6 s on
this machine. Per-call events are logged at DEBUG; INFO stays at one line per user action.

## Development

```bash
.venv/bin/python -m pytest -q        # 189 tests
.venv/bin/python -m pyflakes app     # lint
```
