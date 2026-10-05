"""Feature engine tests on a tiny hand-computed fixture, plus leakage guarantees."""
import json
import random
from datetime import date, timedelta

import pytest

from app.analysis.features import (
    FeatureConfig, FeatureEngine, InsufficientDataError, Temperature, TemperatureThresholds, draws_before,
)
from app.analysis.features.distributions import hypergeometric_pct
from app.domain.games import MEGA_645, POWER_655, LotteryGameConfig
from app.domain.models import DrawResult

# Numbers 1..6, two per draw. LOW = 1..3, HIGH = 4..6.
TINY = LotteryGameConfig(key="tiny", name="Tiny 2/6", min_number=1, max_number=6, numbers_per_draw=2)
D0 = date(2024, 1, 1)
TINY_DRAWS = [
    DrawResult.create(TINY, str(i + 1), D0 + timedelta(days=i), nums)
    for i, nums in enumerate([(1, 2), (1, 3), (2, 4), (1, 5), (3, 6)])
]


@pytest.fixture
def tiny():
    cfg = FeatureConfig(recent_windows=(2,), hot_cold_window=2, include_triples=True, triple_min_support=1)
    return FeatureEngine(cfg).compute(TINY, TINY_DRAWS)


def test_frequency(tiny):
    assert [n.frequency for n in tiny.numbers] == [3, 2, 2, 1, 1, 1]
    assert tiny.by_number(1).frequency_rate == pytest.approx(3 / 5)
    assert tiny.expected_rate == pytest.approx(2 / 6)


def test_recent_frequency(tiny):
    # Last two draws: (1, 5), (3, 6)
    assert [n.recent[2] for n in tiny.numbers] == [1, 0, 1, 0, 1, 1]


def test_recent_window_larger_than_history_uses_all_draws():
    fs = FeatureEngine(FeatureConfig(recent_windows=(100,), hot_cold_window=100)).compute(TINY, TINY_DRAWS)
    assert [n.recent[100] for n in fs.numbers] == [n.frequency for n in fs.numbers]


def test_gap(tiny):
    assert [n.gap for n in tiny.numbers] == [1, 2, 0, 2, 1, 0]
    assert tiny.by_number(1).last_seen_draw_id == "4"
    assert tiny.by_number(1).last_seen_date == D0 + timedelta(days=3)


def test_average_gap_and_deviation(tiny):
    one, two, three, four = (tiny.by_number(n) for n in (1, 2, 3, 4))
    assert one.average_gap == pytest.approx(0.5)  # appearances at 0,1,3 → missed 0 and 1
    assert one.gap_deviation == pytest.approx(2.0)
    assert two.average_gap == pytest.approx(1.0)
    assert three.average_gap == pytest.approx(2.0) and three.gap_deviation == pytest.approx(0.0)
    assert four.average_gap is None and four.gap_deviation is None  # single appearance
    assert tiny.expected_gap == pytest.approx(2.0)  # (1 - 1/3) / (1/3)


def test_never_seen_number_gap_is_history_length():
    draws = [d for d in TINY_DRAWS if 6 not in d.numbers]
    fs = FeatureEngine().compute(TINY, draws)
    six = fs.by_number(6)
    assert not six.seen and six.gap == len(draws) and six.frequency == 0 and six.last_seen_date is None


def test_temperature(tiny):
    # Expected in a 2-draw window: 2 * 2/6 = 0.667. One hit → ratio 1.5 → HOT; none → COLD.
    assert tiny.by_number(1).temperature_ratio == pytest.approx(1.5)
    assert tiny.by_number(1).temperature == Temperature.HOT
    assert tiny.by_number(2).temperature == Temperature.COLD


def test_temperature_thresholds_configurable():
    cfg = FeatureConfig(recent_windows=(2,), hot_cold_window=2, temperature=TemperatureThresholds(hot=2, warm=1.4, cold=0))
    fs = FeatureEngine(cfg).compute(TINY, TINY_DRAWS)
    assert fs.by_number(1).temperature == Temperature.WARM
    assert fs.by_number(2).temperature == Temperature.NORMAL


def test_invalid_thresholds_rejected():
    with pytest.raises(ValueError):
        TemperatureThresholds(hot=1.0, warm=1.2, cold=0.5)


def test_sum_stats(tiny):
    s = tiny.sums  # sums 3, 4, 6, 6, 9
    assert (s.min, s.max, s.median) == (3, 9, 6)
    assert s.mean == pytest.approx(5.6)
    assert s.std == pytest.approx(2.302172886644267)
    assert s.theoretical_mean == pytest.approx(7.0)
    assert sum(c for _, _, c in s.histogram) == 5


def test_odd_even(tiny):
    # odd counts per draw: 1, 2, 0, 2, 1
    assert tiny.odd_even.counts == [1, 2, 2]
    assert tiny.odd_even.mean == pytest.approx(1.2)
    assert tiny.odd_even.expected_mean == pytest.approx(1.0)


def test_low_high(tiny):
    # low (1–3) counts per draw: 2, 2, 1, 1, 1
    assert tiny.low_high.counts == [0, 3, 2]
    assert sum(tiny.low_high.observed_pct) == pytest.approx(100)


