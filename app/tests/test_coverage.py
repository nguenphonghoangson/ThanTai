from datetime import date

from app.data.coverage import merge_ranges, missing_ranges


def d(m, day, y=2024):
    return date(y, m, day)


def test_merge_overlapping_and_adjacent():
    ranges = [(d(1, 11), d(1, 20)), (d(1, 1), d(1, 10)), (d(1, 15), d(1, 25)), (d(3, 1), d(3, 2))]
    assert merge_ranges(ranges) == [(d(1, 1), d(1, 25)), (d(3, 1), d(3, 2))]


def test_merge_ignores_inverted_ranges():
    assert merge_ranges([(d(2, 1), d(1, 1))]) == []


def test_nothing_covered():
    assert missing_ranges((d(1, 1), d(1, 31)), []) == [(d(1, 1), d(1, 31))]


def test_fully_covered():
    assert missing_ranges((d(1, 5), d(1, 10)), [(d(1, 1), d(1, 31))]) == []


def test_extension_fetches_only_new_tail():
    # Spec example: DB has 2020→2025, user asks 2020→2026 → fetch only 2026.
    covered = [(date(2020, 1, 1), date(2025, 12, 31))]
    assert missing_ranges((date(2020, 1, 1), date(2026, 10, 1)), covered) == [(date(2026, 1, 1), date(2026, 10, 1))]


def test_holes_and_both_ends():
    covered = [(d(1, 5), d(1, 10)), (d(1, 20), d(1, 25))]
    assert missing_ranges((d(1, 1), d(1, 31)), covered) == [
        (d(1, 1), d(1, 4)), (d(1, 11), d(1, 19)), (d(1, 26), d(1, 31)),
    ]


def test_covered_outside_request_is_ignored():
    covered = [(d(1, 1), d(1, 3)), (d(2, 1), d(2, 5))]
    assert missing_ranges((d(1, 10), d(1, 12)), covered) == [(d(1, 10), d(1, 12))]
