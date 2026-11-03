from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .database import Database
from .symbols import normalize_symbol


WEEKDAYS = ((0, "周一"), (1, "周二"), (2, "周三"), (3, "周四"), (4, "周五"))


@dataclass(frozen=True)
class WeekdayStats:
    weekday: str
    up_days: int
    down_days: int
    unchanged_days: int


@dataclass(frozen=True)
class SymbolAnalysis:
    symbol: str
    total_days: int
    weekdays: tuple[WeekdayStats, ...]


def analyze_daily_moves(database: Database, symbols: list[str]) -> list[SymbolAnalysis]:
    """Compare each close with the previous available trading day's close."""
    normalized = sorted({normalize_symbol(value)[1] for value in symbols})
    results: list[SymbolAnalysis] = []
    with database.connect() as connection:
        for symbol in normalized:
            rows = connection.execute(
                """SELECT trading_date, close
                   FROM daily_prices
                   WHERE symbol = ? AND close IS NOT NULL
                   ORDER BY trading_date""",
                (symbol,),
            ).fetchall()
            counts = {day: {"up": 0, "down": 0, "unchanged": 0} for day, _ in WEEKDAYS}
            previous: float | None = None
            for row in rows:
                close = float(row["close"])
                # ISO YYYY-MM-DD is lexically ordered and parseable without
                # depending on the host locale or database timezone.
                from datetime import date

                weekday_number = date.fromisoformat(row["trading_date"]).weekday()
                if weekday_number in counts and previous is not None:
                    direction = "up" if close > previous else "down" if close < previous else "unchanged"
                    counts[weekday_number][direction] += 1
                previous = close
            results.append(
                SymbolAnalysis(
                    symbol=symbol,
                    total_days=max(0, len(rows) - 1),
                    weekdays=tuple(
                        WeekdayStats(name, counts[number]["up"], counts[number]["down"], counts[number]["unchanged"])
                        for number, name in WEEKDAYS
                    ),
                )
            )
    return results
