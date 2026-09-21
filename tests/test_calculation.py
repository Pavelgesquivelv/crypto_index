import unittest
from decimal import Decimal

from crypto_index.calculation import (
    index_level,
    portfolio_value,
    rebalance,
    return_pct,
)


class CalculationTests(unittest.TestCase):
    def test_value_includes_cash(self):
        value = portfolio_value(
            {"BTC": "0.001", "ETH": "0.01"},
            {"BTC": "100000", "ETH": "4000"},
            cash="10",
        )
        self.assertEqual(value, Decimal("150"))

    def test_valuation_preserves_quantities(self):
        quantities = {"BTC": "0.001"}
        original = quantities.copy()

        first = portfolio_value(quantities, {"BTC": "100000"})
        second = portfolio_value(quantities, {"BTC": "110000"})

        self.assertEqual(first, Decimal("100"))
        self.assertEqual(second, Decimal("110"))
        self.assertEqual(quantities, original)

    def test_index_base_and_return(self):
        self.assertEqual(
            index_level("1100", initial_value="1000"),
            Decimal("110"),
        )
        self.assertEqual(return_pct("1100", "1000"), Decimal("10"))
        self.assertEqual(return_pct("900", "1000"), Decimal("-10"))

    def test_ten_assets_receive_ten_percent(self):
        assets = [f"C{i}" for i in range(10)]
        prices = {asset: str(i + 3) for i, asset in enumerate(assets)}

        result = rebalance("100", assets, prices)

        self.assertEqual(result["cash"], Decimal("0"))
        self.assertEqual(len(result["quantities"]), 10)

        for asset, quantity in result["quantities"].items():
            value = portfolio_value(
                {asset: quantity}, {asset: prices[asset]}
            )
            self.assertLess(abs(value - Decimal("10")), Decimal("1e-30"))

    def test_missing_slots_remain_cash(self):
        result = rebalance(
            "100", ["BTC", "ETH"], {"BTC": "100", "ETH": "20"}
        )

        self.assertEqual(result["quantities"]["BTC"], Decimal("0.1"))
        self.assertEqual(result["quantities"]["ETH"], Decimal("0.5"))
        self.assertEqual(result["cash"], Decimal("80"))
        self.assertEqual(result["value_after"], Decimal("100"))

    def test_empty_selection_is_all_cash(self):
        result = rebalance("100", [], {})
        self.assertEqual(result["quantities"], {})
        self.assertEqual(result["cash"], Decimal("100"))

    def test_rebalance_preserves_accumulated_index_level(self):
        value = Decimal("86.77310843180926481204652777")
        assets = [f"C{i}" for i in range(10)]
        prices = {asset: str(i + 3) for i, asset in enumerate(assets)}

        result = rebalance(value, assets, prices)

        self.assertLess(
            abs(index_level(result["value_after"]) - index_level(value)),
            Decimal("1e-25"),
        )

    def test_removed_asset_is_not_retained(self):
        old_value = portfolio_value({"OLD": "2"}, {"OLD": "50"})
        result = rebalance(old_value, ["NEW"], {"NEW": "5"})

        self.assertNotIn("OLD", result["quantities"])
        self.assertEqual(result["quantities"]["NEW"], Decimal("2"))
        self.assertEqual(result["cash"], Decimal("90"))

    def test_missing_price_is_rejected(self):
        with self.assertRaises(ValueError):
            portfolio_value({"BTC": "1"}, {})
        with self.assertRaises(ValueError):
            rebalance("100", ["BTC"], {})

    def test_invalid_prices_are_rejected(self):
        for price in ["0", "-1", "NaN", "Infinity"]:
            with self.subTest(price=price):
                with self.assertRaises(ValueError):
                    portfolio_value({"BTC": "1"}, {"BTC": price})
                with self.assertRaises(ValueError):
                    rebalance("100", ["BTC"], {"BTC": price})

    def test_invalid_holdings_are_rejected(self):
        with self.assertRaises(ValueError):
            portfolio_value({"BTC": "-1"}, {"BTC": "100"})
        with self.assertRaises(ValueError):
            portfolio_value({}, {}, cash="-1")

    def test_invalid_selections_are_rejected(self):
        for assets in [
            ["BTC", "BTC"],
            ["USDT"],
            [f"C{i}" for i in range(11)],
        ]:
            with self.subTest(assets=assets):
                with self.assertRaises(ValueError):
                    rebalance("100", assets, {})

    def test_invalid_index_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            index_level("100", initial_value="0")
        with self.assertRaises(ValueError):
            index_level("-1")
        with self.assertRaises(ValueError):
            return_pct("100", "0")


if __name__ == "__main__":
    unittest.main()
