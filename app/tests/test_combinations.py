from collections import Counter
from datetime import timedelta

import numpy as np
import pytest

from app.analysis.combination import CombinationRules, CombinationScorer, sample_combinations
from app.analysis.features import FeatureEngine
from app.analysis.pipeline import GenerationRequest, generate, request_from_params
from app.analysis.scoring import build_scorer
from app.data.sessions import SqliteSessionRepository, session_csv
from app.domain.games import MEGA_645, POWER_655, LotteryGameConfig
from app.domain.models import DrawResult
from app.tests.test_features import TINY, TINY_DRAWS, random_history

UNIFORM_45 = np.ones(45)


@pytest.fixture(scope="module")
def mega_history():
    return random_history(MEGA_645, 400, seed=5)


# ------------------------------------------------------------ generator

@pytest.mark.parametrize("game", [MEGA_645, POWER_655])
def test_combinations_are_valid_unique_and_sorted(game):
    result = sample_combinations(game, np.ones(game.pool_size), 500, seed=1)
    combos = result.combinations
    assert len(combos) == 500
    assert len(set(combos)) == 500
    for c in combos:
        assert len(c) == game.numbers_per_draw
        assert len(set(c)) == game.numbers_per_draw
        assert list(c) == sorted(c)
        assert all(game.min_number <= n <= game.max_number for n in c)


def test_same_seed_same_output_different_seed_differs():
    a = sample_combinations(MEGA_645, UNIFORM_45, 50, seed=42).combinations
    b = sample_combinations(MEGA_645, UNIFORM_45, 50, seed=42).combinations
    c = sample_combinations(MEGA_645, UNIFORM_45, 50, seed=43).combinations
    assert a == b and a != c


def test_uniform_weights_give_roughly_uniform_inclusion():
    combos = sample_combinations(MEGA_645, UNIFORM_45, 20_000, seed=7).combinations
    counts = Counter(n for c in combos for n in c)
    expected = 20_000 * 6 / 45
    assert all(abs(counts[n] - expected) < 5 * expected ** 0.5 for n in range(1, 46))


def test_weights_shift_inclusion():
    w = UNIFORM_45.copy()
    w[22] = 3.0  # number 23
    combos = sample_combinations(MEGA_645, w, 5_000, seed=7).combinations
    counts = Counter(n for c in combos for n in c)
    assert counts[23] > 2 * np.median([counts[n] for n in range(1, 46)])


def test_requesting_more_than_exist_stops_with_note():
    # Tiny 2/6 has only C(6,2) = 15 distinct combinations.
    result = sample_combinations(TINY, np.ones(6), 20, seed=1)
    assert len(result.combinations) == 15
    assert "Only 15 unique" in result.notes[0]


@pytest.mark.parametrize("weights", [np.ones(44), np.r_[np.ones(44), 0.0], np.r_[np.ones(44), -1.0]])
def test_invalid_weights_rejected(weights):
    with pytest.raises(ValueError):
        sample_combinations(MEGA_645, weights, 5, seed=1)


# ------------------------------------------------------------ combination scoring

@pytest.fixture(scope="module")
def mega_scorer_parts(mega_history):
    fs = FeatureEngine().compute(MEGA_645, mega_history)
    return fs, build_scorer("random").score(MEGA_645, fs)


def combo_scorer(parts, **rules):
    fs, ss = parts
    return CombinationScorer(MEGA_645, ss, fs, CombinationRules(**rules))


def test_number_score_is_sum_of_scores(mega_scorer_parts):
    s = combo_scorer(mega_scorer_parts, pair_weight=0).score((3, 12, 18, 23, 31, 41))
    assert s.number_score == pytest.approx(6.0)  # uniform scores of 1.0
    assert s.total_sum == 128 and s.odd == 4 and s.low == 3
    assert s.flags == [] and s.total == pytest.approx(6.0)


def test_extreme_distributions_are_penalized(mega_scorer_parts):
    s = combo_scorer(mega_scorer_parts, pair_weight=0).score((1, 3, 5, 7, 9, 11))
    # all odd, all low, narrow range (10 < 0.3 × 44), sum 36 far below P5
    assert s.distribution_score == pytest.approx(-3.0)
    assert s.sum_score == pytest.approx(-1.0)
    assert len(s.flags) == 4
    assert s.total == pytest.approx(6.0 - 4.0)


def test_penalties_can_be_disabled(mega_scorer_parts):
    s = combo_scorer(mega_scorer_parts, pair_weight=0, odd_penalty=0, low_penalty=0, spread_penalty=0,
                     sum_penalty=0).score((1, 3, 5, 7, 9, 11))
    assert s.flags == [] and s.total == pytest.approx(6.0)


def test_custom_odd_counts(mega_scorer_parts):
    s = combo_scorer(mega_scorer_parts, pair_weight=0, odd_counts=(4,)).score((3, 12, 18, 23, 31, 41))
    assert s.distribution_score == -1.0 and "4 odd / 2 even" in s.flags