@pytest.mark.parametrize("game", [MEGA_645, POWER_655])
def test_low_high_split_derived_from_game(game):
    draw = DrawResult.create(game, "1", D0, [1, 2, game.low_max, game.low_max + 1, game.max_number - 1, game.max_number])
    fs = FeatureEngine().compute(game, [draw])
    assert fs.low_high.counts[3] == 1  # exactly 3 low


def test_hypergeometric_baseline():
    pct = hypergeometric_pct(45, 23, 6)
    assert sum(pct) == pytest.approx(100)
    assert pct[3] == pytest.approx(100 * 1771 * 1540 / 8145060)  # C(23,3)·C(22,3)/C(45,6)


def test_pairs(tiny):
    assert tiny.pairs.expected_count == pytest.approx(5 / 15)
    assert sorted(c.numbers for c in tiny.pairs.top if c.count == 1) == [(1, 2), (1, 3), (1, 5), (2, 4), (3, 6)]
    assert tiny.pairs.top[0].count == 1
    assert tiny.pair_matrix[0, 1] == tiny.pair_matrix[1, 0] == 1
    assert tiny.pair_matrix.trace() == 0


def test_pairs_can_be_disabled():
    fs = FeatureEngine(FeatureConfig(include_pairs=False)).compute(TINY, TINY_DRAWS)
    assert fs.pairs is None and fs.pair_matrix is None


def test_triples_flag_sparsity():
    game = LotteryGameConfig(key="t3", name="T 3/6", min_number=1, max_number=6, numbers_per_draw=3)
    draws = [DrawResult.create(game, str(i), D0 + timedelta(days=i), n)
             for i, n in enumerate([(1, 2, 3), (1, 2, 3), (4, 5, 6)])]
    fs = FeatureEngine(FeatureConfig(include_triples=True, triple_min_support=2)).compute(game, draws)
    assert [(c.numbers, c.count) for c in fs.triples.top] == [((1, 2, 3), 2)]
    assert fs.triples.expected_count == pytest.approx(3 / 20)
    assert "chance" in fs.triples.note


def test_triples_off_by_default():
    assert FeatureEngine().compute(TINY, TINY_DRAWS).triples is None


def test_deterministic_and_json_serializable(tiny):
    again = FeatureEngine(tiny.config).compute(TINY, list(reversed(TINY_DRAWS)))  # input order irrelevant
    assert again.to_dict() == tiny.to_dict()
    json.dumps(tiny.to_dict())


def test_empty_history_raises():
    with pytest.raises(InsufficientDataError):
        FeatureEngine().compute(TINY, [])


# ---------------------------------------------------------------- leakage

def random_history(game, n, seed=7):
    rng = random.Random(seed)
    start = date(2020, 1, 1)
    return [
        DrawResult.create(game, f"{i + 1:05d}", start + timedelta(days=2 * i),
                          rng.sample(range(game.min_number, game.max_number + 1), game.numbers_per_draw))
        for i in range(n)
    ]


def test_as_of_excludes_draw_on_cutoff_date():
    cutoff = TINY_DRAWS[3].draw_date
    fs = FeatureEngine().compute(TINY, TINY_DRAWS, as_of=cutoff)
    assert fs.n_draws == 3
    assert fs.last_draw[1] < cutoff
    assert draws_before(TINY_DRAWS, cutoff) == TINY_DRAWS[:3]


def test_as_of_equals_truncated_history():
    draws = random_history(MEGA_645, 300)
    engine = FeatureEngine(FeatureConfig(include_triples=True))
    for i in (1, 50, 151, 299):
        cutoff = draws[i].draw_date
        with_future = engine.compute(MEGA_645, draws, as_of=cutoff).to_dict()
        truncated = engine.compute(MEGA_645, draws[:i]).to_dict()
        with_future.pop("as_of"), truncated.pop("as_of")
        assert with_future == truncated


def test_future_draws_do_not_change_features():
    draws = random_history(POWER_655, 200)
    cutoff = draws[120].draw_date
    engine = FeatureEngine()
    base = engine.compute(POWER_655, draws[:150], as_of=cutoff).to_dict()
    # Replace every draw on/after the cutoff with different data.
    altered = draws[:120] + random_history(POWER_655, 200, seed=99)[120:]
    assert engine.compute(POWER_655, altered, as_of=cutoff).to_dict() == base


def test_as_of_before_first_draw_raises():
    with pytest.raises(InsufficientDataError, match="before"):
        FeatureEngine().compute(TINY, TINY_DRAWS, as_of=TINY_DRAWS[0].draw_date)


@pytest.mark.parametrize("n", [1, 37, 1500])
def test_pair_matrix_matches_integer_reference(n):
    import numpy as np

    from app.analysis.features.combos import pair_matrix

    m = np.random.default_rng(n).random((n, 55)) < 0.11
    ref = m.astype(np.int64).T @ m.astype(np.int64)
    np.fill_diagonal(ref, 0)
    assert np.array_equal(pair_matrix(m), ref)
