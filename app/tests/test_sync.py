from datetime import date

import pytest

from app.data.errors import DataFetchError
from app.data.repository import SqliteCoverageRepository, SqliteDrawRepository
from app.data.sync import DrawSyncService
from app.domain.games import MEGA_645
from app.domain.models import DrawResult
from app.tests.conftest import FakeProvider

TODAY = date(2024, 3, 1)


def mega_draws():
    # Wed/Fri/Sun-like cadence across Jan–Feb 2024.
    days = [date(2024, 1, 3), date(2024, 1, 5), date(2024, 1, 7), date(2024, 2, 2), date(2024, 2, 28)]
    return [DrawResult.create(MEGA_645, f"{i + 1:05d}", day, [1, 2, 3, 4, 5, 6 + i]) for i, day in enumerate(days)]


@pytest.fixture
def provider():
    return FakeProvider({"mega645": mega_draws()})


@pytest.fixture
def service(conn, provider):
    return DrawSyncService(provider, SqliteDrawRepository(conn), SqliteCoverageRepository(conn), TODAY, settle_days=2)


def test_first_sync_fetches_whole_range(service, provider, conn):
    report = service.sync(MEGA_645, date(2024, 1, 1), date(2024, 2, 29))
    assert provider.calls == [("mega645", date(2024, 1, 1), date(2024, 2, 29), False)]
    assert report.inserted == 5
    # Settled through today - 2 days only.
    assert SqliteCoverageRepository(conn).get(MEGA_645) == [(date(2024, 1, 1), date(2024, 2, 28))]


def test_resync_refetches_only_unsettled_days(service, provider):
    service.sync(MEGA_645, date(2024, 1, 1), date(2024, 2, 29))
    provider.calls.clear()
    report = service.sync(MEGA_645, date(2024, 1, 1), date(2024, 2, 29))
    assert provider.calls == [("mega645", date(2024, 2, 29), date(2024, 2, 29), False)]
    assert report.inserted == 0


def test_extending_range_fetches_only_new_part(service, provider):
    service.sync(MEGA_645, date(2024, 1, 1), date(2024, 1, 31))
    provider.calls.clear()
    report = service.sync(MEGA_645, date(2024, 1, 1), date(2024, 2, 27))
    assert provider.calls == [("mega645", date(2024, 2, 1), date(2024, 2, 27), False)]
    assert report.inserted == 1  # 2024-02-02


def test_earlier_start_fetches_only_prefix(service, provider):
    service.sync(MEGA_645, date(2024, 1, 5), date(2024, 1, 31))
    provider.calls.clear()
    service.sync(MEGA_645, date(2024, 1, 1), date(2024, 1, 31))
    assert provider.calls == [("mega645", date(2024, 1, 1), date(2024, 1, 4), False)]


def test_force_ignores_coverage_and_requests_refresh(service, provider):
    service.sync(MEGA_645, date(2024, 1, 1), date(2024, 1, 31))
    provider.calls.clear()
    report = service.sync(MEGA_645, date(2024, 1, 1), date(2024, 1, 31), force=True)
    assert provider.calls == [("mega645", date(2024, 1, 1), date(2024, 1, 31), True)]
    assert report.unchanged == 3


def test_end_is_clipped_to_today(service, provider):
    report = service.sync(MEGA_645, date(2024, 2, 1), date(2030, 1, 1))
    assert report.requested == (date(2024, 2, 1), TODAY)
    assert provider.calls[0][2] == TODAY


def test_future_only_range_is_a_no_op(service, provider):
    report = service.sync(MEGA_645, date(2025, 1, 1), date(2025, 2, 1))
    assert provider.calls == [] and report.up_to_date


def test_stale_source_does_not_record_coverage(conn, provider):
    provider.stale = True
    svc = DrawSyncService(provider, SqliteDrawRepository(conn), SqliteCoverageRepository(conn), TODAY)
    report = svc.sync(MEGA_645, date(2024, 1, 1), date(2024, 1, 31))
    assert report.stale_source and report.inserted == 3
    assert SqliteCoverageRepository(conn).get(MEGA_645) == []


def test_provider_failure_propagates_and_records_nothing(conn):
    svc = DrawSyncService(FakeProvider(error="boom"), SqliteDrawRepository(conn), SqliteCoverageRepository(conn), TODAY)
    with pytest.raises(DataFetchError):
        svc.sync(MEGA_645, date(2024, 1, 1), date(2024, 1, 31))
    assert SqliteCoverageRepository(conn).get(MEGA_645) == []


def test_conflicts_surface_in_report(service, provider):
    service.sync(MEGA_645, date(2024, 1, 1), date(2024, 1, 31))
    changed = DrawResult.create(MEGA_645, "00001", date(2024, 1, 3), [10, 20, 30, 40, 41, 42])
    provider.draws_by_game["mega645"][0] = changed
    report = service.sync(MEGA_645, date(2024, 1, 1), date(2024, 1, 31), force=True)
    assert report.conflicts == ["00001"]


def test_inverted_range_rejected(service):
    with pytest.raises(ValueError):
        service.sync(MEGA_645, date(2024, 2, 1), date(2024, 1, 1))
