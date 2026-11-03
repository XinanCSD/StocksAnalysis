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
    up_le_1: int
    up_1_to_2: int
    up_gt_2: int
    down_le_1: int
    down_1_to_2: int
    down_gt_2: int

    @property
    def comparable_days(self) -> int:
        return self.up_days + self.down_days + self.unchanged_days

    @property
    def up_ratio(self) -> float:
        return self.up_days / self.comparable_days if self.comparable_days else 0.0

    @property
    def down_ratio(self) -> float:
        return self.down_days / self.comparable_days if self.comparable_days else 0.0

    def ratio(self, category: str) -> float:
        return getattr(self, category) / self.comparable_days if self.comparable_days else 0.0


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
            categories = (
                "up", "down", "unchanged", "up_le_1", "up_1_to_2", "up_gt_2",
                "down_le_1", "down_1_to_2", "down_gt_2",
            )
            counts = {day: dict.fromkeys(categories, 0) for day, _ in WEEKDAYS}
            previous: float | None = None
            for row in rows:
                close = float(row["close"])
                # ISO YYYY-MM-DD is lexically ordered and parseable without
                # depending on the host locale or database timezone.
                from datetime import date

                weekday_number = date.fromisoformat(row["trading_date"]).weekday()
                if weekday_number in counts and previous is not None:
                    change_pct = (close - previous) / previous * 100 if previous else 0.0
                    current = counts[weekday_number]
                    if change_pct > 0:
                        current["up"] += 1
                        current["up_le_1" if change_pct <= 1 else "up_1_to_2" if change_pct <= 2 else "up_gt_2"] += 1
                    elif change_pct < 0:
                        current["down"] += 1
                        magnitude = abs(change_pct)
                        current["down_le_1" if magnitude <= 1 else "down_1_to_2" if magnitude <= 2 else "down_gt_2"] += 1
                    else:
                        current["unchanged"] += 1
                previous = close
            results.append(
                SymbolAnalysis(
                    symbol=symbol,
                    total_days=max(0, len(rows) - 1),
                    weekdays=tuple(
                        WeekdayStats(
                            name, counts[number]["up"], counts[number]["down"], counts[number]["unchanged"],
                            counts[number]["up_le_1"], counts[number]["up_1_to_2"], counts[number]["up_gt_2"],
                            counts[number]["down_le_1"], counts[number]["down_1_to_2"], counts[number]["down_gt_2"],
                        )
                        for number, name in WEEKDAYS
                    ),
                )
            )
    return results
