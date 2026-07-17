"""Read-only chart queries and on-demand OHLCV aggregation."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from .database import Database


INTRADAY_INTERVALS = {"5m": 5, "30m": 30, "1h": 60, "2h": 120, "4h": 240}
DAILY_INTERVALS = {"1d", "1wk", "1mo", "1y"}
SUPPORTED_INTERVALS = set(INTRADAY_INTERVALS) | DAILY_INTERVALS
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ChartResult:
    symbol: str
    interval: str
    source_interval: str
    source_table: str
    session: str
    bars: list[dict[str, int | float]]


class ChartCache:
    def __init__(self, max_items: int = 64):
        self.max_items = max_items
        self._items: OrderedDict[tuple[object, ...], ChartResult] = OrderedDict()

    def get(self, key: tuple[object, ...]) -> ChartResult | None:
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def set(self, key: tuple[object, ...], value: ChartResult) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


def _raw_frame(
    database: Database, symbol: str, intraday: bool, start: int | None, end: int | None
) -> pd.DataFrame:
    table = "intraday_5m_prices" if intraday else "daily_prices"
    where = ["symbol = ?", "open IS NOT NULL", "high IS NOT NULL", "low IS NOT NULL", "close IS NOT NULL"]
    parameters: list[object] = [symbol]
    if start is not None:
        where.append("timestamp_utc >= ?")
        parameters.append(start)
    if end is not None:
        where.append("timestamp_utc <= ?")
        parameters.append(end)
    query = (
        "SELECT timestamp_utc, open, high, low, close, volume FROM " + table + " WHERE "
        + " AND ".join(where) + " ORDER BY timestamp_utc"
    )
    with database.connect() as connection:
        frame = pd.read_sql_query(query, connection, params=parameters)
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame.pop("timestamp_utc"), unit="s", utc=True)
    frame = frame.set_index("timestamp")
    return frame


def _aggregate(frame: pd.DataFrame, group_key: pd.Series) -> pd.DataFrame:
    grouped = frame.groupby(group_key, sort=True)
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    # Preserve the timestamp of the last actual bar; never invent holiday bars.
    result["timestamp"] = grouped.apply(lambda rows: rows.index[-1])
    return result.set_index("timestamp")


def _regular_session(frame: pd.DataFrame) -> pd.DataFrame:
    local = frame.index.tz_convert(NY)
    minutes = local.hour * 60 + local.minute
    return frame[(local.weekday < 5) & (minutes >= 9 * 60 + 30) & (minutes < 16 * 60)]


def aggregate_intraday(frame: pd.DataFrame, minutes: int, session: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    if session == "regular":
        frame = _regular_session(frame)
    if frame.empty or minutes == 5:
        return frame
    local = frame.index.tz_convert(NY)
    dates = pd.Series(local.date, index=frame.index)
    if session == "regular":
        offset = local.hour * 60 + local.minute - (9 * 60 + 30)
        bucket = offset // minutes
        keys = pd.Series(list(zip(dates, bucket)), index=frame.index)
    else:
        # Extended-hours bars may be present. Keep each exchange-local date separate.
        bucket = (local.hour * 60 + local.minute) // minutes
        keys = pd.Series(list(zip(dates, bucket)), index=frame.index)
    return _aggregate(frame, keys)


def aggregate_daily(frame: pd.DataFrame, interval: str) -> pd.DataFrame:
    if frame.empty or interval == "1d":
        return frame
    local = frame.index.tz_convert(NY)
    local_naive = local.tz_localize(None)
    if interval == "1wk":
        key = local_naive.to_period("W-FRI")
    elif interval == "1mo":
        key = local_naive.to_period("M")
    elif interval == "1y":
        key = local_naive.to_period("Y")
    else:
        raise ValueError(interval)
    return _aggregate(frame, pd.Series(key, index=frame.index))


def chart_data(
    database: Database,
    symbol: str,
    interval: str,
    *,
    start: int | None = None,
    end: int | None = None,
    limit: int = 5000,
    session: Literal["regular", "extended"] = "regular",
) -> ChartResult:
    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(f"不支持的周期: {interval}")
    if session not in {"regular", "extended"}:
        raise ValueError("session 必须为 regular 或 extended")
    intraday = interval in INTRADAY_INTERVALS
    frame = _raw_frame(database, symbol, intraday, start, end)
    if intraday:
        frame = aggregate_intraday(frame, INTRADAY_INTERVALS[interval], session)
        source_interval, source_table = "5m", "intraday_5m_prices"
    else:
        frame = aggregate_daily(frame, interval)
        source_interval, source_table = "1d", "daily_prices"
    if not frame.empty:
        frame = frame.tail(max(1, min(limit, 20000)))
    bars: list[dict[str, int | float]] = []
    for timestamp, row in frame.iterrows():
        values = (row["open"], row["high"], row["low"], row["close"])
        if any(pd.isna(value) for value in values):
            continue
        bars.append(
            {
                "time": int(timestamp.to_pydatetime().astimezone(UTC).timestamp()),
                "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]),
                "volume": int(row["volume"] or 0),
            }
        )
    return ChartResult(symbol, interval, source_interval, source_table, session, bars)
