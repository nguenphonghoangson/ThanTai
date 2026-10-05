from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DATASET_URL = "https://raw.githubusercontent.com/vietvudanh/vietlott-data/master/data"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000
    # Data source: "github" (public JSONL dataset) or "file" (local JSONL files in data_dir).
    provider: str = "github"
    dataset_url: str = DEFAULT_DATASET_URL
    data_dir: Optional[Path] = None
    cache_dir: Optional[Path] = None
    # Within this window a cached download is reused without contacting the server.
    cache_max_age_seconds: int = 3600
    http_timeout_seconds: float = 20.0
    # Coverage for the most recent days is never marked complete: results are published
    # after the evening draw and mirrored with a delay, so these days are re-checked.
    settle_days: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        data_dir = Path(env("VIETLOTT_DATA_DIR", PROJECT_ROOT / "data"))
        return cls(
            db_path=Path(env("VIETLOTT_DB", data_dir / "vietlott.sqlite3")),
            log_level=env("VIETLOTT_LOG_LEVEL", "INFO"),
            host=env("VIETLOTT_HOST", "127.0.0.1"),
            port=int(env("VIETLOTT_PORT", "8000")),
            provider=env("VIETLOTT_PROVIDER", "github"),
            dataset_url=env("VIETLOTT_DATASET_URL", DEFAULT_DATASET_URL),
            data_dir=data_dir,
            cache_dir=Path(env("VIETLOTT_CACHE_DIR", data_dir / "cache")),
            cache_max_age_seconds=int(env("VIETLOTT_CACHE_MAX_AGE", "3600")),
            http_timeout_seconds=float(env("VIETLOTT_HTTP_TIMEOUT", "20")),
            settle_days=int(env("VIETLOTT_SETTLE_DAYS", "2")),
        )

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir or self.db_path.parent

    @property
    def resolved_cache_dir(self) -> Path:
        return self.cache_dir or self.resolved_data_dir / "cache"
