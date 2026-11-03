from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from stock_data.analysis import analyze_daily_moves
from stock_data.database import Database


class DailyMoveAnalysisTest(unittest.TestCase):
    def test_counts_direction_by_current_day_weekday(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "market.sqlite")
            database.initialize()
            database.add_symbols(["AAPL"])
            rows = []
            values = [
                ("2026-06-05", 100),  # Friday baseline
                ("2026-06-08", 101),  # Monday up
                ("2026-06-09", 100),  # Tuesday down
                ("2026-06-10", 100),  # Wednesday unchanged
                ("2026-06-11", 102),  # Thursday up
                ("2026-06-12", 99),   # Friday down
            ]
            for index, (day, close) in enumerate(values):
                rows.append({
                    "symbol": "AAPL", "trading_date": day, "timestamp_utc": index,
                    "open": close, "high": close, "low": close, "close": close,
                    "adj_close": close, "volume": 1, "dividends": 0,
                    "stock_splits": 0, "capital_gains": 0, "source": "test",
                    "downloaded_at_utc": datetime.now(UTC).isoformat(),
                })
            database.upsert_daily(rows)
            result = analyze_daily_moves(database, ["AAPL"])[0]
            by_day = {item.weekday: item for item in result.weekdays}
            self.assertEqual(by_day["周一"].up_days, 1)
            self.assertEqual(by_day["周二"].down_days, 1)
            self.assertEqual(by_day["周三"].unchanged_days, 1)
            self.assertEqual(by_day["周四"].up_days, 1)
            self.assertEqual(by_day["周五"].down_days, 1)


if __name__ == "__main__":
    unittest.main()
