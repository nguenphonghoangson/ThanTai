from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import routes_analysis, routes_backtest, routes_data, routes_sessions
from app.data.backtests import SqliteBacktestRepository
from app.data.providers import build_provider
from app.data.sync import vietnam_today
from app.database.sqlite import connect, init_schema
from app.domain.interfaces import LotteryDataProvider
from app.domain.games import list_games
from app.logging_config import configure_logging, log_event
from app.settings import Settings

WEB_DIR = Path(__file__).resolve().parent / "web"
logger = logging.getLogger(__name__)


def create_app(
    settings: Optional[Settings] = None,
    provider: Optional[LotteryDataProvider] = None,
    today: Callable[[], date] = vietnam_today,
) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        conn = connect(settings.db_path)
        try:
            init_schema(conn)
            interrupted = SqliteBacktestRepository(conn).fail_interrupted()
        finally:
            conn.close()
        # Backtests run one at a time in a worker thread owned by this app instance.
        app.state.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backtest")
        log_event(logger, "app.startup", db_path=str(settings.db_path), provider=app.state.provider.name,
                  interrupted_backtests=interrupted)
        try:
            yield
        finally:
            app.state.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Vietlott Analyzer", lifespan=lifespan)
    app.state.settings = settings
    app.state.provider = provider or build_provider(settings)
    app.state.today = today
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.include_router(routes_data.router)
    app.include_router(routes_analysis.router)
    app.include_router(routes_sessions.router)
    app.include_router(routes_backtest.router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "games": list_games(),
                "default_start": "2020-01-01",
                "default_end": today().isoformat(),
                "strategies": [
                    ("balanced", "Balanced"),
                    ("frequency", "Frequency"),
                    ("recent", "Recent"),
                    ("random", "Random baseline"),
                ],
                "weight_fields": [
                    ("frequency", "Frequency"),
                    ("recent_frequency", "Recent"),
                    ("gap", "Gap"),
                    ("pair", "Pair"),
                    ("historical", "Historical"),
                ],
            },
        )

    return app