def test_extremes_follow_game_size():
    game = LotteryGameConfig(key="x", name="X 3/9", min_number=1, max_number=9, numbers_per_draw=3)
    draws = [DrawResult.create(game, str(i), TINY_DRAWS[0].draw_date + timedelta(days=i), n)
             for i, n in enumerate([(1, 2, 3), (4, 5, 6), (7, 8, 9), (1, 5, 9)])]
    fs = FeatureEngine().compute(game, draws)
    scorer = CombinationScorer(game, build_scorer("random").score(game, fs), fs, CombinationRules(pair_weight=0))
    assert "3 odd / 0 even" in scorer.score((1, 3, 5)).flags


def test_pair_score_hand_computed():
    fs = FeatureEngine().compute(TINY, TINY_DRAWS)
    scorer = CombinationScorer(TINY, build_scorer("random").score(TINY, fs), fs,
                               CombinationRules(odd_penalty=0, low_penalty=0, spread_penalty=0, sum_penalty=0))
    # Pair (1, 2) occurred once; expected 5 × 1/15 = 1/3 → ratio 3 → score 3 − 1 = 2.
    assert scorer.score((1, 2)).pair_score == pytest.approx(2.0)
    assert scorer.score((4, 5)).pair_score == pytest.approx(-1.0)  # never together


def test_rules_validation():
    with pytest.raises(ValueError):
        CombinationRules(oversample=0)
    with pytest.raises(ValueError):
        CombinationRules(sum_percentiles=(95, 5))
    with pytest.raises(ValueError):
        CombinationRules(spread_penalty=-1)
    assert CombinationRules.from_dict(CombinationRules(odd_counts=[6, 0, 6]).to_dict()).odd_counts == (0, 6)


# ------------------------------------------------------------ pipeline

def request(**kw):
    defaults = dict(game=MEGA_645, strategy="balanced", count=30, seed=123)
    defaults.update(kw)
    return GenerationRequest(**defaults)


def test_pipeline_reproducible_and_sorted(mega_history):
    a = generate(mega_history, request())
    b = generate(list(reversed(mega_history)), request())
    assert [c.numbers for c in a.combinations] == [c.numbers for c in b.combinations]
    totals = [c.total for c in a.combinations]
    assert totals == sorted(totals, reverse=True)
    assert len(a.combinations) == 30


def test_params_contain_reproducibility_fields(mega_history):
    p = generate(mega_history, request(strategy="recent", seed=9)).params
    for key in ("game", "start", "end", "feature_config", "strategy", "scoring", "seed", "count",
                "dataset_fingerprint", "rules", "sampler", "numpy_version"):
        assert key in p
    assert p["scoring"]["weights"]["recent_frequency"] == 0.8


def test_request_roundtrip_reproduces(mega_history):
    original = generate(mega_history, request(rules=CombinationRules(oversample=3), gap_mode="recency"))
    rebuilt = request_from_params(MEGA_645, original.params)
    again = generate(mega_history, rebuilt)
    assert [c.numbers for c in again.combinations] == [c.numbers for c in original.combinations]
    assert again.params == original.params


def test_oversample_keeps_best(mega_history):
    plain = generate(mega_history, request(count=20))
    selected = generate(mega_history, request(count=20, rules=CombinationRules(oversample=5)))
    assert np.mean([c.total for c in selected.combinations]) > np.mean([c.total for c in plain.combinations])
    assert any("Kept the best 20 of 100" in n for n in selected.notes)


def test_random_baseline_ignores_oversample(mega_history):
    result = generate(mega_history, request(strategy="random", rules=CombinationRules(oversample=5)))
    assert result.params["rules"]["oversample"] == 1


def test_pipeline_respects_as_of(mega_history):
    cutoff = mega_history[300].draw_date
    a = generate(mega_history, request(), as_of=cutoff)
    altered = mega_history[:300] + random_history(MEGA_645, 400, seed=77)[300:]
    b = generate(altered, request(), as_of=cutoff)
    assert [c.numbers for c in a.combinations] == [c.numbers for c in b.combinations]
    assert a.params["n_draws"] == 300


# ------------------------------------------------------------ sessions

def test_session_save_get_list_and_csv(conn, mega_history):
    repo = SqliteSessionRepository(conn)
    result = generate(mega_history, request(count=5))
    sid = repo.save(result)
    stored = repo.get(sid)
    assert stored.seed == 123 and stored.count == 5 and len(stored.combinations) == 5
    assert stored.params == result.params
    assert [s.id for s in repo.list("mega645")] == [sid]
    assert repo.list("power655") == []
    assert repo.get(999) is None

    text = session_csv(stored)
    lines = text.strip().splitlines()
    assert lines[0].startswith(f"# session={sid} game=mega645 strategy=balanced seed=123")
    header = next(line for line in lines if line.startswith("rank,"))
    assert header.split(",")[1:7] == ["n1", "n2", "n3", "n4", "n5", "n6"]
    assert len([line for line in lines if not line.startswith("#")]) == 6  # header + 5 rows
