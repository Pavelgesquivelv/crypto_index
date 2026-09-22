import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_daily.py"
SPEC = importlib.util.spec_from_file_location("daily_rollover_target", SCRIPT)
daily = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daily)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 1, 13, 2, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class DailyRolloverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "observations").mkdir()
        (self.root / "portfolios").mkdir()

        # September portfolio: BTC worth 10 plus 90 in cash.
        portfolio = {
            "cutoff_utc": "2026-08-31T13:00:00+00:00",
            "initial_value_usdt": "100",
            "base_level": "100",
            "cash_usdt": "90",
            "positions": [
                {"asset": "BTC", "pair": "BTCUSDT", "quantity": "0.1"}
            ],
        }
        history = (
            "date,value_usdt,index_level\n"
            "2026-09-29,100,100\n"
        ).encode("utf-8")
        portfolio_raw = json.dumps(portfolio).encode("utf-8")

        (self.root / "history_seed.csv").write_bytes(history)
        (self.root / "portfolio_seed.json").write_bytes(portfolio_raw)
        self.seed_hash = hashlib.sha256(portfolio_raw).hexdigest()

        manifest = {
            "history_file": "history_seed.csv",
            "portfolio_file": "portfolio_seed.json",
            "sha256": {
                "history_seed.csv": hashlib.sha256(history).hexdigest(),
                "portfolio_seed.json": self.seed_hash,
            },
        }
        (self.root / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        # At September close BTC=110, so NAV=101.
        # New portfolio: 10.1 in ETH and 90.9 in cash.
        self.successor = {
            "cutoff_utc": "2026-09-30T13:00:00+00:00",
            "initial_value_usdt": "100",
            "base_level": "100",
            "cash_usdt": "90.9",
            "value_before_usdt": "101",
            "value_after_usdt": "101",
            "index_level": "101",
            "positions": [
                {
                    "asset": "ETH",
                    "pair": "ETHUSDT",
                    "quantity": "2.02",
                    "rebalance_price_usdt": "5",
                }
            ],
        }
        self.successor_path = (
            self.root / "portfolios" / "portfolio_2026-09-30.json"
        )

    def save_successor(self):
        raw = json.dumps(self.successor).encode("utf-8")
        self.successor_path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def fetch(self, url):
        query = parse_qs(urlparse(url).query)
        pair = query["symbol"][0]
        start = int(query["startTime"][0])
        day = datetime.fromtimestamp(
            start / 1000, timezone.utc
        ).date().isoformat()

        expected = {
            ("BTCUSDT", "2026-09-30"): "110",
            ("ETHUSDT", "2026-10-01"): "6",
        }
        self.assertIn((pair, day), expected)
        price = expected[(pair, day)]

        candle = [
            start, price, price, price, price,
            "10", start + 59_999, "100", 3, "5", "50", "0",
        ]
        return json.dumps([candle]).encode("utf-8")

    def execute(self):
        with (
            patch.object(daily, "ROOT", self.root),
            patch.object(daily, "datetime", FrozenDateTime),
            patch.object(daily, "download_bytes", side_effect=self.fetch) as fetch,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            daily.main()
            return fetch.call_count

    def observation(self, day):
        path = self.root / "observations" / f"{day}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def test_month_end_uses_old_holdings_and_next_day_uses_new(self):
        successor_hash = self.save_successor()

        self.assertEqual(self.execute(), 2)

        closing = self.observation("2026-09-30")
        following = self.observation("2026-10-01")

        self.assertEqual(closing["portfolio_sha256"], self.seed_hash)
        self.assertEqual(set(closing["prices_usdt"]), {"BTC"})
        self.assertEqual(Decimal(closing["value_usdt"]), Decimal("101"))

        self.assertEqual(following["portfolio_sha256"], successor_hash)
        self.assertEqual(set(following["prices_usdt"]), {"ETH"})
        self.assertEqual(Decimal(following["value_usdt"]), Decimal("103.02"))
        self.assertEqual(Decimal(following["index_level"]), Decimal("103.02"))
        self.assertEqual(Decimal(following["daily_return_pct"]), Decimal("2"))

        before = self.snapshot()
        self.assertEqual(self.execute(), 0)
        self.assertEqual(self.snapshot(), before)

    def test_missing_successor_stops_and_can_resume(self):
        with self.assertRaises(FileNotFoundError):
            self.execute()

        closing_path = self.root / "observations" / "2026-09-30.json"
        closing_bytes = closing_path.read_bytes()
        self.assertFalse(
            (self.root / "observations" / "2026-10-01.json").exists()
        )

        self.save_successor()
        self.assertEqual(self.execute(), 1)
        self.assertEqual(closing_path.read_bytes(), closing_bytes)
        self.assertEqual(
            Decimal(self.observation("2026-10-01")["value_usdt"]),
            Decimal("103.02"),
        )

    def test_invalid_successor_blocks_next_day(self):
        self.successor["cash_usdt"] = "91"
        self.save_successor()

        with self.assertRaisesRegex(ValueError, "efectivo"):
            self.execute()

        self.assertTrue(
            (self.root / "observations" / "2026-09-30.json").exists()
        )
        self.assertFalse(
            (self.root / "observations" / "2026-10-01.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
