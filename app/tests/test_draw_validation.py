from datetime import date

import pytest

from app.domain.games import MEGA_645, POWER_655
from app.domain.models import DrawResult, DrawValidationError, validate_draw

D = date(2024, 1, 1)


def test_create_sorts_and_normalizes():
    draw = DrawResult.create(MEGA_645, " 00001 ", D, ["41", 3, 23, 12, 31, 18])
    assert draw.numbers == (3, 12, 18, 23, 31, 41)
    assert draw.draw_id == "00001"


def test_duplicate_numbers_rejected():
    with pytest.raises(DrawValidationError, match="Duplicate"):
        DrawResult.create(MEGA_645, "1", D, [1, 1, 2, 3, 4, 5])


@pytest.mark.parametrize("bad", [0, 46, -3])
def test_out_of_range_rejected(bad):
    with pytest.raises(DrawValidationError, match="out of range"):
        DrawResult.create(MEGA_645, "1", D, [bad, 2, 3, 4, 5, 6])


def test_range_depends_on_game():
    DrawResult.create(POWER_655, "1", D, [50, 2, 3, 4, 5, 55])
    with pytest.raises(DrawValidationError):
        DrawResult.create(MEGA_645, "1", D, [50, 2, 3, 4, 5, 55])


@pytest.mark.parametrize("nums", [[1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6, 7], []])
def test_invalid_draw_size_rejected(nums):
    with pytest.raises(DrawValidationError, match="must have 6"):
        DrawResult.create(MEGA_645, "1", D, nums)


@pytest.mark.parametrize("value", ["abc", None, 3.5, True])
def test_non_integer_rejected(value):
    with pytest.raises(DrawValidationError, match="Invalid number"):
        DrawResult.create(MEGA_645, "1", D, [value, 2, 3, 4, 5, 6])


def test_empty_draw_id_rejected():
    with pytest.raises(DrawValidationError, match="draw_id"):
        DrawResult.create(MEGA_645, "  ", D, [1, 2, 3, 4, 5, 6])


def test_unsorted_raw_draw_rejected():
    with pytest.raises(DrawValidationError, match="sorted"):
        validate_draw(MEGA_645, DrawResult("1", D, (6, 5, 4, 3, 2, 1)))


def test_bonus_rules():
    DrawResult.create(POWER_655, "1", D, [1, 2, 3, 4, 5, 6], bonus_number=7)
    with pytest.raises(DrawValidationError, match="no bonus"):
        DrawResult.create(MEGA_645, "1", D, [1, 2, 3, 4, 5, 6], bonus_number=7)
    with pytest.raises(DrawValidationError, match="duplicates"):
        DrawResult.create(POWER_655, "1", D, [1, 2, 3, 4, 5, 6], bonus_number=6)
    with pytest.raises(DrawValidationError, match="Bonus number out of range"):
        DrawResult.create(POWER_655, "1", D, [1, 2, 3, 4, 5, 6], bonus_number=56)
