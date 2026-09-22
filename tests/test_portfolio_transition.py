import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from crypto_index.portfolio_transition import load_next_portfolio


class PortfolioTransitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "portfolio_2026-09-30.json"

        self.current = {
            "cutoff_utc": "2026-08-31T13:00:00+00:00",
            "initial_value_usdt": "100",
            "base_level": "100",
            "cash_usdt": "0",
            "positions": [
                {"asset": "BTC", "pair": "BTCUSDT", "quantity": "1"}
            ],
        }
        self.current_hash = "seed-hash"
        self.closing = {
            "date": "2026-09-30",
            "portfolio_sha256": self.current_hash,
            "prices_usdt": {"BTC": "100"},
            "value_usdt": "100",
            "index_level": "100",
        }
        self.successor = {
            "cutoff_utc": "2026-09-30T13:00:00+00:00",
            "initial_value_usdt": "100",
            "base_level": "100",
            "cash_usdt": "90",
            "value_before_usdt": "100",
            "value_after_usdt": "100",
            "index_level": "100",
            "positions": [
                {
                    "asset": "ETH",
                    "pair": "ETHUSDT",
                    "quantity": "2",
                    "rebalance_price_usdt": "5",
                }
            ],
        }

    def save(self):
        raw = json.dumps(self.successor).encode("utf-8")
        self.path.write_bytes(raw)
        return raw

    def transition(self):
        return load_next_portfolio(
            self.directory,
            self.current,
            self.current_hash,
            self.closing,
        )

    def test_valid_transition_preserves_inputs_and_file(self):
        original_current = deepcopy(self.current)
        original_closing = deepcopy(self.closing)
        raw = self.save()

        portfolio, digest = self.transition()

        self.assertEqual(portfolio, self.successor)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.current, original_current)
        self.assertEqual(self.closing, original_closing)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_missing_successor_stops(self):
        with self.assertRaises(FileNotFoundError):
            self.transition()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_wrong_closing_portfolio_is_rejected(self):
        self.save()
        self.closing["portfolio_sha256"] = "another-portfolio"
        with self.assertRaisesRegex(ValueError, "otra cartera"):
            self.transition()

    def test_skipped_month_is_rejected(self):
        self.save()
        self.closing["date"] = "2026-10-31"
        with self.assertRaisesRegex(ValueError, "mes siguiente"):
            self.transition()

    def test_wrong_cutoff_hour_is_rejected(self):
        self.successor["cutoff_utc"] = "2026-09-30T14:00:00+00:00"
        self.save()
        with self.assertRaisesRegex(ValueError, "07:00"):
            self.transition()

    def test_changed_base_is_rejected(self):
        self.successor["base_level"] = "200"
        self.save()
        with self.assertRaisesRegex(ValueError, "base_level"):
            self.transition()

    def test_redistributed_missing_slots_are_rejected(self):
        # Full investment in one asset preserves NAV but violates 10% per slot.
        self.successor["positions"][0]["quantity"] = "20"
        self.successor["cash_usdt"] = "0"
        self.save()
        with self.assertRaisesRegex(ValueError, "asignación"):
            self.transition()

    def test_wrong_cash_is_rejected(self):
        self.successor["cash_usdt"] = "91"
        self.save()
        with self.assertRaisesRegex(ValueError, "efectivo"):
            self.transition()

    def test_shared_asset_price_must_match_closing(self):
        # NAV and 10% allocation are valid, but the BTC price contradicts
        # the outgoing portfolio's price at the same cutoff.
        self.successor["positions"] = [
            {
                "asset": "BTC",
                "pair": "BTCUSDT",
                "quantity": "0.05",
                "rebalance_price_usdt": "200",
            }
        ]
        self.save()
        with self.assertRaisesRegex(ValueError, "precio de BTC"):
            self.transition()

    def test_nonfinite_price_is_rejected(self):
        self.successor["positions"][0]["rebalance_price_usdt"] = "NaN"
        self.save()
        with self.assertRaisesRegex(ValueError, "finito"):
            self.transition()

    def test_incorrect_closing_value_is_rejected(self):
        self.closing["value_usdt"] = "101"
        self.save()
        with self.assertRaisesRegex(ValueError, "valor del cierre"):
            self.transition()

    def test_all_cash_successor_is_valid(self):
        self.successor["positions"] = []
        self.successor["cash_usdt"] = "100"
        self.save()

        portfolio, _ = self.transition()

        self.assertEqual(portfolio["positions"], [])
        self.assertEqual(portfolio["cash_usdt"], "100")


if __name__ == "__main__":
    unittest.main()
