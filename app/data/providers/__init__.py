from __future__ import annotations

from app.data.cache import CachedHttpClient
from app.domain.models import FetchResult
from app.data.providers.file import JsonlFileProvider
from app.data.providers.github_dataset import GithubDatasetProvider
from app.domain.interfaces import LotteryDataProvider
from app.settings import Settings

__all__ = ["FetchResult", "GithubDatasetProvider", "JsonlFileProvider", "build_provider"]


def build_provider(settings: Settings) -> LotteryDataProvider:
    if settings.provider == "github":
        http = CachedHttpClient(
            settings.resolved_cache_dir,
            max_age_seconds=settings.cache_max_age_seconds,
            timeout_seconds=settings.http_timeout_seconds,
        )
        return GithubDatasetProvider(http, settings.dataset_url)
    if settings.provider == "file":
        return JsonlFileProvider(settings.resolved_data_dir / "import")
    raise ValueError(f"Unknown provider '{settings.provider}' (expected 'github' or 'file')")
