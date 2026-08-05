from __future__ import annotations

import unittest
from decimal import Decimal

from olist_agents.utils import money, stable_unique, variance_hours


class UtilityTests(unittest.TestCase):
    def test_money_uses_half_up_rounding(self) -> None:
        self.assertEqual(money(Decimal("1.005")), 1.01)
        self.assertEqual(money(Decimal("-0.001")), 0.0)

    def test_variance_hours(self) -> None:
        self.assertEqual(
            variance_hours("2018-03-31 15:23:33", "2018-03-28 00:00:00"),
            87.39,
        )

    def test_stable_unique_preserves_source_order(self) -> None:
        self.assertEqual(stable_unique(["b", "a", "b", "c"]), ["b", "a", "c"])


if __name__ == "__main__":
    unittest.main()
