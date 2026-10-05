import json
from datetime import timedelta

import numpy as np
import pytest

from app.analysis.features import FeatureConfig, FeatureEngine
from app.analysis.scoring import (
    PRESETS, GapMode, MissingFeatureError, ScoringConfig, ScoringWeights, UnknownStrategyError,
    WeightedScorer, build_scorer,
)
from app.analysis.scoring.components import pair_raw, zscores
from app.domain.games import MEGA_645, POWER_655
from app.domain.models import DrawResult
from app.tests.test_features import TINY, TINY_DRAWS, random_history


@pytest.fixture(scope="module")
def mega_history():
    return random_history(MEGA_645, 400, seed=3)


@pytest.fixture(scope="module")
def mega_features(mega_history):
    return FeatureEngine().compute(MEGA_645, mega_history)


def scorer(**weights):
    return WeightedScorer(ScoringConfig("custom", ScoringWeights(**weights)))


# ------------------------------------------------------------ weights / config

def test_weights_validation_and_normalization():
    with pytest.raises(ValueError):
        ScoringWeights(frequency=-0.1)
    w = ScoringWeights(frequency=3, recent_frequency=1)
    assert w.normalized().as_dict() == {"frequency": 0.75, "recent_frequency": 0.25, "gap": 0.0,
                                        "pair": 0.0, "historical": 0.0}
    assert ScoringWeights().normalized().total == 0


def test_config_validation():
    with pytest.raises(ValueError):
        ScoringConfig("x", gap_mode="due")
    with pytest.raises(ValueError):
        ScoringConfig("x", min_score=0)


def test_presets_cover_required_strategies():
    assert set(PRESETS) == {"frequency", "recent", "balanced", "random"}
    assert PRESETS["balanced"].weights.as_dict() == {
        "frequency": 0.30, "recent_frequency": 0.25, "gap": 0.15, "pair": 0.15, "historical": 0.15}
    with pytest.raises(UnknownStrategyError):
        build_scorer("ml")


# ------------------------------------------------------------ math

def test_zscores():
    z = zscores([1.0, 2.0, 3.0, None])
    assert z[3] == 0
    assert z[:3].mean() == pytest.approx(0) and z[:3].std() == pytest.approx(1)
    assert not zscores([2.0, 2.0, 2.0]).any()


def test_contributions_sum_to_score_minus_one(mega_features):
    result = build_scorer("balanced").score(MEGA_645, mega_features)
    for s in result.scores:
        total = 1 + sum(c.contribution for c in s.components)
        assert s.score == pytest.approx(max(total, result.config.min_score))
        for c in s.components:
            assert c.contribution == pytest.approx(result.config.intensity * c.weight * c.z)


def test_score_floor_applied(mega_features):
    result = WeightedScorer(ScoringConfig("x", ScoringWeights(frequency=1), intensity=5.0)).score(MEGA_645, mega_features)
    assert min(s.score for s in result.scores) == pytest.approx(0.05)
    assert any("floor" in n for n in result.notes)


def test_frequency_strategy_is_monotonic_in_frequency(mega_features):
    result = build_scorer("frequency").score(MEGA_645, mega_features)
    pairs = sorted((mega_features.by_number(s.number).frequency, s.score) for s in result.scores)
    assert all(a[1] <= b[1] + 1e-12 for a, b in zip(pairs, pairs[1:]))


def test_recent_only_is_monotonic_in_window_hits(mega_features):
    result = scorer(recent_frequency=1).score(MEGA_645, mega_features)
    pairs = sorted((mega_features.by_number(s.number).temperature_ratio, s.score) for s in result.scores)
    assert all(a[1] <= b[1] + 1e-12 for a, b in zip(pairs, pairs[1:]))


def test_gap_modes_are_mirror_images(mega_features):
    over = WeightedScorer(ScoringConfig("x", ScoringWeights(gap=1), gap_mode=GapMode.OVERDUE)).score(MEGA_645, mega_features)
    rec = WeightedScorer(ScoringConfig("x", ScoringWeights(gap=1), gap_mode=GapMode.RECENCY)).score(MEGA_645, mega_features)
    for a, b in zip(over.scores, rec.scores):
        assert a.components[0].contribution == pytest.approx(-b.components[0].contribution)


def test_rank_is_dense_and_tie_broken_by_number(mega_features):
    result = build_scorer("balanced").score(MEGA_645, mega_features)
    assert sorted(s.rank for s in result.scores) == list(range(1, 46))
    ranked = result.ranked()
    assert all(a.score >= b.score for a, b in zip(ranked, ranked[1:]))


