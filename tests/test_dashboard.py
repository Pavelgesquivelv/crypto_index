import json
import unittest
from decimal import Decimal

import test_rebalance_daily as fixtures
from crypto_index.dashboard import public_data, render


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RebalanceDailyTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.root = self.fixture.root
        history = ('date,value_usdt,index_level,daily_return_pct,cumulative_return_pct\n'
                   '2026-09-28,100,100,,0\n2026-09-29,100,100,0,0\n').encode()
        (self.root / 'history_seed.csv').write_bytes(history)
        manifest = {'history_file': 'history_seed.csv', 'portfolio_file': 'portfolio_seed.json',
                    'sha256': {'history_seed.csv': fixtures.module.digest(history),
                               'portfolio_seed.json': fixtures.module.digest(self.fixture.prior.read_bytes())}}
        (self.root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        closing = json.loads(self.fixture.closing_path.read_bytes())
        closing.update(daily_return_pct='1', cumulative_return_pct='1',
                       sources={'secret': 'PRIVATE_SENTINEL'}, error='PRIVATE_SENTINEL')
        self.fixture.closing_path.write_text(json.dumps(closing), encoding='utf-8')

    def test_allowlist_metrics_and_observed_weights(self):
        data = public_data(self.root)
        self.assertEqual(data['last_date'], '2026-09-30')
        self.assertAlmostEqual(data['metrics']['total'], 1)
        self.assertAlmostEqual(sum(p['weight'] for p in data['measured_weights']), 100)
        page = render(data)
        self.assertNotIn('PRIVATE_SENTINEL', page)
        self.assertNotIn(str(self.root), page)
        self.assertNotIn('portfolio_sha256', page)
        self.assertNotIn('__PUBLIC_DATA__', page)

    def test_published_target_is_distinct_from_closing_holdings(self):
        self.fixture.run_script()
        data = public_data(self.root)
        self.assertEqual(data['target_date'], '2026-09-30')
        self.assertEqual(data['composition'][0]['asset'], 'ETH')
        self.assertEqual(data['measured_weights'][0]['asset'], 'BTC')

    def test_next_day_replays_generated_portfolio(self):
        path = self.fixture.run_script()
        row = {'date': '2026-10-01', 'portfolio_sha256': fixtures.module.digest(path.read_bytes()),
               'prices_usdt': {'ETH': '6'}, 'value_usdt': '103.02', 'index_level': '103.02',
               'daily_return_pct': '2', 'cumulative_return_pct': '3.02'}
        (self.root / 'observations/2026-10-01.json').write_text(json.dumps(row))
        data = public_data(self.root)
        self.assertEqual(Decimal(str(data['metrics']['level'])), Decimal('103.02'))
        self.assertEqual(data['measured_weights'][0]['asset'], 'ETH')
        self.assertFalse(data['months'][-1]['complete'])

    def test_seed_only_does_not_invent_current_weights(self):
        self.fixture.closing_path.unlink()
        self.assertIsNone(public_data(self.root)['measured_weights'])

    def test_corrupt_seed_is_rejected(self):
        with (self.root / 'history_seed.csv').open('ab') as stream:
            stream.write(b' ')
        with self.assertRaisesRegex(ValueError, 'modificada'):
            public_data(self.root)

    def test_inconsistent_observation_is_rejected(self):
        row = json.loads(self.fixture.closing_path.read_bytes())
        row['value_usdt'] = '900'
        self.fixture.closing_path.write_text(json.dumps(row))
        with self.assertRaises(ValueError):
            public_data(self.root)

    def test_embedded_json_cannot_close_script(self):
        data = public_data(self.root)
        data['monthly_status'] = '</script><script>alert(1)</script>'
        self.assertNotIn('</script><script>alert', render(data))

    def test_monthly_errors_are_not_public(self):
        directory = self.root / 'monthly'
        directory.mkdir()
        (directory / 'failure.json').write_text(json.dumps({
            'cutoff': '2026-09-30', 'recorded_utc': '2026-09-30T13:04:00Z',
            'status': 'action_required', 'message': 'PRIVATE_SENTINEL'}))
        data = public_data(self.root, directory)
        self.assertEqual(data['monthly_status'], 'Revisión mensual pendiente')
        self.assertNotIn('PRIVATE_SENTINEL', render(data))


if __name__ == '__main__':
    unittest.main()
