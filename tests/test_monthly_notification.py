import io
import json
import unittest
from urllib.parse import parse_qs

import test_rebalance_daily as fixtures
from test_notify_index import notify


class MonthlyNotificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RebalanceDailyTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.root = self.fixture.root
        self.path = self.fixture.run_script()
        self.monthly = self.root / 'monthly'
        self.monthly.mkdir()
        manifest = {'portfolio_file': 'portfolio_seed.json', 'sha256': {
            'portfolio_seed.json': fixtures.module.digest(self.fixture.prior.read_bytes())}}
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        self.status = self.monthly / '2026-09-30-finalize-test.json'
        self.status.write_text(json.dumps({'status': 'portfolio_ready', 'cutoff': '2026-09-30'}))
        self.messages = []

    def opener(self, request, timeout):
        self.messages.append(parse_qs(request.data.decode()))
        return io.BytesIO(b'{"status":1}')

    def send(self, opener=None):
        return notify.send_monthly(self.root, self.monthly, '2026-09-30',
                                   {'PUSHOVER_TOKEN': 'fake', 'PUSHOVER_USER': 'fake'},
                                   opener or self.opener)

    def test_entries_exits_and_duplicate_suppression(self):
        before = self.path.read_bytes()
        self.assertEqual(self.send(), 'sent')
        self.assertIn('Entran: ETH.', self.messages[0]['message'][0])
        self.assertIn('Salen: BTC.', self.messages[0]['message'][0])
        self.assertEqual(self.send(), 'already_sent')
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_same_assets_message(self):
        report = json.loads(self.path.read_bytes())
        result = fixtures.module.rebalance('101', ['BTC'], {'BTC': '110'})
        report['positions'] = [{'asset': 'BTC', 'pair': 'BTCUSDT',
                                'quantity': str(result['quantities']['BTC']),
                                'rebalance_price_usdt': '110'}]
        self.path.write_text(json.dumps(report))
        self.send()
        text = self.messages[0]['message'][0]
        self.assertIn('Entran: Ninguna.', text)
        self.assertIn('Salen: Ninguna.', text)
        self.assertIn('pesos restablecidos', text)

    def test_failed_month_does_not_send(self):
        self.status.write_text(json.dumps({'status': 'action_required', 'cutoff': '2026-09-30'}))
        with self.assertRaisesRegex(ValueError, 'confirmado'):
            self.send()
        self.assertEqual(self.messages, [])

    def test_ambiguous_delivery_is_not_automatically_repeated(self):
        def timeout(*args, **kwargs):
            raise TimeoutError()
        with self.assertRaises(RuntimeError):
            self.send(timeout)
        with self.assertRaisesRegex(ValueError, 'incierto'):
            self.send()
        self.assertEqual(self.messages, [])
        self.assertFalse((self.monthly / 'notifications/2026-09-30.lock').exists())

    def test_invalid_portfolio_does_not_send(self):
        report = json.loads(self.path.read_bytes())
        report['cash_usdt'] = '999'
        self.path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            self.send()
        self.assertEqual(self.messages, [])


if __name__ == '__main__':
    unittest.main()
