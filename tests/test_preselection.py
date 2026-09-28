import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from crypto_index import cli
from crypto_index.schedule import month_end, selection_day, selection_due
from test_index import fixture


class PreselectionTests(unittest.TestCase):
    def test_previous_weekday_including_weekends_and_leap_year(self):
        cases = [('2026-09-30', '2026-09-29'), ('2026-10-31', '2026-10-30'),
                 ('2026-05-31', '2026-05-29'), ('2026-08-31', '2026-08-28'),
                 ('2024-02-29', '2024-02-28'), ('2026-12-31', '2026-12-30')]
        for end, expected in cases:
            with self.subTest(end=end):
                self.assertEqual(selection_day(date.fromisoformat(end)).isoformat(), expected)

    def test_no_holiday_adjustment(self):
        self.assertEqual(selection_day(date(2026, 4, 30)), date(2026, 4, 29))
        self.assertEqual(month_end(date(2026, 2, 1)), date(2026, 2, 28))

    def test_window_and_no_capture_on_rebalance_day(self):
        self.assertTrue(selection_due(datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)))
        self.assertFalse(selection_due(datetime(2026, 9, 29, 13, 15, tzinfo=timezone.utc)))
        self.assertFalse(selection_due(datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)))

    def test_cli_preserves_sample_after_capture(self):
        cmc, exchange, registry = fixture()
        now = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)
        for coin in cmc['data']:
            coin['last_updated'] = now.isoformat()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reg = root / 'registry.json'
            reg.write_text(json.dumps(registry))
            args = ['index', '--scheduled', '--preselect', '--output', str(root / 'snapshots'),
                    '--registry', str(reg)]
            with (patch('sys.argv', args), patch.object(cli, 'utcnow', return_value=now),
                  patch.object(cli, 'fetch', side_effect=[json.dumps(cmc).encode(),
                                                        json.dumps(exchange).encode()]) as fetch,
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(cli.main(), 0)
                path = root / 'snapshots/2026-09/report.json'
                before = path.read_bytes()
                report = json.loads(before)
                self.assertEqual(report['selection_date'], '2026-09-29')
                self.assertEqual(report['rebalance_date'], '2026-09-30')
                self.assertEqual(cli.main(), 0)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(fetch.call_count, 2)


if __name__ == '__main__':
    unittest.main()
