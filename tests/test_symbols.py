from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stock_data.database import Database
from stock_data.symbols import normalize_symbol


class SymbolTest(unittest.TestCase):
    def test_yahoo_normalization_preserves_exchange_suffixes(self) -> None:
        self.assertEqual(normalize_symbol(" BRK.B "), ("BRK.B", "BRK-B"))
        self.assertEqual(normalize_symbol("BRK-B"), ("BRK-B", "BRK-B"))
        self.assertEqual(normalize_symbol("7203.T"), ("7203.T", "7203.T"))

    def test_adding_class_share_twice_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "market.sqlite")
            database.initialize(); database.add_symbols(["BRK.B"]); database.add_symbols(["BRK-B"])
            matches = [row for row in database.list_symbols() if row["symbol"] == "BRK-B"]
            self.assertEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main()
