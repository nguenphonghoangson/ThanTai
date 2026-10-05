"""HTTP download cache on disk.

A cached body is reused without any request while it is younger than ``max_age``;
after that it is revalidated with ``If-None-Match``. If the network fails and a
stale copy exists, the stale copy is returned (and logged) instead of failing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx

from app.data.errors import DataFetchError
from app.logging_config import log_event

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class CachedResponse:
    text: str
    from_cache: bool
    stale: bool = False


class CachedHttpClient:
    def __init__(
        self,
        cache_dir: Path,
        max_age_seconds: int = 3600,
        timeout_seconds: float = 20.0,
        retries: int = 3,
        backoff_seconds: float = 1.0,
        transport: Optional[httpx.BaseTransport] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._dir = cache_dir
        self._max_age = max_age_seconds
        self._timeout = timeout_seconds
        self._retries = retries
        self._backoff = backoff_seconds
        self._transport = transport
        self._clock = clock
        self._sleep = sleep

    def get_text(self, url: str, force_revalidate: bool = False) -> CachedResponse:
        body_path, meta_path = self._paths(url)
        meta = _read_meta(meta_path) if body_path.exists() else None

        if meta and not force_revalidate and self._clock() - meta["fetched_at"] < self._max_age:
            log_event(logger, "cache.hit", url=url, age_s=round(self._clock() - meta["fetched_at"]))
            return CachedResponse(body_path.read_text(encoding="utf-8"), from_cache=True)

        headers = {"If-None-Match": meta["etag"]} if meta and meta.get("etag") else {}
        try:
            response = self._request(url, headers)
        except DataFetchError as exc:
            if meta:
                log_event(logger, "cache.stale_fallback", logging.WARNING, url=url, error=str(exc))
                return CachedResponse(body_path.read_text(encoding="utf-8"), from_cache=True, stale=True)
            raise

        if response.status_code == 304 and meta:
            meta["fetched_at"] = self._clock()
            _write_meta(meta_path, meta)
            log_event(logger, "cache.revalidated", url=url)
            return CachedResponse(body_path.read_text(encoding="utf-8"), from_cache=True)

        text = response.text
        self._dir.mkdir(parents=True, exist_ok=True)
        body_path.write_text(text, encoding="utf-8")
        _write_meta(meta_path, {"url": url, "etag": response.headers.get("etag"), "fetched_at": self._clock()})
        log_event(logger, "cache.miss", url=url, bytes=len(text))
        return CachedResponse(text, from_cache=False)

    def _request(self, url: str, headers: dict) -> httpx.Response:
        last_error = "unknown error"
        with httpx.Client(timeout=self._timeout, transport=self._transport, follow_redirects=True) as client:
            for attempt in range(1, self._retries + 1):
                try:
                    response = client.get(url, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code in (200, 304):
                        return response
                    last_error = f"HTTP {response.status_code}"
                    if response.status_code not in RETRY_STATUSES:
                        break
                if attempt < self._retries:
                    log_event(logger, "http.retry", logging.WARNING, url=url, attempt=attempt, error=last_error)
                    self._sleep(self._backoff * 2 ** (attempt - 1))
        raise DataFetchError(f"GET {url} failed: {last_error}")

    def _paths(self, url: str):
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self._dir / f"{key}.body", self._dir / f"{key}.meta.json"


def _read_meta(path: Path) -> Optional[dict]:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        return meta if isinstance(meta.get("fetched_at"), (int, float)) else None
    except (OSError, ValueError):
        return None


def _write_meta(path: Path, meta: dict) -> None:
    path.write_text(json.dumps(meta), encoding="utf-8")
