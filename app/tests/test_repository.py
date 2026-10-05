from datetime import date

import pytest

from app.domain.games import MEGA_645, POWER_655
from app.domain.models import DrawResult, DrawValidationError


def test_schema_has_required_indexes(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_draws_game", "idx_draws_draw_date", "idx_draws_draw_id"} <= names


def test_save_and_read_sorted_chronologically(repo, sample_mega_draws):
    assert repo.save_draws(MEGA_645, sample_mega_draws).inserted == 3
    ids = [d.draw_id for d in repo.get_draws(MEGA_645)]
    assert ids == ["00001", "00002", "00003"]


def test_duplicate_draws_ignored(repo, sample_mega_draws):
    repo.save_draws(MEGA_645, sample_mega_draws)
    again = repo.save_draws(MEGA_645, sample_mega_draws[:2])
    assert (again.inserted, again.unchanged, again.conflicts) == (0, 2, [])
    assert repo.count(MEGA_645) == 3


def test_conflicting_draw_is_reported_not_overwritten(repo, sample_mega_draws):
    repo.save_draws(MEGA_645, sample_mega_draws)
    original = sample_mega_draws[0]
    changed = DrawResult.create(MEGA_645, original.draw_id, original.draw_date, [1, 2, 3, 4, 5, 6])
    result = repo.save_draws(MEGA_645, [changed])
    assert result.conflicts == [original.draw_id] and result.inserted == 0
    stored = [d for d in repo.get_draws(MEGA_645) if d.draw_id == original.draw_id]
    assert stored == [original]


def test_duplicates_within_one_batch_inserted_once(repo, sample_mega_draws):
    assert repo.save_draws(MEGA_645, sample_mega_draws + sample_mega_draws).inserted == 3


def test_draw_id_gaps(repo):
    draws = [DrawResult.create(MEGA_645, f"{i:05d}", date(2024, 1, i), [1, 2, 3, 4, 5, 6]) for i in (3, 4, 7)]
    repo.save_draws(MEGA_645, draws)
    assert repo.draw_id_gaps(MEGA_645) == [5, 6]
    assert repo.first_last_draw_ids(MEGA_645) == ("00003", "00007")


def test_date_filter_is_inclusive(repo, sample_mega_draws):
    repo.save_draws(MEGA_645, sample_mega_draws)
    got = repo.get_draws(MEGA_645, date(2024, 1, 5), date(2024, 1, 7))
    assert [d.draw_date for d in got] == [date(2024, 1, 5), date(2024, 1, 7)]


def test_games_are_isolated(repo, sample_mega_draws, sample_power_draw):
    repo.save_draws(MEGA_645, sample_mega_draws)
    repo.save_draws(POWER_655, [sample_power_draw])
    assert repo.count(MEGA_645) == 3
    power = repo.get_draws(POWER_655)
    assert power == [sample_power_draw]
    assert power[0].bonus_number == 19


def test_date_bounds(repo, sample_mega_draws):
    assert repo.date_bounds(MEGA_645) is None
    repo.save_draws(MEGA_645, sample_mega_draws)
    assert repo.date_bounds(MEGA_645) == (date(2024, 1, 3), date(2024, 1, 7))


def test_invalid_draw_not_saved(repo):
    bad = DrawResult("9", date(2024, 1, 1), (1, 2, 3, 4, 5, 99))
    with pytest.raises(DrawValidationError):
        repo.save_draws(MEGA_645, [bad])
    assert repo.count(MEGA_645) == 0


def test_coverage_repository_merges(conn):
    from app.data.repository import SqliteCoverageRepository

    cov = SqliteCoverageRepository(conn)
    cov.add(MEGA_645, (date(2024, 1, 1), date(2024, 1, 10)))
    cov.add(MEGA_645, (date(2024, 1, 11), date(2024, 1, 20)))
    cov.add(MEGA_645, (date(2024, 3, 1), date(2024, 3, 5)))
    assert cov.get(MEGA_645) == [(date(2024, 1, 1), date(2024, 1, 20)), (date(2024, 3, 1), date(2024, 3, 5))]
    assert cov.get(POWER_655) == []
