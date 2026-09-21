import calendar
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from crypto_index.monthly_valuation import value_month


def price_series(year, month, price):
    return {
        date(year, month, day).isoformat(): Decimal(price)
        for day in range(
            1, calendar.monthrange(year, month)[1] + 1
        )
    }


class MonthlyValuationTests(unittest.TestCase):
    def run_month(self, **overrides):
        arguments = {
            "quantities": {"BTC": "1"},
            "pairs": {"BTC": "BTCUSDT"},
            "cash": "0",
            "archive_directory": "unused",
            "year": 2025,
            "month": 10,
            "previous_value": "100",
            "initial_value": "100",
            "base_level": "100",
        }
        arguments.update(overrides)
        return value_month(**arguments)

    def test_constant_prices_produce_zero_returns(self):
        with patch(
            "crypto_index.monthly_valuation.monthly_open_prices",
            return_value=price_series(2025, 10, "100"),
        ):
            rows = self.run_month()

        self.assertEqual(len(rows), 31)
        self.assertTrue(all(
            row["daily_return_pct"] == Decimal("0")
            for row in rows
        ))
        self.assertEqual(rows[-1]["index_level"], Decimal("100"))

    def test_daily_return_uses_previous_day(self):
        prices = price_series(2025, 10, "121")
        prices["2025-10-01"] = Decimal("110")

        with patch(
            "crypto_index.monthly_valuation.monthly_open_prices",
            return_value=prices,
        ):
            rows = self.run_month()

        self.assertEqual(rows[0]["daily_return_pct"], Decimal("10"))
        self.assertEqual(rows[1]["daily_return_pct"], Decimal("10"))
        self.assertEqual(rows[1]["cumulative_return_pct"], Decimal("21"))
        self.assertEqual(rows[2]["daily_return_pct"], Decimal("0"))

    def test_cash_is_included_without_redistribution(self):
        with patch(
            "crypto_index.monthly_valuation.monthly_open_prices",
            return_value=price_series(2025, 10, "110"),
        ):
            rows = self.run_month(
                quantities={"BTC": "0.1"},
                cash="90",
            )

        self.assertEqual(rows[0]["value_usdt"], Decimal("101"))
        self.assertEqual(rows[0]["daily_return_pct"], Decimal("1"))

    def test_all_cash_needs_no_price_download(self):
        with patch(
            "crypto_index.monthly_valuation.monthly_open_prices"
        ) as reader:
            rows = self.run_month(
                quantities={}, pairs={}, cash="100"
            )

        reader.assert_not_called()
        self.assertEqual(len(rows), 31)
        self.assertEqual(rows[-1]["value_usdt"], Decimal("100"))

    def test_holdings_are_not_mutated(self):
        quantities = {"BTC": "1"}
        original = quantities.copy()

        with patch(
            "crypto_index.monthly_valuation.monthly_open_prices",
            return_value=price_series(2025, 10, "120"),
        ):
            self.run_month(quantities=quantities)

        self.assertEqual(quantities, original)

    def test_leap_month_has_29_observations(self):
        with patch(
            "crypto_index.monthly_valuation.monthly_open_prices",
            return_value=price_series(2024, 2, "100"),
        ):
            rows = self.run_month(year=2024, month=2)

        self.assertEqual(len(rows), 29)
        self.assertEqual(rows[-1]["date"], "2024-02-29")

    def test_missing_pair_mapping_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_month(pairs={})

    def test_duplicate_pair_mapping_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_month(
                quantities={"BTC": "1", "OTHER": "1"},
                pairs={"BTC": "BTCUSDT", "OTHER": "BTCUSDT"},
            )

    def test_invalid_previous_value_is_rejected(self):
        for value in ["0", "-1", "NaN"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.run_month(previous_value=value)

    def test_archive_failure_is_not_replaced_with_zero(self):
        with patch(
            "crypto_index.monthly_valuation.monthly_open_prices",
            side_effect=ValueError("Missing daily cutoffs"),
        ):
            with self.assertRaisesRegex(
                ValueError, "Missing daily cutoffs"
            ):
                self.run_month()


if __name__ == "__main__":
    unittest.main()
