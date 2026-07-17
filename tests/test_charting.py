from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from stock_data.charting import aggregate_daily, aggregate_intraday, chart_data
from stock_data.database import Database


def intraday_frame(times: list[str]) -> pd.DataFrame:
    index = pd.to_datetime(times, utc=True)
    values = list(range(1, len(index) + 1))
    return pd.DataFrame({"open": values, "high": [v + 1 for v in values], "low": [v - 1 for v in values], "close": values, "volume": [10] * len(index)}, index=index)


class ChartAggregationTest(unittest.TestCase):
    def test_1h_anchors_at_new_york_0930_and_keeps_partial_bar(self) -> None:
        times = list(pd.date_range("2026-03-09 13:30", periods=78, freq="5min", tz="UTC").astype(str))
        result = aggregate_intraday(intraday_frame(times), 60, "regular")
        self.assertEqual(len(result), 7)
        self.assertEqual(result.iloc[0]["open"], 1)
        self.assertEqual(result.iloc[0]["close"], 12)
        self.assertEqual(result.iloc[-1]["volume"], 60)

    def test_2h_and_4h_do_not_cross_trading_days(self) -> None:
        times = ["2026-03-09 13:30", "2026-03-09 19:55", "2026-03-10 13:30", "2026-03-10 19:55"]
        frame = intraday_frame(times)
        self.assertEqual(len(aggregate_intraday(frame, 120, "regular")), 4)
        self.assertEqual(len(aggregate_intraday(frame, 240, "regular")), 4)

    def test_dst_regular_session_filters_correctly(self) -> None:
        # March 6 uses UTC-5; March 9 follows the US DST change and uses UTC-4.
        frame = intraday_frame(["2026-03-06 14:30", "2026-03-09 13:30", "2026-03-09 13:25"])
        result = aggregate_intraday(frame, 5, "regular")
        self.assertEqual(len(result), 2)

    def test_week_month_year_use_last_actual_trading_bar(self) -> None:
        frame = intraday_frame(["2025-12-31 05:00", "2026-01-02 05:00", "2026-01-30 05:00", "2026-02-02 05:00"])
        weekly = aggregate_daily(frame, "1wk")
        monthly = aggregate_daily(frame, "1mo")
        yearly = aggregate_daily(frame, "1y")
        self.assertEqual(len(weekly), 3)
        self.assertEqual(len(monthly), 3)
        self.assertEqual(len(yearly), 2)
        self.assertEqual(monthly.index[1].day, 30)

    def test_chart_api_source_is_sorted_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "market.sqlite")
            database.initialize(); database.add_symbols(["AAPL"])
            rows = []
            for timestamp in (1773063000, 1773063300, 1773063600):
                rows.append({"symbol": "AAPL", "timestamp_utc": timestamp, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10, "dividends": 0, "stock_splits": 0, "capital_gains": 0, "source": "test", "downloaded_at_utc": datetime.now(UTC).isoformat()})
            database.upsert_intraday(rows)
            result = chart_data(database, "AAPL", "5m")
            self.assertEqual(result.source_table, "intraday_5m_prices")
            self.assertEqual([bar["time"] for bar in result.bars], sorted(bar["time"] for bar in result.bars))


if __name__ == "__main__":
    unittest.main()
