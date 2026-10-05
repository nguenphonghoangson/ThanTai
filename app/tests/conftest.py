from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.data.repository import SqliteDrawRepository
from app.database.sqlite import connect, init_schema
from app.domain.games import MEGA_645, POWER_655
from app.data.errors import DataFetchError
from app.domain.models import DrawResult, FetchResult
from app.main import create_app
from app.settings import Settings


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return SqliteDrawRepository(conn)


@pytest.fixture
def sample_mega_draws():
    return [
        DrawResult.create(MEGA_645, "00002", date(2024, 1, 5), [3, 12, 18, 23, 31, 41]),
        DrawResult.create(MEGA_645, "00001", date(2024, 1, 3), [1, 7, 9, 22, 33, 45]),
        DrawResult.create(MEGA_645, "00003", date(2024, 1, 7), [2, 4, 6, 8, 10, 12]),
    ]


@pytest.fixture
def sample_power_draw():
    return DrawResult.create(POWER_655, "00100", date(2024, 1, 4), [5, 14, 27, 28, 40, 55], bonus_number=19)


class FakeProvider:
    """In-memory provider that records every fetch call."""

    name = "fake"

    def __init__(self, draws_by_game=None, error=None, stale=False):
        self.draws_by_game = draws_by_game or {}
        self.error = error
        self.stale = stale
        self.calls = []

    def fetch(self, game, start_date, end_date, refresh=False):
        self.calls.append((game.key, start_date, end_date, refresh))
        if self.error:
            raise DataFetchError(self.error)
        draws = [d for d in self.draws_by_game.get(game.key, []) if start_date <= d.draw_date <= end_date]
        return FetchResult(draws=draws, source="fake://", stale=self.stale)


@pytest.fixture
def fake_provider(sample_mega_draws):
    return FakeProvider({"mega645": sample_mega_draws})


@pytest.fixture
def client(tmp_path, fake_provider):
    app = create_app(
        Settings(db_path=tmp_path / "test.sqlite3", log_level="WARNING"),
        provider=fake_provider,
        today=lambda: date(2024, 2, 1),
    )
    with TestClient(app) as c:
        yield c
