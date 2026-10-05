"""Development CLI: ``python -m app <command>``."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import List, Optional

from app.data.sync import vietnam_today
from app.domain.games import GAMES, get_game
from app.settings import Settings


def _add_range_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--game", choices=sorted(GAMES), default="mega645")
    p.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2020, 1, 1))
    p.add_argument("--to", dest="end", type=date.fromisoformat, default=vietnam_today())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="Vietlott Analyzer CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("games", help="List supported games")
    sub.add_parser("initdb", help="Create the SQLite schema")

    serve = sub.add_parser("serve", help="Run the web dashboard")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")

    fetch = sub.add_parser("fetch", help="Fetch draws for a date range (only missing ranges unless --force)")
    _add_range_args(fetch)
    fetch.add_argument("--force", action="store_true", help="Ignore recorded coverage and re-download")

    status = sub.add_parser("status", help="Show stored data per game")
    status.add_argument("--game", choices=sorted(GAMES))

    imp = sub.add_parser("import", help="Import draws from a local JSONL file (same format as the dataset)")
    imp.add_argument("--game", choices=sorted(GAMES), required=True)
    imp.add_argument("--file", required=True)

    an = sub.add_parser("analyze", help="Compute historical features for stored draws")
    _add_range_args(an)
    an.add_argument("--window", type=int, default=100, help="hot/cold window in draws")
    an.add_argument("--no-pairs", dest="pairs", action="store_false")
    an.add_argument("--triples", action="store_true")
    an.add_argument("--sort", choices=["number", "frequency", "recent", "gap"], default="number")
    an.add_argument("--json", action="store_true", help="print the full feature set as JSON")

    sc = sub.add_parser("score", help="Score every number with a strategy and show the breakdown")
    _add_range_args(sc)
    sc.add_argument("--strategy", choices=["frequency", "recent", "balanced", "random"], default="balanced")
    sc.add_argument("--window", type=int, default=100)
    sc.add_argument("--gap-mode", choices=["overdue", "recency"])
    sc.add_argument("--intensity", type=float)
    sc.add_argument("--explain", type=int, nargs="*", default=None,
                    help="numbers to break down (default: the top 3)")
    sc.add_argument("--json", action="store_true")

    gen = sub.add_parser("generate", help="Generate candidate combinations and store the session")
    _add_range_args(gen)
    gen.add_argument("--strategy", choices=["frequency", "recent", "balanced", "random"], default="balanced")
    gen.add_argument("--count", type=int, default=100)
    gen.add_argument("--seed", type=int, help="omit for a random seed (printed)")
    gen.add_argument("--window", type=int, default=100)
    gen.add_argument("--oversample", type=int, default=1, help="keep the best COUNT of COUNT×N by combination score")
    gen.add_argument("--no-filters", action="store_true", help="disable odd/even, low/high, spread and sum penalties")
    gen.add_argument("--csv", help="also write the session as CSV to this path")

    bt = sub.add_parser("backtest", help="Walk-forward backtest of strategies against the random baseline")
    bt.add_argument("--game", choices=sorted(GAMES), default="mega645")
    bt.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2022, 1, 1),
                    help="first target draw date")
    bt.add_argument("--to", dest="end", type=date.fromisoformat, default=vietnam_today(), help="last target draw date")
    bt.add_argument("--train-from", type=date.fromisoformat, help="ignore draws before this date (default: all)")
    bt.add_argument("--strategies", nargs="+", choices=["frequency", "recent", "balanced"],
                    default=["frequency", "recent", "balanced"], help="random baseline is always included")
    bt.add_argument("--per-draw", type=int, default=100, help="combinations generated per target draw")
    bt.add_argument("--min-history", type=int, default=100)
    bt.add_argument("--history-window", type=int, help="use only the last N prior draws (default: expanding)")
    bt.add_argument("--step", type=int, default=1)
    bt.add_argument("--seed", type=int, default=20240101)
    bt.add_argument("--window", type=int, default=100)
    bt.add_argument("--csv", help="write per-draw results to this path")
    bt.add_argument("--json", action="store_true")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()

    if args.command == "games":
        for g in GAMES.values():
            d = g.to_dict()
            print(f"{g.key:10} {g.name:12} {g.min_number}-{g.max_number}, pick {g.numbers_per_draw}, "
                  f"low {d['low_range'][0]}-{d['low_range'][1]}, high {d['high_range'][0]}-{d['high_range'][1]}")
        return 0

    if args.command == "initdb":
        from app.database.sqlite import connect, init_schema

        conn = connect(settings.db_path)
        init_schema(conn)
        conn.close()
        print(f"Schema ready at {settings.db_path}")
        return 0

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "app.main:create_app",
            factory=True,
            host=args.host or settings.host,
            port=args.port or settings.port,
            reload=args.reload,
        )
        return 0

    if args.command == "analyze":
        return _analyze(args, settings)
    if args.command == "score":
        return _score(args, settings)
    if args.command == "generate":
        return _generate(args, settings)
    if args.command == "backtest":
        return _backtest(args, settings)

    if args.command in ("fetch", "status", "import"):
        from app.logging_config import configure_logging

        configure_logging(settings.log_level)
        return _data_command(args, settings)

    raise AssertionError(f"unhandled command {args.command}")


def _data_command(args: argparse.Namespace, settings: Settings) -> int:
    from pathlib import Path

    from app.data.errors import DataFetchError
    from app.data.providers import build_provider
    from app.data.providers.jsonl_format import parse_jsonl
    from app.data.repository import SqliteCoverageRepository, SqliteDrawRepository
    from app.data.sync import DrawSyncService, vietnam_today
    from app.database.sqlite import connect, init_schema

    conn = connect(settings.db_path)
    init_schema(conn)
    draws = SqliteDrawRepository(conn)
    try:
        if args.command == "fetch":
            game = get_game(args.game)
            service = DrawSyncService(build_provider(settings), draws, SqliteCoverageRepository(conn),
                                      today=vietnam_today(), settle_days=settings.settle_days)
            try:
                r = service.sync(game, args.start, args.end, force=args.force)
            except DataFetchError as exc:
                print(f"Fetch failed: {exc}", file=sys.stderr)
                return 1
            if r.up_to_date:
                print(f"{game.name}: {args.start} → {r.requested[1]} already cached, nothing fetched.")
            else:
                print(f"{game.name}: fetched {len(r.fetched_ranges)} range(s) from {r.source}")
                print(f"  received {r.received}, inserted {r.inserted}, already stored {r.unchanged}")
            if r.stale_source:
                print("  WARNING: source unreachable, used an expired cached copy")
            _print_issues(r.conflicts, r.rejected)
        elif args.command == "import":
            game = get_game(args.game)
            parsed = parse_jsonl(game, Path(args.file).read_text(encoding="utf-8"), source=args.file)
            saved = draws.save_draws(game, parsed.draws)
            print(f"{game.name}: inserted {saved.inserted}, already stored {saved.unchanged}")
            _print_issues(saved.conflicts, [f"{x.ref}: {x.reason}" for x in parsed.rejected])
        else:
            for game in [get_game(args.game)] if args.game else GAMES.values():
                bounds, gaps = draws.date_bounds(game), draws.draw_id_gaps(game)
                ids = draws.first_last_draw_ids(game)
                if not bounds:
                    print(f"{game.name}: no data")
                    continue
                print(f"{game.name}: {draws.count(game)} draws, #{ids[0]} {bounds[0]} → #{ids[1]} {bounds[1]}, "
                      f"{len(gaps)} missing id(s){': ' + str(gaps[:20]) if gaps else ''}")
    finally:
        conn.close()
    return 0


def _analyze(args: argparse.Namespace, settings: Settings) -> int:
    import json

    from app.analysis.features import FeatureConfig, FeatureEngine, InsufficientDataError
    from app.data.repository import SqliteDrawRepository
    from app.database.sqlite import connect, init_schema
    from app.logging_config import configure_logging

    configure_logging(settings.log_level)
    game = get_game(args.game)
    conn = connect(settings.db_path)
    init_schema(conn)
    try:
        draws = SqliteDrawRepository(conn).get_draws(game, args.start, args.end)
    finally:
        conn.close()
    config = FeatureConfig(hot_cold_window=args.window, include_pairs=args.pairs, include_triples=args.triples)
    try:
        fs = FeatureEngine(config).compute(game, draws)
    except InsufficientDataError as exc:
        print(f"{exc}. Run 'python -m app fetch' first.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(fs.to_dict(), indent=2))
        return 0

    w = config.hot_cold_window
    print(f"{game.name}: {fs.n_draws} draws, #{fs.first_draw[0]} {fs.first_draw[1]} → #{fs.last_draw[0]} {fs.last_draw[1]}")
    print(f"Expected per number: rate {fs.expected_rate:.3f}/draw, gap {fs.expected_gap:.2f} draws\n")
    keys = {
        "number": lambda n: n.number,
        "frequency": lambda n: (-n.frequency, n.number),
        "recent": lambda n: (-n.recent[w], n.number),
        "gap": lambda n: (-n.gap, n.number),
    }
    print(f"{'No':>3} {'Freq':>5} {'Rate':>6} {'R' + str(w):>5} {'Gap':>4} {'AvgGap':>7} {'Gap/Avg':>8}  Temp")
    for n in sorted(fs.numbers, key=keys[args.sort]):
        avg = f"{n.average_gap:7.2f}" if n.average_gap is not None else "      –"
        dev = f"{n.gap_deviation:8.2f}" if n.gap_deviation is not None else "       –"
        print(f"{n.number:>3} {n.frequency:>5} {n.frequency_rate:6.3f} {n.recent[w]:>5} {n.gap:>4} {avg} {dev}  {n.temperature}")

    s = fs.sums
    print(f"\nSum: min {s.min}, max {s.max}, mean {s.mean:.1f} (theoretical {s.theoretical_mean:.1f}), "
          f"median {s.median:.0f}, std {s.std:.1f}, p5–p95 {s.percentiles[5]:.0f}–{s.percentiles[95]:.0f}")
    for dist, a, b in ((fs.odd_even, "odd", "even"), (fs.low_high, "low", "high")):
        k = len(dist.counts) - 1
        print(f"\n{a.capitalize()}/{b}   observed   expected")
        for x, (obs, exp) in enumerate(zip(dist.observed_pct, dist.expected_pct)):
            print(f"  {x} {a} / {k - x} {b}  {obs:6.1f}%   {exp:6.1f}%")
    for combo in (fs.pairs, fs.triples):
        if combo:
            label = "Pairs" if combo.size == 2 else "Triples"
            print(f"\nTop {label.lower()} (expected {combo.expected_count:.2f} each): " +
                  ", ".join(f"{'-'.join(f'{x:02d}' for x in c.numbers)}×{c.count}" for c in combo.top[:10]))
            if combo.note:
                print(f"  Note: {combo.note}")
    return 0


def _score(args: argparse.Namespace, settings: Settings) -> int:
    import json

    from app.analysis.features import FeatureConfig, FeatureEngine, InsufficientDataError
    from app.analysis.scoring import build_scorer
    from app.data.repository import SqliteDrawRepository
    from app.database.sqlite import connect, init_schema
    from app.logging_config import configure_logging

    configure_logging(settings.log_level)
    game = get_game(args.game)
    conn = connect(settings.db_path)
    init_schema(conn)
    try:
        draws = SqliteDrawRepository(conn).get_draws(game, args.start, args.end)
    finally:
        conn.close()
    scorer = build_scorer(args.strategy, intensity=args.intensity, gap_mode=args.gap_mode)
    features_cfg = FeatureConfig(hot_cold_window=args.window, include_pairs=scorer.config.weights.pair > 0)
    try:
        fs = FeatureEngine(features_cfg).compute(game, draws)
    except InsufficientDataError as exc:
        print(f"{exc}. Run 'python -m app fetch' first.", file=sys.stderr)
        return 1
    result = scorer.score(game, fs)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0

    w = args.window
    print(f"{game.name} · strategy {args.strategy} · {fs.n_draws} draws · dataset {fs.dataset_fingerprint}")
    print("Score = relative sampling weight (1.00 neutral), not a probability.\n")
    print(f"{'Rank':>4} {'No':>3} {'Score':>6} {'Freq':>5} {'R' + str(w):>5} {'Gap':>4}")
    for s in result.ranked():
        nf = fs.by_number(s.number)
        print(f"{s.rank:>4} {s.number:>3} {s.score:6.3f} {nf.frequency:>5} {nf.recent[w]:>5} {nf.gap:>4}")
    explain = args.explain if args.explain else [s.number for s in result.ranked()[:3]]
    for number in explain:
        s = next((x for x in result.scores if x.number == number), None)
        if s is None:
            continue
        print(f"\n{number:02d}")
        for c in s.components:
            raw = "n/a" if c.raw is None else f"{c.raw:.3f}"
            print(f"  {c.name:17} {c.contribution:+.3f}   (raw {raw}, z {c.z:+.2f}, weight {c.weight:.2f})")
        print(f"  {'Final Score':17} {s.score:.3f}")
    for note in result.notes:
        print(f"\nNote: {note}")
    return 0


def _generate(args: argparse.Namespace, settings: Settings) -> int:
    from pathlib import Path

    from app.analysis.combination import CombinationRules
    from app.analysis.features import FeatureConfig, InsufficientDataError
    from app.analysis.pipeline import GenerationRequest, generate, new_seed
    from app.data.repository import SqliteDrawRepository
    from app.data.sessions import SqliteSessionRepository, session_csv
    from app.database.sqlite import connect, init_schema
    from app.logging_config import configure_logging

    configure_logging(settings.log_level)
    game = get_game(args.game)
    rules = CombinationRules(oversample=args.oversample)
    if args.no_filters:
        rules = CombinationRules(odd_penalty=0, low_penalty=0, spread_penalty=0, sum_penalty=0,
                                 oversample=args.oversample)
    request = GenerationRequest(
        game=game, strategy=args.strategy, count=args.count,
        seed=args.seed if args.seed is not None else new_seed(),
        start=args.start, end=args.end, feature_config=FeatureConfig(hot_cold_window=args.window), rules=rules,
    )
    conn = connect(settings.db_path)
    init_schema(conn)
    try:
        try:
            result = generate(SqliteDrawRepository(conn).get_draws(game, args.start, args.end), request)
        except InsufficientDataError as exc:
            print(f"{exc}. Run 'python -m app fetch' first.", file=sys.stderr)
            return 1
        sessions = SqliteSessionRepository(conn)
        stored = sessions.get(sessions.save(result))
    finally:
        conn.close()

    print(f"Session #{stored.id} · {game.name} · strategy {args.strategy} · seed {stored.seed} · "
          f"generated {len(stored.combinations)} · {result.params['n_draws']} draws (dataset {stored.dataset_fingerprint})")
    print("Scores are relative weights from historical data, not winning probabilities.\n")
    print(f"{'#':>4}  {'Numbers':<{3 * game.numbers_per_draw}} {'Score':>6}  Flags")
    for i, c in enumerate(stored.combinations, start=1):
        nums = " ".join(f"{n:02d}" for n in c["numbers"])
        print(f"{i:>4}  {nums:<{3 * game.numbers_per_draw}} {c['total']:6.2f}  {'; '.join(c['flags'])}")
    for note in stored.notes:
        print(f"\nNote: {note}")
    if args.csv:
        Path(args.csv).write_text(session_csv(stored), encoding="utf-8")
        print(f"\nCSV written to {args.csv}")
    return 0


def _backtest(args: argparse.Namespace, settings: Settings) -> int:
    import json

    from app.analysis.backtesting import Backtester, BacktestConfig, StrategySpec
    from app.analysis.features import FeatureConfig
    from app.data.backtests import SqliteBacktestRepository
    from app.data.repository import SqliteDrawRepository
    from app.database.sqlite import connect, init_schema
    from app.logging_config import configure_logging

    configure_logging(settings.log_level)
    game = get_game(args.game)
    specs = (StrategySpec("random", "random"),) + tuple(StrategySpec(s, s) for s in args.strategies)
    config = BacktestConfig(
        start=args.start, end=args.end, training_start=args.train_from, strategies=specs,
        combinations_per_draw=args.per_draw, min_history=args.min_history, history_window=args.history_window,
        step=args.step, base_seed=args.seed, feature_config=FeatureConfig(hot_cold_window=args.window),
    )
    conn = connect(settings.db_path)
    init_schema(conn)
    try:
        draws = SqliteDrawRepository(conn).get_draws(game, args.train_from, args.end)

        def progress(done: int, total: int) -> None:
            print(f"\r  {done}/{total} draws", end="", file=sys.stderr, flush=True)

        result = Backtester().run(game, draws, config, progress=progress)
        print(file=sys.stderr)
        runs = SqliteBacktestRepository(conn)
        run_id = runs.create(game.key, config.to_dict())
        runs.finish(run_id, result.to_dict())
        if args.csv:
            from pathlib import Path

            from app.data.backtests import backtest_csv
            Path(args.csv).write_text(backtest_csv(runs.get(run_id)), encoding="utf-8")
    finally:
        conn.close()

    if args.json:
        print(json.dumps(result.to_dict(include_targets=False), indent=2))
        return 0
    s, k = result.summary, game.numbers_per_draw
    t = s.theory
    print(f"Backtest #{run_id} · {game.name} · targets {len(result.targets)} "
          f"({result.targets[0].draw_date if result.targets else '-'} → "
          f"{result.targets[-1].draw_date if result.targets else '-'}) · {args.per_draw} combinations/draw · "
          f"seed {args.seed} · {result.duration_s:.1f}s\n")
    hits = " ".join(f"{h}hit%".rjust(7) for h in range(k + 1))
    print(f"{'Strategy':<11} {'AvgMatch':>8} {'Best':>4} {hits} {'≥3 %':>6}")
    for label, m in s.strategies.items():
        pct = " ".join(f"{x:7.2f}" for x in m.hit_pct)
        print(f"{label:<11} {m.average_match:8.4f} {m.best_match:>4} {pct} {m.prize_rate_pct:6.3f}")
    pct = " ".join(f"{x:7.2f}" for x in t.hit_pct)
    print(f"{'theory':<11} {t.expected_average:8.4f} {'':>4} {pct} {t.prize_rate_pct:6.3f}")
    print(f"\nPaired comparison with {config.baseline} (per-draw mean matches, shared random numbers):")
    for c in s.comparisons:
        lo, hi = c.ci95
        ci = f"[{lo:+.4f}, {hi:+.4f}]" if lo is not None else "[n/a]"
        print(f"  {c.label:<10} Δ {c.mean_difference:+.4f}  95% CI {ci}  p {c.p_value:.3f}  "
              f"p(adj) {c.p_adjusted:.3f}  {c.verdict}")
    for note in result.notes:
        print(f"\nNote: {note}")
    return 0


def _print_issues(conflicts: List[str], rejected: List[str]) -> None:
    if conflicts:
        print(f"  {len(conflicts)} conflict(s), stored version kept: {conflicts[:10]}")
    if rejected:
        print(f"  {len(rejected)} source record(s) rejected:")
        for line in rejected[:10]:
            print(f"    {line}")


if __name__ == "__main__":
    sys.exit(main())