def test_random_baseline_is_uniform(mega_features):
    result = build_scorer("random").score(MEGA_645, mega_features)
    assert np.all(result.weight_vector() == 1.0)
    assert all(s.components == [] for s in result.scores)
    # Overrides are ignored for the baseline.
    assert build_scorer("random", weights=ScoringWeights(frequency=1)).config.uniform


def test_pair_raw_hand_computed():
    fs = FeatureEngine().compute(TINY, TINY_DRAWS)
    # k=2, N=6 → uniform P(m | n) = 1/5. Number 1: freq 3, co with 2 = 1, co with 3 = 1.
    raw = pair_raw(TINY, fs, anchors=[1, 2, 3])
    assert raw[0] == pytest.approx(((1 + 1) / 2) / (3 * 1 / 5))  # anchors 2,3 (1 excluded)
    assert raw[3] == pytest.approx(((0 + 1 + 0) / 3) / (1 * 1 / 5))  # number 4 with 1,2,3


def test_pair_weight_requires_pair_features(mega_history):
    fs = FeatureEngine(FeatureConfig(include_pairs=False)).compute(MEGA_645, mega_history)
    with pytest.raises(MissingFeatureError):
        build_scorer("balanced").score(MEGA_645, fs)
    build_scorer("recent").score(MEGA_645, fs)  # no pair weight → fine


def test_historical_neutral_when_history_too_short():
    fs = FeatureEngine().compute(TINY, TINY_DRAWS)  # 5 draws < 50-draw block
    result = scorer(historical=1, frequency=1).score(TINY, fs)
    hist = [c for s in result.scores for c in s.components if c.name == "historical"]
    assert all(c.z == 0 and c.raw is None for c in hist)
    assert any("historical component is neutral" in n for n in result.notes)


# ------------------------------------------------------------ reproducibility

def test_same_input_same_config_same_scores(mega_history):
    a = build_scorer("balanced").score(MEGA_645, FeatureEngine().compute(MEGA_645, mega_history))
    b = build_scorer("balanced").score(MEGA_645, FeatureEngine().compute(MEGA_645, list(reversed(mega_history))))
    assert a.to_dict() == b.to_dict()
    json.dumps(a.to_dict(), default=str)


def test_params_capture_everything(mega_features):
    p = build_scorer("balanced", gap_mode=GapMode.RECENCY).score(MEGA_645, mega_features).params()
    assert p["dataset_fingerprint"] == mega_features.dataset_fingerprint
    assert p["scoring"]["gap_mode"] == "recency"
    assert p["scoring"]["weights"]["pair"] == 0.15
    assert p["feature_config"]["hot_cold_window"] == 100
    assert p["n_draws"] == 400


def test_fingerprint_changes_with_data(mega_history):
    base = FeatureEngine().compute(MEGA_645, mega_history).dataset_fingerprint
    last = mega_history[-1]
    changed = mega_history[:-1] + [DrawResult.create(MEGA_645, last.draw_id, last.draw_date, [1, 2, 3, 4, 5, 6])]
    assert FeatureEngine().compute(MEGA_645, changed).dataset_fingerprint != base


def test_scores_respect_as_of_cutoff():
    draws = random_history(POWER_655, 300, seed=11)
    cutoff = draws[200].draw_date
    engine, s = FeatureEngine(), build_scorer("balanced")
    with_future = s.score(POWER_655, engine.compute(POWER_655, draws, as_of=cutoff))
    future_changed = draws[:200] + random_history(POWER_655, 300, seed=12)[200:]
    other = s.score(POWER_655, engine.compute(POWER_655, future_changed, as_of=cutoff))
    assert with_future.to_dict() == other.to_dict()
    assert with_future.as_of == cutoff and with_future.n_draws == 200


def test_consistency_feature():
    game = TINY
    # 4 draws, block of 2: number 1 appears twice in each block → above expected (2*2/6) in both.
    draws = [DrawResult.create(game, str(i), TINY_DRAWS[0].draw_date + timedelta(days=i), n)
             for i, n in enumerate([(1, 2), (1, 3), (1, 4), (1, 5)])]
    fs = FeatureEngine(FeatureConfig(consistency_block=2)).compute(game, draws)
    assert fs.by_number(1).consistency == 1.0
    assert fs.by_number(6).consistency == 0.0
    assert fs.by_number(2).consistency == 0.5  # once in the first block (1 > 0.667), absent in the second
