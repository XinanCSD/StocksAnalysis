from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stock_data.database import Database


class DatabaseTest(unittest.TestCase):
    def test_seed_and_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "market.sqlite")
            database.initialize()
            self.assertIn("^NDX", [row["symbol"] for row in database.list_symbols()])
            row = {
                "symbol": "SPY", "trading_date": "2026-07-09", "timestamp_utc": 1,
                "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "adj_close": 1.4,
                "volume": 100, "dividends": 0.0, "stock_splits": 0.0,
                "capital_gains": 0.0, "source": "yahoo", "downloaded_at_utc": "now",
            }
            database.upsert_daily([row])
            row["close"] = 1.7
            database.upsert_daily([row])
            with database.connect() as connection:
                result = connection.execute("SELECT close FROM daily_prices WHERE symbol='SPY'").fetchone()
            self.assertEqual(result["close"], 1.7)


if __name__ == "__main__":
    unittest.main()

