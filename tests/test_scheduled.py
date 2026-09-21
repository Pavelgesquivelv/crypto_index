import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_index.cli import main
from test_index import NOW, fixture


class ScheduledRunTests(unittest.TestCase):
    def test_monthly_report_is_created_and_preserved(self):
        cmc, binance, registry = fixture()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "assets.json"
            registry_path.write_text(
                json.dumps(registry), encoding="utf-8"
            )
            output = root / "runs"

            arguments = [
                "crypto-index",
                "--scheduled",
                "--registry", str(registry_path),
                "--output", str(output),
            ]

            responses = [
                json.dumps(cmc).encode("utf-8"),
                json.dumps(binance).encode("utf-8"),
            ]

            with (
                patch("sys.argv", arguments),
                patch("crypto_index.cli.utcnow", return_value=NOW),
                patch(
                    "crypto_index.cli.fetch",
                    side_effect=responses,
                ) as fetch,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                # Primera ejecución: genera la propuesta mensual.
                self.assertEqual(main(), 0)
                self.assertEqual(fetch.call_count, 2)

                monthly = output / "2026-09"
                report_path = monthly / "report.json"
                report = json.loads(
                    report_path.read_text(encoding="utf-8")
                )

                self.assertEqual(report["mode"], "scheduled")
                self.assertEqual(
                    report["status"], "composition_ready"
                )
                self.assertEqual(len(report["portfolio"]), 10)
                self.assertEqual(
                    sum(p["weight_pct"] for p in report["portfolio"]),
                    100,
                )
                self.assertTrue((monthly / "portfolio.csv").exists())
                self.assertFalse((output / "2026-09.lock").exists())

                before = {
                    p.name: p.read_bytes()
                    for p in monthly.iterdir()
                }

                # Segunda ejecución: conserva el resultado existente.
                self.assertEqual(main(), 0)
                self.assertEqual(fetch.call_count, 2)

                after = {
                    p.name: p.read_bytes()
                    for p in monthly.iterdir()
                }

                self.assertEqual(before, after)
                self.assertFalse((output / "2026-09.lock").exists())


if __name__ == "__main__":
    unittest.main()
