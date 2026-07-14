from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd

from stock_data.downloader import (
    dataframe_to_rows,
    download_history,
    intraday_start,
    normalize_yfinance_columns,
)


class NormalizeColumnsTest(unittest.TestCase):
    def test_field_then_symbol_multiindex(self) -> None:
        columns = pd.MultiIndex.from_tuples(
            [("Close", "AAPL"), ("Dividends", "AAPL"), ("Stock Splits", "AAPL")]
        )
        frame = pd.DataFrame([[10.0, 0.2, 0.0]], index=pd.to_datetime(["2026-01-02"]), columns=columns)
        normalized = normalize_yfinance_columns(frame, "AAPL")
        self.assertEqual(normalized.loc[pd.Timestamp("2026-01-02"), "close"], 10.0)
        self.assertEqual(normalized.loc[pd.Timestamp("2026-01-02"), "dividends"], 0.2)
        self.assertIn("open", normalized.columns)

    def test_symbol_then_field_multiindex_and_rows(self) -> None:
        columns = pd.MultiIndex.from_tuples(
            [("AAPL", "Open"), ("AAPL", "Close"), ("AAPL", "Volume")]
        )
        index = pd.DatetimeIndex(["2026-07-09 13:30:00+00:00"])
        frame = pd.DataFrame([[9.0, 10.0, 123]], index=index, columns=columns)
        rows = dataframe_to_rows(normalize_yfinance_columns(frame, "AAPL"), "AAPL", "5m")
        self.assertEqual(rows[0]["open"], 9.0)
        self.assertEqual(rows[0]["volume"], 123)
        self.assertEqual(rows[0]["dividends"], 0.0)

    def test_intraday_start_is_limited_to_available_window(self) -> None:
        now = datetime(2026, 7, 10, tzinfo=UTC)
        old_latest = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp())
        self.assertEqual(intraday_start(old_latest, 3, 59, now), datetime(2026, 5, 12, tzinfo=UTC))

    @patch("stock_data.downloader.yf.download", return_value=pd.DataFrame())
    def test_repair_is_daily_only(self, mocked_download) -> None:
        download_history("SPY", "5m", period="1d")
        self.assertFalse(mocked_download.call_args.kwargs["repair"])

        download_history("SPY", "1d", period="5d")
        self.assertTrue(mocked_download.call_args.kwargs["repair"])


if __name__ == "__main__":
    unittest.main()
