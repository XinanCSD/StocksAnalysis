from __future__ import annotations

import unittest


class DependencyTest(unittest.TestCase):
    def test_price_repair_dependency_is_installed(self) -> None:
        import scipy

        self.assertTrue(scipy.__version__)


if __name__ == "__main__":
    unittest.main()
