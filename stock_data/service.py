from __future__ import annotations

import logging
import signal
import time
from datetime import datetime

from .config import Settings
from .database import Database
from .downloader import dataframe_to_rows, daily_start, download_history, intraday_start


LOGGER = logging.getLogger(__name__)


class Collector:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self.stopping = False

    def update_symbol(self, symbol: str) -> bool:
        success = True
        latest_daily = self.database.latest_daily_date(symbol)
        start = daily_start(latest_daily, self.settings.daily_overlap_days)
        try:
            if start is None:
                LOGGER.info("%s 1d: downloading full history", symbol)
                frame = download_history(symbol, "1d", period="max", prepost=self.settings.prepost)
            else:
                LOGGER.info("%s 1d: downloading from %s", symbol, start)
                frame = download_history(symbol, "1d", start=start, prepost=self.settings.prepost)
            if frame.empty:
                raise RuntimeError("Yahoo returned no daily rows")
            rows = dataframe_to_rows(frame, symbol, "1d")
            self.database.upsert_daily(rows)
            self.database.record_success(symbol, "1d", len(rows))
            LOGGER.info("%s 1d: received %d rows", symbol, len(rows))
        except Exception as exc:
            success = False
            self.database.record_failure(symbol, "1d", str(exc))
            LOGGER.exception("%s 1d: update failed", symbol)

        time.sleep(self.settings.request_pause_seconds)
        latest_5m = self.database.latest_intraday_timestamp(symbol)
        start_5m = intraday_start(
            latest_5m,
            self.settings.intraday_overlap_days,
            self.settings.intraday_initial_days,
        )
        try:
            LOGGER.info("%s 5m: downloading from %s", symbol, start_5m.isoformat())
            frame = download_history(symbol, "5m", start=start_5m, prepost=self.settings.prepost)
            if frame.empty:
                raise RuntimeError("Yahoo returned no 5-minute rows")
            rows = dataframe_to_rows(frame, symbol, "5m")
            self.database.upsert_intraday(rows)
            self.database.record_success(symbol, "5m", len(rows))
            LOGGER.info("%s 5m: received %d rows", symbol, len(rows))
        except Exception as exc:
            success = False
            self.database.record_failure(symbol, "5m", str(exc))
            LOGGER.exception("%s 5m: update failed", symbol)
        return success

    def update_all(self) -> bool:
        symbols = [row["symbol"] for row in self.database.list_symbols(enabled_only=True)]
        LOGGER.info("Starting update for %d symbols", len(symbols))
        success = True
        for position, symbol in enumerate(symbols):
            if self.stopping:
                break
            if position:
                time.sleep(self.settings.request_pause_seconds)
            success = self.update_symbol(symbol) and success
        return success

    def run_forever(self) -> None:
        def stop(_signum: int, _frame: object) -> None:
            LOGGER.info("Stop requested; finishing current request")
            self.stopping = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        interval_seconds = self.settings.update_interval_minutes * 60
        while not self.stopping:
            started = time.monotonic()
            self.update_all()
            remaining = max(0.0, interval_seconds - (time.monotonic() - started))
            LOGGER.info("Update finished; next run in %.0f seconds", remaining)
            deadline = time.monotonic() + remaining
            while not self.stopping and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))
