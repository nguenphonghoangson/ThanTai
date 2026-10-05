import pytest

from app.domain.games import GAMES, MEGA_645, POWER_655, LotteryGameConfig, UnknownGameError, get_game


def test_mega_645_config():
    assert (MEGA_645.min_number, MEGA_645.max_number, MEGA_645.numbers_per_draw) == (1, 45, 6)
    assert MEGA_645.pool_size == 45
    assert MEGA_645.low_max == 22
    assert MEGA_645.is_low(22) and not MEGA_645.is_low(23)
    assert not MEGA_645.has_bonus_number


def test_power_655_config():
    assert (POWER_655.min_number, POWER_655.max_number, POWER_655.numbers_per_draw) == (1, 55, 6)
    assert POWER_655.pool_size == 55
    assert POWER_655.low_max == 27
    assert POWER_655.is_low(27) and not POWER_655.is_low(28)
    assert POWER_655.has_bonus_number


def test_low_high_derived_for_custom_game():
    game = LotteryGameConfig(key="x", name="X", min_number=10, max_number=19, numbers_per_draw=3)
    assert game.low_max == 14
    assert game.to_dict()["high_range"] == [15, 19]


def test_registry_lookup():
    assert get_game("mega645") is MEGA_645
    assert set(GAMES) == {"mega645", "power655"}
    with pytest.raises(UnknownGameError):
        get_game("keno")


@pytest.mark.parametrize("kwargs", [
    dict(min_number=10, max_number=1, numbers_per_draw=1),
    dict(min_number=1, max_number=5, numbers_per_draw=6),
    dict(min_number=1, max_number=5, numbers_per_draw=0),
])
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        LotteryGameConfig(key="bad", name="Bad", **kwargs)
