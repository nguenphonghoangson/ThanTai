import json
from datetime import date

import httpx
import pytest

from app.data.cache import CachedHttpClient
from app.data.errors import DataFetchError, MalformedDataError
from app.data.providers import GithubDatasetProvider, JsonlFileProvider, build_provider
from app.domain.games import MEGA_645, POWER_655, LotteryGameConfig
from app.settings import Settings

URL = "https://example.test/data/power645.jsonl"
BODY = "\n".join(
    json.dumps({"id": f"{i:05d}", "date": f"2024-01-{i:02d}", "result": [1, 2, 3, 4, 5, 5 + i]})
    for i in range(1, 6)
)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Server:
    """Scriptable transport: a list of responses (or exceptions) served in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(tmp_path, server, clock=None, max_age=3600):
    return CachedHttpClient(
        tmp_path / "cache", max_age_seconds=max_age, retries=3, backoff_seconds=0,
        transport=httpx.MockTransport(server.handler), clock=clock or Clock(), sleep=lambda s: None,
    )


def test_cache_miss_then_hit_within_max_age(tmp_path):
    server = Server(httpx.Response(200, text=BODY, headers={"etag": '"v1"'}))
    client = make_client(tmp_path, server)
    first, second = client.get_text(URL), client.get_text(URL)
    assert (first.from_cache, second.from_cache) == (False, True)
    assert second.text == BODY and len(server.requests) == 1


def test_revalidates_with_etag_after_max_age(tmp_path):
    clock = Clock()
    server = Server(httpx.Response(200, text=BODY, headers={"etag": '"v1"'}), httpx.Response(304))
    client = make_client(tmp_path, server, clock)
    client.get_text(URL)
    clock.now += 7200
    r = client.get_text(URL)
    assert r.from_cache and r.text == BODY
    assert server.requests[1].headers["if-none-match"] == '"v1"'


def test_force_revalidate_skips_fresh_cache(tmp_path):
    server = Server(httpx.Response(200, text="old", headers={"etag": '"v1"'}), httpx.Response(200, text="new"))
    client = make_client(tmp_path, server)
    client.get_text(URL)
    assert client.get_text(URL, force_revalidate=True).text == "new"


def test_retries_transient_errors(tmp_path):
    server = Server(httpx.ConnectError("down"), httpx.Response(503), httpx.Response(200, text=BODY))
    assert make_client(tmp_path, server).get_text(URL).text == BODY
    assert len(server.requests) == 3


def test_does_not_retry_404(tmp_path):
    server = Server(httpx.Response(404), httpx.Response(200, text=BODY))
    with pytest.raises(DataFetchError, match="404"):
        make_client(tmp_path, server).get_text(URL)
    assert len(server.requests) == 1


def test_network_failure_without_cache_raises(tmp_path):
    server = Server(*[httpx.ConnectError("down")] * 3)
    with pytest.raises(DataFetchError, match="ConnectError"):
        make_client(tmp_path, server).get_text(URL)


def test_network_failure_falls_back_to_stale_cache(tmp_path):
    clock = Clock()
    server = Server(httpx.Response(200, text=BODY), *[httpx.ReadTimeout("slow")] * 3)
    client = make_client(tmp_path, server, clock)
    client.get_text(URL)
    clock.now += 7200
    r = client.get_text(URL)
    assert r.stale and r.text == BODY


def test_github_provider_filters_range(tmp_path):
    server = Server(httpx.Response(200, text=BODY))
    provider = GithubDatasetProvider(make_client(tmp_path, server), "https://example.test/data/")
    result = provider.fetch(MEGA_645, date(2024, 1, 2), date(2024, 1, 4))
    assert [d.draw_id for d in result.draws] == ["00002", "00003", "00004"]
    assert str(server.requests[0].url) == URL
    # The second range comes from the cached download.
    provider.fetch(MEGA_645, date(2024, 1, 5), date(2024, 1, 5))
    assert len(server.requests) == 1


def test_github_provider_html_challenge_page_is_malformed(tmp_path):
    server = Server(httpx.Response(200, text="<!DOCTYPE html><title>Just a moment...</title>"))
    provider = GithubDatasetProvider(make_client(tmp_path, server), "https://example.test/data")
    with pytest.raises(MalformedDataError):
        provider.fetch(MEGA_645, date(2024, 1, 1), date(2024, 1, 31))


def test_github_provider_unknown_game(tmp_path):
    provider = GithubDatasetProvider(make_client(tmp_path, Server()), "https://example.test/data")
    other = LotteryGameConfig(key="lotto535", name="Lotto 5/35", min_number=1, max_number=35, numbers_per_draw=5)
    with pytest.raises(DataFetchError, match="no data"):
        provider.fetch(other, date(2024, 1, 1), date(2024, 1, 31))


def test_file_provider(tmp_path):
    (tmp_path / "mega645.jsonl").write_text(BODY, encoding="utf-8")
    provider = JsonlFileProvider(tmp_path)
    assert len(provider.fetch(MEGA_645, date(2024, 1, 1), date(2024, 1, 31)).draws) == 5
    with pytest.raises(DataFetchError, match="Cannot read"):
        provider.fetch(POWER_655, date(2024, 1, 1), date(2024, 1, 31))


def test_build_provider(tmp_path):
    base = Settings(db_path=tmp_path / "db.sqlite3")
    assert isinstance(build_provider(base), GithubDatasetProvider)
    file_settings = Settings(db_path=tmp_path / "db.sqlite3", provider="file")
    assert isinstance(build_provider(file_settings), JsonlFileProvider)
    with pytest.raises(ValueError):
        build_provider(Settings(db_path=tmp_path / "db.sqlite3", provider="ftp"))
