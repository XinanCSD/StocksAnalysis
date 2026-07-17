from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import INITIAL_SYMBOLS
from .symbols import normalize_symbol


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    input_symbol TEXT,
    yahoo_symbol TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_prices (
    symbol TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    timestamp_utc INTEGER NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adj_close REAL,
    volume INTEGER,
    dividends REAL NOT NULL DEFAULT 0,
    stock_splits REAL NOT NULL DEFAULT 0,
    capital_gains REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'yahoo',
    downloaded_at_utc TEXT NOT NULL,
    PRIMARY KEY (symbol, trading_date),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);

CREATE TABLE IF NOT EXISTS intraday_5m_prices (
    symbol TEXT NOT NULL,
    timestamp_utc INTEGER NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adj_close REAL,
    volume INTEGER,
    dividends REAL NOT NULL DEFAULT 0,
    stock_splits REAL NOT NULL DEFAULT 0,
    capital_gains REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'yahoo',
    downloaded_at_utc TEXT NOT NULL,
    PRIMARY KEY (symbol, timestamp_utc),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);

CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_prices(trading_date);
CREATE INDEX IF NOT EXISTS idx_5m_timestamp ON intraday_5m_prices(timestamp_utc);

CREATE TABLE IF NOT EXISTS download_state (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL CHECK (interval IN ('1d', '5m')),
    last_attempt_utc TEXT,
    last_success_utc TEXT,
    last_error TEXT,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    rows_received INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, interval),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);
