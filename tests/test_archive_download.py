import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from crypto_index.archive_download import (
    download_bytes,
    ensure_monthly_archive,
)


class ArchiveDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.raw = b"synthetic archive bytes"
        self.checksum = (
            hashlib.sha256(self.raw).hexdigest()
            + "  BTCUSDT-1m-2025-11.zip\n"
        ).encode("utf-8")

    def ensure(self):
        return ensure_monthly_archive(
            "BTCUSDT", 2025, 11, self.directory
        )

    def test_download_saves_verified_files(self):
        with patch(
            "crypto_index.archive_download.download_bytes",
            side_effect=[self.checksum, self.raw],
        ) as download:
            path = self.ensure()

        self.assertEqual(download.call_count, 2)
        self.assertEqual(path.read_bytes(), self.raw)
        self.assertEqual(
            Path(str(path) + ".CHECKSUM").read_bytes(),
            self.checksum,
        )

    def test_valid_cache_avoids_network(self):
        with patch(
            "crypto_index.archive_download.download_bytes",
            side_effect=[self.checksum, self.raw],
        ):
            self.ensure()

        with patch(
            "crypto_index.archive_download.download_bytes"
        ) as download:
            self.ensure()

        download.assert_not_called()

    def test_bad_download_is_not_saved(self):
        with patch(
            "crypto_index.archive_download.download_bytes",
            side_effect=[self.checksum, b"wrong content"],
        ):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                self.ensure()

        self.assertEqual(list(self.directory.iterdir()), [])

    def test_corrupted_cache_is_preserved(self):
        with patch(
            "crypto_index.archive_download.download_bytes",
            side_effect=[self.checksum, self.raw],
        ):
            path = self.ensure()

        path.write_bytes(b"corrupted")

        with patch(
            "crypto_index.archive_download.download_bytes"
        ) as download:
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                self.ensure()

        download.assert_not_called()
        self.assertEqual(path.read_bytes(), b"corrupted")

    def test_incomplete_cache_is_rejected(self):
        path = self.directory / "BTCUSDT-1m-2025-11.zip"
        path.write_bytes(self.raw)

        with patch(
            "crypto_index.archive_download.download_bytes"
        ) as download:
            with self.assertRaisesRegex(ValueError, "Incomplete cache"):
                self.ensure()

        download.assert_not_called()

    def test_malformed_checksum_is_rejected(self):
        with patch(
            "crypto_index.archive_download.download_bytes",
            side_effect=[b"not-a-checksum", self.raw],
        ):
            with self.assertRaisesRegex(ValueError, "Malformed"):
                self.ensure()

        self.assertEqual(list(self.directory.iterdir()), [])

    def test_invalid_pair_is_rejected(self):
        with self.assertRaises(ValueError):
            ensure_monthly_archive(
                "../BTCUSDT", 2025, 11, self.directory
            )

    def test_http_404_remains_unresolved(self):
        error = HTTPError(
            "https://example.test/archive", 404, "Not Found", {}, None
        )

        with patch(
            "crypto_index.archive_download.urlopen",
            side_effect=error,
        ) as request:
            with self.assertRaisesRegex(
                FileNotFoundError, "unresolved"
            ):
                download_bytes("https://example.test/archive")

        self.assertEqual(request.call_count, 1)

    def test_transient_errors_have_bounded_retries(self):
        error = HTTPError(
            "https://example.test/archive",
            503,
            "Unavailable",
            {},
            None,
        )

        with (
            patch(
                "crypto_index.archive_download.urlopen",
                side_effect=error,
            ) as request,
            patch("crypto_index.archive_download.time.sleep") as sleep,
        ):
            with self.assertRaises(HTTPError):
                download_bytes("https://example.test/archive")

        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
