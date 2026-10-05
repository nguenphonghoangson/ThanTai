"""Walk-forward backtest tests. The leakage tests are the most important ones in the suite."""
import random
from datetime import date, timedelta

import numpy as np
import pytest

from app.analysis.backtesting import Backtester, BacktestConfig, StrategySpec, match_counts, theory
from app.analysis.backtesting import runner as runner_module
from app.analysis.backtesting.metrics import paired_comparison
from app.analysis.features import FeatureEngine
from app.domain.games import MEGA_645
from app.domain.models import DrawResult
from app.tests.test_features import random_history

START = date(2020, 1, 1)


@pytest.fixture(scope="module")
def history():
    return random_history(MEGA_645, 260, seed=21)  # one draw every 2 days from 2020-01-01


def period(draws, first_index, last_index):
    return draws[first_index].draw_date, draws[last_index].draw_date


class SpyEngine(FeatureEngine):
    """Records every history the backtester hands to the feature engine."""

    calls = []

    def compute(self, game, draws, as_of=None, **kwargs):
        SpyEngine.calls.append((as_of, [d.draw_date for d in draws]))
        return super().compute(game, draws, as_of=as_of, **kwargs)


@pytest.fixture
def spy():
    SpyEngine.calls = []
    return SpyEngine


@pytest.fixture
def captured(monkeypatch):
    """Record (target numbers, combinations) at the single point the target's numbers are read."""
    calls = []
    original = runner_module.match_counts

    def recording(combos, actual):
        calls.append((tuple(actual), [tuple(c) for c in combos]))
        return original(combos, actual)

    monkeypatch.setattr(runner_module, "match_counts", recording)
    return calls


def small_config(draws, first=150, last=199, **kw):
    start, end = period(draws, first, last)
    defaults = dict(start=start, end=end, combinations_per_draw=20, min_history=50)
    defaults.update(kw)
    return BacktestConfig(**defaults)


# ------------------------------------------------------------ leakage

def test_history_strictly_before_each_target(history, spy):
    config = small_config(history)
    result = Backtester(engine_factory=spy).run(MEGA_645, history, config)
    assert len(result.targets) == 50 and len(spy.calls) == 50
    for (as_of, dates), target in zip(spy.calls, result.targets):
        assert as_of.isoformat() == target.draw_date
        assert dates and max(dates) < as_of  # never <=
        assert len(dates) == target.history


def test_target_and_future_draws_cannot_change_generated_combinations(history, captured):
    config = small_config(history, first=150, last=150)
    Backtester().run(MEGA_645, history, config)
    first = list(captured)  # one capture per strategy
    captured.clear()

    # Replace the target draw and everything after it with different numbers.
    altered = history[:150] + random_history(MEGA_645, 260, seed=999)[150:]
    Backtester().run(MEGA_645, altered, config)
    second = list(captured)
    assert len(first) == len(second) == 4
    assert first[0][0] != second[0][0]  # the target itself changed …
    assert [c for _, c in first] == [c for _, c in second]  # … but nothing generated for it did


def test_results_for_earlier_targets_unaffected_by_later_data(history):
    config = small_config(history, first=120, last=200)
    full = Backtester().run(MEGA_645, history, config)
    altered = history[:170] + random_history(MEGA_645, 260, seed=5)[170:]
    partial = Backtester().run(MEGA_645, altered, config)
    before = [t for t in full.targets if t.draw_date < history[170].draw_date.isoformat()]
    assert before and before == partial.targets[: len(before)]


def test_history_window_limits_lookback(history, spy):
    Backtester(engine_factory=spy).run(MEGA_645, history, small_config(history, history_window=60))
    assert all(len(dates) == 60 for _, dates in spy.calls)


def test_training_start_excludes_older_draws(history, spy):
    train = history[40].draw_date
    Backtester(engine_factory=spy).run(MEGA_645, history, small_config(history, training_start=train))
    assert all(min(dates) >= train for _, dates in spy.calls)


# ------------------------------------------------------------ mechanics

def test_min_history_skips_early_targets(history):
    result = Backtester().run(MEGA_645, history, small_config(history, first=10, last=79, min_history=50))
    assert result.skipped == 40 and len(result.targets) == 30
    assert "40 target draw(s) skipped" in result.notes[0]


def test_step(history):
    result = Backtester().run(MEGA_645, history, small_config(history, step=5))
    assert len(result.targets) == 10


