from __future__ import annotations

import math
import warnings
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pandas as pd
import yfinance as yf


YAHOO_FIELDS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
    "Dividends": "dividends",
    "Stock Splits": "stock_splits",
    "Capital Gains": "capital_gains",
}


def _field_name(value: Any) -> str | None:
    text = str(value).strip()
    for yahoo_name in YAHOO_FIELDS:
        if text.casefold() == yahoo_name.casefold():
            return yahoo_name
    return None


def normalize_yfinance_columns(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Return one symbol's yfinance frame with stable, single-level field names."""
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        symbol_upper = symbol.upper()
        symbol_level = next(
            (
                level
                for level in range(result.columns.nlevels)
                if symbol_upper in {str(value).upper() for value in result.columns.get_level_values(level)}
            ),
            None,
        )
        if symbol_level is not None:
            matching_value = next(
                value
                for value in result.columns.get_level_values(symbol_level)
                if str(value).upper() == symbol_upper
            )
            result = result.xs(matching_value, axis=1, level=symbol_level, drop_level=True)

        if isinstance(result.columns, pd.MultiIndex):
            flattened: list[str] = []
            for column in result.columns:
                field = next((_field_name(part) for part in column if _field_name(part)), None)
                flattened.append(field or "_".join(str(part) for part in column))
            result.columns = flattened

    renamed: dict[Any, str] = {}
    for column in result.columns:
        field = _field_name(column)
        if field:
            renamed[column] = YAHOO_FIELDS[field]
    result = result.rename(columns=renamed)

    wanted = set(YAHOO_FIELDS.values())
    result = result.loc[:, [column for column in result.columns if column in wanted]]
    if result.columns.duplicated().any():
        result = result.T.groupby(level=0, sort=False).first().T

    for column in wanted:
        if column not in result:
            result[column] = 0.0 if column in {"dividends", "stock_splits", "capital_gains"} else None
    return result


def download_history(
    symbol: str,
    interval: str,
    *,
    period: str | None = None,
    start: date | datetime | None = None,
    prepost: bool = False,
) -> pd.DataFrame:
    # yfinance deliberately keeps SciPy optional, but repair=True imports it
    # when a suspicious dividend/price adjustment is encountered.
    try:
        import scipy  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "价格修复功能需要 SciPy；请在项目目录运行 "
            "`python -m pip install -e .` 后重试"
        ) from exc

    kwargs: dict[str, Any] = {
        "tickers": symbol,
        "interval": interval,
        "actions": True,
        "auto_adjust": False,
        # Daily repair improves long-history prices and corporate-action
        # adjustments. On intraday data it can launch finer-grained requests
        # outside Yahoo's retention window and print misleading nested errors;
        # raw 5m OHLC/actions remain complete without that reconstruction.
        "repair": interval == "1d",
        "keepna": False,
        "prepost": prepost,
        "progress": False,
        "threads": False,
        "group_by": "column",
        "multi_level_index": True,
        "timeout": 30,
    }
    if period is not None:
        kwargs["period"] = period
    if start is not None:
        kwargs["start"] = start
    # NumPy currently emits this warning from yfinance's own interval parser.
    # It does not affect the returned data and is not actionable by this project.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The 'generic' unit for NumPy timedelta is deprecated.*",
            category=DeprecationWarning,
            module=r"yfinance\..*",
        )
        frame = yf.download(**kwargs)
    if frame.empty:
        return normalize_yfinance_columns(frame, symbol)
    frame = normalize_yfinance_columns(frame, symbol)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or pd.isna(value):
        return default
    number = float(value)
    return number if math.isfinite(number) else default


def _volume(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _aware_utc(index_value: Any, *, daily: bool) -> datetime:
    stamp = pd.Timestamp(index_value)
    if stamp.tzinfo is None:
        if daily:
            stamp = stamp.tz_localize("America/New_York")
        else:
            stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC").to_pydatetime()


def dataframe_to_rows(frame: pd.DataFrame, symbol: str, interval: str) -> list[dict[str, Any]]:
    downloaded_at = datetime.now(UTC).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for index_value, values in frame.iterrows():
        timestamp = _aware_utc(index_value, daily=interval == "1d")
        row = {
            "symbol": symbol,
            "timestamp_utc": int(timestamp.timestamp()),
            "open": _number(values.get("open")),
            "high": _number(values.get("high")),
            "low": _number(values.get("low")),
            "close": _number(values.get("close")),
            "adj_close": _number(values.get("adj_close")),
            "volume": _volume(values.get("volume")),
            "dividends": _number(values.get("dividends"), 0.0),
            "stock_splits": _number(values.get("stock_splits"), 0.0),
            "capital_gains": _number(values.get("capital_gains"), 0.0),
            "source": "yahoo",
            "downloaded_at_utc": downloaded_at,
        }
        if interval == "1d":
            row["trading_date"] = pd.Timestamp(index_value).date().isoformat()
        rows.append(row)
    return rows


def daily_start(latest_date: str | None, overlap_days: int) -> date | None:
    if latest_date is None:
        return None
    return date.fromisoformat(latest_date) - timedelta(days=overlap_days)


def intraday_start(
    latest_timestamp: int | None,
    overlap_days: int,
    initial_days: int,
    now: datetime | None = None,
) -> datetime:
    current = now or datetime.now(UTC)
    earliest_available = current - timedelta(days=initial_days)
    if latest_timestamp is None:
        return earliest_available
    overlap_start = datetime.fromtimestamp(latest_timestamp, UTC) - timedelta(days=overlap_days)
    return max(earliest_available, overlap_start)
