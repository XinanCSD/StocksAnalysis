from __future__ import annotations

import tempfile
import unittest
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from stock_data.config import Settings
from stock_data.database import Database
from stock_data.charting import ChartCache
from stock_data.webapp import UpdateCoordinator, create_app


class WebApiTest(unittest.TestCase):
    def test_health_symbols_and_chart_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "market.sqlite")
            database.initialize(); database.add_symbols(["AAPL"])
            database.upsert_intraday([
                {"symbol": "AAPL", "timestamp_utc": 1773063000, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100, "dividends": 0, "stock_splits": 0, "capital_gains": 0, "source": "test", "downloaded_at_utc": datetime.now(UTC).isoformat()},
                {"symbol": "AAPL", "timestamp_utc": 1773063300, "open": 11, "high": 13, "low": 10, "close": 12, "volume": 120, "dividends": 0, "stock_splits": 0, "capital_gains": 0, "source": "test", "downloaded_at_utc": datetime.now(UTC).isoformat()},
            ])
            app = create_app(database, Settings(data_dir=Path(directory)), start_immediately=False)
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)
                symbols = client.get("/api/symbols").json()["symbols"]
                self.assertTrue(any(item["yahoo_symbol"] == "AAPL" for item in symbols))
                response = client.get("/api/chart?symbol=AAPL&interval=5m&limit=10")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["source_table"], "intraday_5m_prices")
                self.assertEqual([bar["time"] for bar in payload["bars"]], [1773063000, 1773063300])

    def test_symbol_update_lock_prevents_parallel_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "market.sqlite")
            database.initialize(); database.add_symbols(["AAPL"])
            coordinator = UpdateCoordinator(database, Settings(data_dir=Path(directory)), ChartCache())
            running = 0; peak = 0

            def update(_symbol: str) -> bool:
                nonlocal running, peak
                running += 1; peak = max(peak, running)
                import time; time.sleep(0.02)
                running -= 1
                return True

            coordinator.collector.update_symbol = update  # type: ignore[method-assign]

            async def exercise() -> None:
                await asyncio.gather(coordinator.update_symbol("AAPL"), coordinator.update_symbol("AAPL"))

            asyncio.run(exercise())
            self.assertEqual(peak, 1)


if __name__ == "__main__":
    unittest.main()
