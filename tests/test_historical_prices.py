import calendar
import csv
import hashlib
import io
import tempfile
import unittest
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from crypto_index.historical_prices import monthly_open_prices


class HistoricalPricesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def rows(self, year=2025, month=10, microseconds=False):
        rows = []
        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            cutoff = datetime(
                year, month, day, 7,
                tzinfo=ZoneInfo("America/Mexico_City"),
            )
            stamp = int(cutoff.timestamp() * 1000)
            if microseconds:
                stamp *= 1000

            rows.append([
                stamp, "100.25", "101", "99", "100",
                "2", stamp, "200", "3",
            ])
        return rows

    def archive(self, rows, year=2025, month=10):
        path = self.root / f"BTCUSDT-1m-{year:04d}-{month:02d}.zip"

        text = io.StringIO()
        csv.writer(text).writerows(rows)

        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                path.stem + ".csv",
                text.getvalue().encode("utf-8"),
            )

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        Path(str(path) + ".CHECKSUM").write_text(
            f"{digest}  {path.name}\n",
            encoding="utf-8",
        )
        return path

    def test_millisecond_timestamps(self):
        path = self.archive(self.rows())
        prices = monthly_open_prices(path, 2025, 10)

        self.assertEqual(len(prices), 31)
        self.assertEqual(prices["2025-10-01"], Decimal("100.25"))
        self.assertEqual(prices["2025-10-31"], Decimal("100.25"))

    def test_microsecond_timestamps(self):
        path = self.archive(self.rows(microseconds=True))
        prices = monthly_open_prices(path, 2025, 10)
        self.assertEqual(len(prices), 31)

    def test_leap_year(self):
        path = self.archive(self.rows(2024, 2), 2024, 2)
        prices = monthly_open_prices(path, 2024, 2)
        self.assertEqual(len(prices), 29)
        self.assertIn("2024-02-29", prices)

    def test_modified_archive_is_rejected(self):
        path = self.archive(self.rows())
        with path.open("ab") as file:
            file.write(b"modified")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            monthly_open_prices(path, 2025, 10)

    def test_missing_cutoff_is_rejected(self):
        path = self.archive(self.rows()[1:])
        with self.assertRaisesRegex(ValueError, "Missing daily cutoffs"):
            monthly_open_prices(path, 2025, 10)

    def test_duplicate_cutoff_is_rejected(self):
        rows = self.rows()
        rows.append(rows[0].copy())
        path = self.archive(rows)
        with self.assertRaisesRegex(ValueError, "Duplicate cutoff"):
            monthly_open_prices(path, 2025, 10)

    def test_wrong_hour_is_not_used(self):
        rows = self.rows()
        rows[0][0] += 60_000
        path = self.archive(rows)
        with self.assertRaisesRegex(ValueError, "Missing daily cutoffs"):
            monthly_open_prices(path, 2025, 10)

    def test_non_traded_candle_is_rejected(self):
        rows = self.rows()
        rows[0][8] = "0"
        path = self.archive(rows)
        with self.assertRaisesRegex(ValueError, "Invalid cutoff candle"):
            monthly_open_prices(path, 2025, 10)

    def test_invalid_prices_are_rejected(self):
        for price in ["0", "-1", "NaN", "Infinity"]:
            with self.subTest(price=price):
                rows = self.rows()
                rows[0][1] = price
                path = self.archive(rows)
                with self.assertRaisesRegex(
                    ValueError, "Invalid cutoff candle"
                ):
                    monthly_open_prices(path, 2025, 10)

    def test_wrong_month_is_rejected(self):
        path = self.archive(self.rows())
        with self.assertRaisesRegex(ValueError, "filename"):
            monthly_open_prices(path, 2025, 11)


if __name__ == "__main__":
    unittest.main()