def test_strategies_share_seed_per_target(history, captured):
    config = small_config(history, first=160, last=160)
    Backtester().run(MEGA_645, history, config)
    # random + frequency + recent + balanced → four calls for one target, all against the same draw.
    assert len(captured) == 4 and len({a for a, _ in captured}) == 1
    assert config.seed_for("00161") == config.seed_for("00161") != config.seed_for("00162")


def test_deterministic(history):
    config = small_config(history)
    a = Backtester().run(MEGA_645, history, config).to_dict()
    b = Backtester().run(MEGA_645, list(reversed(history)), config).to_dict()
    a.pop("duration_s"), b.pop("duration_s")
    assert a == b


def test_metrics_consistency(history):
    result = Backtester().run(MEGA_645, history, small_config(history))
    for label, m in result.summary.strategies.items():
        assert m.combinations == 50 * 20 == sum(m.hit_counts)
        assert sum(m.hit_pct) == pytest.approx(100)
        per_draw = np.mean([t.mean[label] for t in result.targets])
        assert m.average_match == pytest.approx(per_draw)
        assert m.best_match == max(t.best[label] for t in result.targets)


def test_random_baseline_matches_theory_on_uniform_data():
    draws = random_history(MEGA_645, 700, seed=8)
    config = BacktestConfig(start=draws[100].draw_date, end=draws[-1].draw_date, combinations_per_draw=50,
                            strategies=(StrategySpec("random", "random"),))
    result = Backtester().run(MEGA_645, draws, config)
    m = result.summary.strategies["random"]
    assert m.average_match == pytest.approx(theory(MEGA_645).expected_average, abs=0.03)
    assert abs(result.summary.vs_theory["random"]["z"]) < 4


def test_harness_detects_a_planted_signal():
    """If draws really favour some numbers, the frequency strategy must beat random significantly.

    Without this, 'no difference on real data' could just mean the backtest cannot see anything.
    """
    rng = random.Random(4)
    weights = [4.0 if n <= 8 else 1.0 for n in range(1, 46)]

    def biased_draw():
        pool, chosen = list(range(1, 46)), []
        w = list(weights)
        for _ in range(6):
            i = rng.choices(range(len(pool)), weights=w)[0]
            chosen.append(pool.pop(i))
            w.pop(i)
        return chosen

    draws = [DrawResult.create(MEGA_645, f"{i + 1:05d}", START + timedelta(days=2 * i), biased_draw())
             for i in range(400)]
    config = BacktestConfig(start=draws[150].draw_date, end=draws[-1].draw_date, combinations_per_draw=50,
                            strategies=(StrategySpec("random", "random"), StrategySpec("frequency", "frequency")))
    result = Backtester().run(MEGA_645, draws, config)
    (comp,) = result.summary.comparisons
    assert comp.significant and comp.mean_difference > 0


# ------------------------------------------------------------ metrics

def test_match_counts():
    assert list(match_counts([(1, 2, 3, 4, 5, 6), (1, 2, 40, 41, 42, 43)], (1, 2, 3, 7, 8, 9))) == [3, 2]


def test_theory_values():
    t = theory(MEGA_645)
    assert t.expected_average == pytest.approx(36 / 45)
    assert sum(t.hit_pct) == pytest.approx(100)


def test_paired_comparison_cases():
    same = [0.8] * 50
    c = paired_comparison("a", "random", same, same, 1)
    assert not c.significant and c.p_value == 1.0
    r = np.random.default_rng(0)
    base = r.normal(0.8, 0.1, 200)
    better = paired_comparison("a", "random", base + 0.05 + r.normal(0, 0.01, 200), base, 3)
    assert better.significant and better.ci95[0] > 0 and "better" in better.verdict
    few = paired_comparison("a", "random", [1.0] * 10, [0.5] * 10, 1)
    assert "Too few draws" in few.verdict


def test_config_validation(history):
    s, e = period(history, 100, 120)
    with pytest.raises(ValueError):
        BacktestConfig(start=e, end=s)
    with pytest.raises(ValueError):
        BacktestConfig(start=s, end=e, strategies=(StrategySpec("frequency", "frequency"),))  # no baseline
    with pytest.raises(ValueError):
        BacktestConfig(start=s, end=e, strategies=(StrategySpec("random", "random"), StrategySpec("random", "recent")))
    with pytest.raises(ValueError):
        BacktestConfig(start=s, end=e, training_start=e + timedelta(days=1))
