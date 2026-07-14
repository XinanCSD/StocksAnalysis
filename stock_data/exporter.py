from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .database import Database


def _export_query(database: Database, query: str, params: list[str], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    with database.connect() as connection, output.open("w", newline="", encoding="utf-8-sig") as handle:
        cursor = connection.execute(query, params)
        headers = [description[0] for description in cursor.description]
        writer = csv.writer(handle)
        writer.writerow(headers)
        count = 0
        for row in cursor:
            values = list(row)
            timestamp_index = headers.index("timestamp_utc") if "timestamp_utc" in headers else None
            if timestamp_index is not None:
                values[timestamp_index] = datetime.fromtimestamp(
                    values[timestamp_index], UTC
                ).isoformat()
            writer.writerow(values)
            count += 1
    return count


def export_csv(
    database: Database,
    interval: str,
    output: Path,
    symbols: Iterable[str] = (),
) -> int:
    selected = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    where = ""
    params: list[str] = []
    if selected:
        where = f" WHERE symbol IN ({', '.join('?' for _ in selected)})"
        params.extend(selected)

    if interval == "1d":
        query = (
            "SELECT symbol, trading_date, timestamp_utc, open, high, low, close, adj_close, "
            "volume, dividends, stock_splits, capital_gains, source, downloaded_at_utc "
            f"FROM daily_prices{where} ORDER BY symbol, trading_date"
        )
    elif interval == "5m":
        query = (
            "SELECT symbol, timestamp_utc, open, high, low, close, adj_close, volume, "
            "dividends, stock_splits, capital_gains, source, downloaded_at_utc "
            f"FROM intraday_5m_prices{where} ORDER BY symbol, timestamp_utc"
        )
    else:
        raise ValueError(f"Unsupported interval: {interval}")
    return _export_query(database, query, params, output)