"""


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_symbols(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at_utc) VALUES (2, ?)",
                (utc_now_text(),),
            )
            connection.executemany(
                """INSERT OR IGNORE INTO symbols(symbol, input_symbol, yahoo_symbol, enabled, created_at_utc)
                   VALUES (?, ?, ?, 1, ?)""",
                [(symbol, symbol, symbol, utc_now_text()) for symbol in INITIAL_SYMBOLS],
            )

    @staticmethod
    def _migrate_symbols(connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(symbols)")}
        if "input_symbol" not in columns:
            connection.execute("ALTER TABLE symbols ADD COLUMN input_symbol TEXT")
        if "yahoo_symbol" not in columns:
            connection.execute("ALTER TABLE symbols ADD COLUMN yahoo_symbol TEXT")
        connection.execute("UPDATE symbols SET input_symbol = COALESCE(input_symbol, symbol)")
        connection.execute("UPDATE symbols SET yahoo_symbol = COALESCE(yahoo_symbol, symbol)")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_symbols_yahoo ON symbols(yahoo_symbol)")

    def add_symbols(self, symbols: Iterable[str]) -> list[str]:
        normalized = [normalize_symbol(symbol) for symbol in symbols if symbol.strip()]
        by_yahoo = {yahoo: entered for entered, yahoo in normalized}
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO symbols(symbol, input_symbol, yahoo_symbol, enabled, created_at_utc)
                   VALUES (?, ?, ?, 1, ?)
                   ON CONFLICT(symbol) DO UPDATE SET enabled = 1,
                       input_symbol=excluded.input_symbol, yahoo_symbol=excluded.yahoo_symbol""",
                [(yahoo, entered, yahoo, utc_now_text()) for yahoo, entered in sorted(by_yahoo.items())],
            )
        return sorted(by_yahoo)

    def set_enabled(self, symbol: str, enabled: bool) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE symbols SET enabled = ? WHERE symbol = ?",
                (int(enabled), normalize_symbol(symbol)[1]),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown symbol: {symbol}")

    def list_symbols(self, enabled_only: bool = False) -> list[sqlite3.Row]:
        query = "SELECT symbol, input_symbol, yahoo_symbol, enabled, created_at_utc FROM symbols"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY symbol"
        with self.connect() as connection:
            return list(connection.execute(query))

    def latest_daily_date(self, symbol: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT MAX(trading_date) AS value FROM daily_prices WHERE symbol = ?", (symbol,)
            ).fetchone()
        return row["value"]

    def latest_intraday_timestamp(self, symbol: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT MAX(timestamp_utc) AS value FROM intraday_5m_prices WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        return row["value"]

    def upsert_daily(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        columns = (
            "symbol", "trading_date", "timestamp_utc", "open", "high", "low", "close",
            "adj_close", "volume", "dividends", "stock_splits", "capital_gains",
            "source", "downloaded_at_utc",
        )
        self._upsert("daily_prices", columns, ("symbol", "trading_date"), rows)
        return len(rows)

    def upsert_intraday(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        columns = (
            "symbol", "timestamp_utc", "open", "high", "low", "close", "adj_close",
            "volume", "dividends", "stock_splits", "capital_gains", "source",
            "downloaded_at_utc",
        )
        self._upsert("intraday_5m_prices", columns, ("symbol", "timestamp_utc"), rows)
        return len(rows)

    def _upsert(
        self,
        table: str,
        columns: Sequence[str],
        keys: Sequence[str],
        rows: Sequence[dict[str, Any]],
    ) -> None:
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column not in keys)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({', '.join(keys)}) DO UPDATE SET {updates}"
        )
        values = [tuple(row.get(column) for column in columns) for row in rows]
        with self.connect() as connection:
            connection.executemany(sql, values)

    def record_success(self, symbol: str, interval: str, rows_received: int) -> None:
        now = utc_now_text()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO download_state(
                       symbol, interval, last_attempt_utc, last_success_utc, last_error,
                       consecutive_errors, rows_received
                   ) VALUES (?, ?, ?, ?, NULL, 0, ?)
                   ON CONFLICT(symbol, interval) DO UPDATE SET
                       last_attempt_utc=excluded.last_attempt_utc,
                       last_success_utc=excluded.last_success_utc,
                       last_error=NULL, consecutive_errors=0,
                       rows_received=excluded.rows_received""",
                (symbol, interval, now, now, rows_received),
            )

    def record_failure(self, symbol: str, interval: str, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO download_state(
                       symbol, interval, last_attempt_utc, last_error, consecutive_errors
                   ) VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(symbol, interval) DO UPDATE SET
                       last_attempt_utc=excluded.last_attempt_utc,
                       last_error=excluded.last_error,
                       consecutive_errors=download_state.consecutive_errors + 1""",
                (symbol, interval, utc_now_text(), error[:2000]),
            )

    def status_rows(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = list(
                connection.execute(
                    """SELECT s.symbol, s.input_symbol, s.yahoo_symbol, s.enabled,
                              (SELECT COUNT(*) FROM daily_prices d WHERE d.symbol=s.symbol) daily_rows,
                              (SELECT COUNT(*) FROM intraday_5m_prices i WHERE i.symbol=s.symbol) intraday_rows,
                              MAX(CASE WHEN ds.interval='1d' THEN ds.last_success_utc END) daily_success,
                              MAX(CASE WHEN ds.interval='5m' THEN ds.last_success_utc END) intraday_success,
                              MAX(ds.last_error) last_error
                       FROM symbols s
                       LEFT JOIN download_state ds ON ds.symbol=s.symbol
                       GROUP BY s.symbol, s.input_symbol, s.yahoo_symbol, s.enabled ORDER BY s.symbol"""
                )
            )
        # Old databases may contain an alias such as BRK.B from before symbol
        # normalization existed. Hide that legacy duplicate while retaining its
        # historical rows on disk; the canonical BRK-B record is authoritative.
        return [row for row in rows if normalize_symbol(row["symbol"])[1] == row["symbol"]]

    def get_symbol(self, value: str) -> sqlite3.Row | None:
        yahoo = normalize_symbol(value)[1]
        with self.connect() as connection:
            return connection.execute(
                "SELECT symbol, input_symbol, yahoo_symbol, enabled, created_at_utc FROM symbols WHERE symbol=?",
                (yahoo,),
            ).fetchone()

    def has_extended_hours(self) -> bool:
        # A regular US session is 09:30 <= New York time < 16:00. SQLite has no
        # timezone database, so inspect the small set of available timestamps in Python.
        from datetime import UTC, datetime
        from zoneinfo import ZoneInfo

        ny = ZoneInfo("America/New_York")
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT timestamp_utc FROM intraday_5m_prices ORDER BY timestamp_utc DESC LIMIT 10000"
            )
            for row in rows:
                local = datetime.fromtimestamp(row["timestamp_utc"], UTC).astimezone(ny)
                if local.weekday() < 5 and not ((local.hour, local.minute) >= (9, 30) and (local.hour, local.minute) < (16, 0)):
                    return True
        return False

    def data_version(self, symbol: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COALESCE(MAX(downloaded_at_utc), '') AS value FROM (
                       SELECT downloaded_at_utc FROM daily_prices WHERE symbol=?
                       UNION ALL
                       SELECT downloaded_at_utc FROM intraday_5m_prices WHERE symbol=?
                   )""",
                (symbol, symbol),
            ).fetchone()
        return row["value"]

    def backup_to(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
