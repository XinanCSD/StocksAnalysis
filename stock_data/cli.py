from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from .config import make_settings
from .database import Database
from .exporter import export_csv
from .service import Collector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stock-data", description="Yahoo Finance SQLite collector")
    parser.add_argument("--data-dir", help="Data directory (default: ./data or STOCK_DATA_DIR)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create the database and seed initial symbols")
    subparsers.add_parser("update", help="Run one update for all enabled symbols")
    subparsers.add_parser("run", help="Update immediately, then every configured interval")
    subparsers.add_parser("status", help="Show symbols, row counts and last updates")

    symbols = subparsers.add_parser("symbols", help="Manage symbols")
    symbol_commands = symbols.add_subparsers(dest="symbol_command", required=True)
    add = symbol_commands.add_parser("add", help="Add or re-enable symbols")
    add.add_argument("symbols", nargs="+")
    disable = symbol_commands.add_parser("disable", help="Disable a symbol")
    disable.add_argument("symbol")
    enable = symbol_commands.add_parser("enable", help="Enable a symbol")
    enable.add_argument("symbol")
    symbol_commands.add_parser("list", help="List symbols")

    export = subparsers.add_parser("export", help="Export SQLite data to CSV")
    export.add_argument("--interval", choices=("1d", "5m", "all"), default="all")
    export.add_argument("--symbol", action="append", default=[], help="Filter; repeat as needed")
    export.add_argument("--output-dir", default="exports")

    backup = subparsers.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("output", help="Destination .sqlite file")
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _print_status(database: Database) -> None:
    print(f"{'SYMBOL':<10} {'ON':<3} {'DAILY':>8} {'5M':>10}  {'LAST DAILY':<25} {'LAST 5M':<25}")
    for row in database.status_rows():
        print(
            f"{row['symbol']:<10} {'Y' if row['enabled'] else 'N':<3} "
            f"{row['daily_rows']:>8} {row['intraday_rows']:>10}  "
            f"{(row['daily_success'] or '-'):25.25} {(row['intraday_success'] or '-'):25.25}"
        )
        if row["last_error"]:
            print(f"  error: {row['last_error']}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    settings = make_settings(args.data_dir)
    database = Database(settings.database_path)
    database.initialize()

    if args.command == "init":
        print(f"Initialized {database.path}")
        return 0
    if args.command == "update":
        return 0 if Collector(database, settings).update_all() else 1
    if args.command == "run":
        Collector(database, settings).run_forever()
        return 0
    if args.command == "status":
        _print_status(database)
        return 0
    if args.command == "symbols":
        if args.symbol_command == "add":
            print("Added/enabled: " + ", ".join(database.add_symbols(args.symbols)))
        elif args.symbol_command == "disable":
            database.set_enabled(args.symbol, False)
            print(f"Disabled: {args.symbol.upper()}")
        elif args.symbol_command == "enable":
            database.set_enabled(args.symbol, True)
            print(f"Enabled: {args.symbol.upper()}")
        else:
            for row in database.list_symbols():
                print(f"{row['symbol']}\t{'enabled' if row['enabled'] else 'disabled'}")
        return 0
    if args.command == "export":
        output_dir = Path(args.output_dir).expanduser().resolve()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        intervals = ("1d", "5m") if args.interval == "all" else (args.interval,)
        for interval in intervals:
            output = output_dir / f"market_{interval}_{stamp}.csv"
            count = export_csv(database, interval, output, args.symbol)
            print(f"Exported {count} rows: {output}")
        return 0
    if args.command == "backup":
        destination = Path(args.output).expanduser().resolve()
        database.backup_to(destination)
        print(f"Backup created: {destination}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

