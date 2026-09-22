import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/update_daily.py"
spec = importlib.util.spec_from_file_location("daily_update", SCRIPT)
daily_update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily_update)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = cls(2026, 9, 22, 13, 2, tzinfo=timezone.utc)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


class DailyUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "observations").mkdir()

        history = (
            "date,value_usdt,index_level\n"
            "2026-09-21,100,100\n"
        ).encode()

        portfolio = json.dumps({
            "cutoff_utc": "2026-08-31T13:00:00+00:00",
            "initial_value_usdt": "100",
            "base_level": "100",
            "cash_usdt": "90",
            "positions": [
                {"asset": "BTC", "pair": "BTCUSDT", "quantity": "0.1"}
            ],
        }).encode()

        manifest = {
            "history_file": "history_seed.csv",
            "portfolio_file": "portfolio_seed.json",
            "sha256": {
                "history_seed.csv": hashlib.sha256(history).hexdigest(),
                "portfolio_seed.json": hashlib.sha256(portfolio).hexdigest(),
            },
        }

        (self.root / "history_seed.csv").write_bytes(history)
        (self.root / "portfolio_seed.json").write_bytes(portfolio)
        (self.root / "manifest.json").write_text(json.dumps(manifest))

        stamp = int(
            datetime(2026, 9, 22, 13, tzinfo=timezone.utc).timestamp()
            * 1000
        )
        self.response = json.dumps([
            [stamp, "110", "111", "109", "110", "2", stamp, "220", 3]
        ]).encode()

    def execute(self):
        with (
            patch.object(daily_update, "ROOT", self.root),
            patch.object(daily_update, "datetime", FrozenDateTime),
            redirect_stdout(io.StringIO()),
        ):
            daily_update.main()

    def snapshot(self):
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }

    def test_new_day_then_repeat_without_download(self):
        with patch.object(
            daily_update, "download_bytes", return_value=self.response
        ) as download:
            self.execute()
            self.assertEqual(download.call_count, 1)
            self.assertIn(
                "symbol=BTCUSDT", download.call_args.args[0]
            )

        path = self.root / "observations/2026-09-22.json"
        record = json.loads(path.read_text(encoding="utf-8"))

        from decimal import Decimal
        self.assertEqual(Decimal(record["value_usdt"]), Decimal("101"))
        self.assertEqual(Decimal(record["index_level"]), Decimal("101"))
        self.assertEqual(Decimal(record["daily_return_pct"]), Decimal("1"))
        self.assertFalse(record["rebalance_applied"])

        before = self.snapshot()
        with patch.object(daily_update, "download_bytes") as download:
            self.execute()
            download.assert_not_called()

        self.assertEqual(before, self.snapshot())

    def test_missing_candle_does_not_write_observation(self):
        before = self.snapshot()

        with patch.object(
            daily_update, "download_bytes", return_value=b"[]"
        ):
            with self.assertRaisesRegex(ValueError, "Falta vela"):
                self.execute()

        self.assertEqual(before, self.snapshot())

    def test_modified_seed_is_rejected_before_download(self):
        (self.root / "history_seed.csv").write_text("modified")

        with patch.object(daily_update, "download_bytes") as download:
            with self.assertRaisesRegex(
                ValueError, "Archivo inicial modificado"
            ):
                self.execute()
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
