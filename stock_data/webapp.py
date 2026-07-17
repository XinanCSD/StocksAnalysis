"""FastAPI dashboard, lifecycle-owned scheduler, and download coordination."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .charting import ChartCache, chart_data
from .config import Settings
from .database import Database
from .downloader import download_history
from .service import Collector
from .symbols import normalize_symbol, split_symbols


LOGGER = logging.getLogger(__name__)
WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


class AddSymbolsRequest(BaseModel):
    symbol: str


class UpdateCoordinator:
    def __init__(self, database: Database, settings: Settings, cache: ChartCache):
        self.database = database
        self.settings = settings
        self.cache = cache
        self.collector = Collector(database, settings)
        self._locks: dict[str, asyncio.Lock] = {}
        self._all_lock = asyncio.Lock()
        self.tasks: dict[str, dict[str, str]] = {}
        self.last_started: str | None = None
        self.last_finished: str | None = None
        self.background_tasks: set[asyncio.Task[object]] = set()

    def _lock(self, symbol: str) -> asyncio.Lock:
        return self._locks.setdefault(symbol, asyncio.Lock())

    async def update_symbol(self, symbol: str) -> bool:
        lock = self._lock(symbol)
        if lock.locked():
            return False
        async with lock:
            self.tasks[symbol] = {"status": "downloading", "stage": "daily"}
            try:
                result = await asyncio.to_thread(self.collector.update_symbol, symbol)
                self.tasks[symbol] = {"status": "ready" if result else "failed", "stage": "complete"}
                self.cache.clear()
                return result
            except Exception as exc:  # defensive: Collector normally captures its own errors
                self.tasks[symbol] = {"status": "failed", "stage": str(exc)[:200]}
                return False

    async def update_all(self) -> bool:
        if self._all_lock.locked():
            return False
        async with self._all_lock:
            self.last_started = datetime.now(UTC).isoformat(timespec="seconds")
            results = []
            for row in self.database.list_symbols(enabled_only=True):
                results.append(await self.update_symbol(row["symbol"]))
            self.last_finished = datetime.now(UTC).isoformat(timespec="seconds")
            return all(results)

    def schedule_symbol(self, symbol: str) -> bool:
        lock = self._lock(symbol)
        if lock.locked() or self.tasks.get(symbol, {}).get("status") == "queued":
            return False
        self.tasks[symbol] = {"status": "queued", "stage": "waiting"}
        task = asyncio.create_task(self.update_symbol(symbol))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        return True

    async def shutdown(self) -> None:
        self.collector.stopping = True
        for task in self.background_tasks:
            task.cancel()
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)


def create_app(database: Database, settings: Settings, *, start_immediately: bool = True) -> FastAPI:
    cache = ChartCache()
    coordinator = UpdateCoordinator(database, settings, cache)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            coordinator.update_all,
            trigger="interval",
            minutes=settings.update_interval_minutes,
            id="market-update",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(UTC) if start_immediately else None,
        )
        scheduler.start()
        app.state.scheduler = scheduler
        app.state.coordinator = coordinator
        LOGGER.info("Market scheduler started: every %d minutes", settings.update_interval_minutes)
        try:
            yield
        finally:
            await coordinator.shutdown()
            scheduler.shutdown(wait=False)
            LOGGER.info("Market scheduler stopped")

    app = FastAPI(title="Stock Dashboard", lifespan=lifespan)
    app.state.chart_cache = cache

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"error": {"code": "invalid_request", "message": str(exc)}})

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        scheduler: AsyncIOScheduler = app.state.scheduler
        try:
            with database.connect() as connection:
                connection.execute("SELECT 1").fetchone()
            database_ok = True
        except Exception:
            database_ok = False
        job = scheduler.get_job("market-update")
        return {
            "status": "ok" if database_ok else "degraded",
            "database": "ok" if database_ok else "unavailable",
            "scheduler": "running" if scheduler.running else "stopped",
            "last_update_started": coordinator.last_started,
            "last_update_finished": coordinator.last_finished,
            "next_update": job.next_run_time.isoformat() if job and job.next_run_time else None,
        }

    @app.get("/api/symbols")
    async def symbols() -> dict[str, Any]:
        result: list[dict[str, Any]] = []
        for row in database.status_rows():
            actual = row["symbol"]
            latest = row["intraday_success"] or row["daily_success"]
            result.append(
                {
                    "symbol": row["input_symbol"] or actual,
                    "yahoo_symbol": row["yahoo_symbol"] or actual,
                    "enabled": bool(row["enabled"]),
                    "daily_updated_at": row["daily_success"],
                    "intraday_updated_at": row["intraday_success"],
                    "daily_rows": row["daily_rows"], "intraday_rows": row["intraday_rows"],
                    "last_error": row["last_error"],
                    "task": coordinator.tasks.get(actual, {"status": "ready" if latest else "waiting"}),
                    "data_version": database.data_version(actual),
                }
            )
        return {"symbols": result, "has_extended_hours": database.has_extended_hours()}

    @app.post("/api/symbols", status_code=202)
    async def add_symbols(payload: AddSymbolsRequest) -> dict[str, Any]:
        requested = split_symbols(payload.symbol)
        if not requested:
            raise ValueError("请至少输入一个股票代码")
        added: list[dict[str, str]] = []
        for raw in requested:
            entered, yahoo = normalize_symbol(raw)
            existing = database.get_symbol(yahoo)
            if existing is None:
                # A small recent request validates Yahoo's actual symbol without a full backfill.
                valid = await asyncio.to_thread(download_history, yahoo, "1d", period="5d")
                if valid.empty:
                    raise HTTPException(
                        status_code=422,
                        detail={"error": {"code": "invalid_symbol", "message": f"Yahoo Finance 未找到 {raw}"}},
                    )
                database.add_symbols([entered])
            coordinator.schedule_symbol(yahoo)
            added.append({"symbol": entered, "yahoo_symbol": yahoo})
        return {"status": "accepted", "symbols": added}

    @app.post("/api/symbols/{symbol}/refresh", status_code=202)
    async def refresh_symbol(symbol: str) -> dict[str, str]:
        yahoo = normalize_symbol(symbol)[1]
        if database.get_symbol(yahoo) is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "股票不存在"}})
        accepted = coordinator.schedule_symbol(yahoo)
        return {"status": "accepted" if accepted else "already_running", "symbol": yahoo}

    @app.get("/api/chart")
    async def chart(
        symbol: str, interval: str = "1d", start: int | None = None, end: int | None = None,
        limit: int = 5000, session: str = "regular",
    ) -> dict[str, Any]:
        yahoo = normalize_symbol(symbol)[1]
        if database.get_symbol(yahoo) is None:
            raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "股票不存在"}})
        limit = max(1, min(limit, 20000))
        version = database.data_version(yahoo)
        key = (yahoo, interval, start, end, limit, session, version)
        result = cache.get(key)
        if result is None:
            result = await asyncio.to_thread(
                chart_data, database, yahoo, interval, start=start, end=end, limit=limit, session=session
            )
            cache.set(key, result)
        return {
            "symbol": result.symbol, "interval": result.interval,
            "source_interval": result.source_interval, "source_table": result.source_table,
            "timezone": "UTC", "session": result.session, "data_version": version, "bars": result.bars,
        }

    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/")
        async def dashboard() -> FileResponse:
            return FileResponse(WEB_DIST / "index.html")
    else:
        @app.get("/")
        async def dashboard_not_built() -> JSONResponse:
            return JSONResponse(status_code=503, content={"error": {"code": "frontend_not_built", "message": "前端尚未构建。请运行 stock-data run，或在 web 目录执行 npm run build。"}})

    return app
