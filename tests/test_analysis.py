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
            self.assertEqual(by_day["周一"].up_le_1, 1)
            self.assertEqual(by_day["周二"].down_le_1, 1)
            self.assertEqual(by_day["周一"].up_ratio, 1.0)
            self.assertEqual(by_day["周二"].down_ratio, 1.0)
            self.assertEqual(by_day["周三"].up_ratio, 0.0)
            self.assertEqual(by_day["周三"].down_ratio, 0.0)
            self.assertEqual(by_day["周三"].comparable_days, 1)

    def test_change_magnitude_bands_and_ratios(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "market.sqlite")
            database.initialize()
            database.add_symbols(["AAPL"])
            values = [
                ("2026-06-05", 100.0),
                ("2026-06-08", 100.5),  # Monday +0.5%
                ("2026-06-15", 102.0),  # Monday +1.49%
                ("2026-06-22", 105.0),  # Monday +2.94%
                ("2026-06-09", 110.0),  # Tuesday is chronologically earlier? inserted sorted below
            ]
            # Use consecutive dates so every move is assigned to its weekday.
            values = [
                ("2026-06-05", 100.0),  # Friday baseline
                ("2026-06-08", 100.5),  # Monday +0.5%
                ("2026-06-09", 101.5),  # Tuesday +0.995%
                ("2026-06-10", 103.1),  # Wednesday +1.576%
                ("2026-06-11", 105.2),  # Thursday +2.037%
                ("2026-06-12", 104.0),  # Friday -1.14%
                ("2026-06-15", 101.0),  # Monday -2.88%
                ("2026-06-16", 97.0),   # Tuesday -3.96%
            ]
            rows = [{
                "symbol": "AAPL", "trading_date": day, "timestamp_utc": index,
                "open": close, "high": close, "low": close, "close": close,
                "adj_close": close, "volume": 1, "dividends": 0,
                "stock_splits": 0, "capital_gains": 0, "source": "test",
                "downloaded_at_utc": datetime.now(UTC).isoformat(),
            } for index, (day, close) in enumerate(values)]
            database.upsert_daily(rows)
            result = analyze_daily_moves(database, ["AAPL"])[0]
            by_day = {item.weekday: item for item in result.weekdays}
            self.assertEqual((by_day["周一"].up_le_1, by_day["周一"].down_gt_2), (1, 1))
            self.assertEqual((by_day["周三"].up_1_to_2, by_day["周四"].up_gt_2), (1, 1))
            self.assertEqual(by_day["周一"].ratio("up_le_1"), 0.5)
            self.assertEqual(by_day["周一"].ratio("down_gt_2"), 0.5)

    def test_empty_weekday_ratios_are_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "market.sqlite")
            database.initialize()
            database.add_symbols(["AAPL"])
            rows = [{
                "symbol": "AAPL", "trading_date": "2026-06-08", "timestamp_utc": 1,
                "open": 100, "high": 100, "low": 100, "close": 100,
                "adj_close": 100, "volume": 1, "dividends": 0,
                "stock_splits": 0, "capital_gains": 0, "source": "test",
                "downloaded_at_utc": datetime.now(UTC).isoformat(),
            }]
            database.upsert_daily(rows)
            result = analyze_daily_moves(database, ["AAPL"])[0]
            self.assertEqual(result.weekdays[0].up_ratio, 0.0)
            self.assertEqual(result.weekdays[0].down_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
