import copy
from datetime import datetime, timezone
import unittest
from crypto_index.cli import build, due

NOW = datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)


def fixture():
    coins = [{'id': i, 'symbol': f'C{i}', 'cmc_rank': i, 'tags': [],
              'last_updated': NOW.isoformat(), 'quote': [{'symbol': 'USD', 'market_cap': 1000-i}]}
             for i in range(1, 21)]
    registry = {str(i): {'symbol': f'C{i}', 'binance_base': f'C{i}', 'classification': 'eligible'}
                for i in range(1, 21)}
    symbols = [{'symbol': f'C{i}USDT', 'baseAsset': f'C{i}', 'quoteAsset': 'USDT',
                'status': 'TRADING', 'isSpotTradingAllowed': True} for i in range(1, 21)]
    return {'data': coins}, {'symbols': symbols}, registry


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.c, self.b, self.r = fixture()

    def run_build(self):
        return build(self.c, self.b, self.r, NOW)

    def test_exclusions_precede_top15(self):
        for i, tag in enumerate(['stablecoin', 'memes', 'wrapped-tokens']):
            self.c['data'][i]['tags'] = [tag]
        result = self.run_build()
        self.assertEqual([r['cmc_id'] for r in result['universe']], list(range(4, 19)))
        self.assertEqual(len(result['portfolio']), 10)

    def test_skip_multiple_unavailable(self):
        for i in [0, 2, 8]:
            self.b['symbols'][i]['status'] = 'BREAK'
        result = self.run_build()
        self.assertEqual([r['cmc_id'] for r in result['portfolio']], [2, 4, 5, 6, 7, 8, 10, 11, 12, 13])

    def test_cash_and_universe_boundary(self):
        for s in self.b['symbols'][:8]:
            s['status'] = 'BREAK'
        result = self.run_build()
        self.assertEqual(result['cash_weight_pct'], 30)
        self.assertEqual(result['portfolio'][-1]['asset'], 'USDT')
        self.assertEqual(sum(p['weight_pct'] for p in result['portfolio']), 100)

    def test_unknown_asset_requires_review(self):
        del self.r['2']
        result = self.run_build()
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['portfolio'], [])

    def test_symbol_change_requires_review(self):
        self.c['data'][0]['symbol'] = 'DIFFERENT'
        self.assertEqual(self.run_build()['status'], 'review_required')

    def test_direct_route_not_inferred(self):
        self.b['symbols'][0]['quoteAsset'] = 'BTC'
        self.assertEqual(self.run_build()['status'], 'route_review_required')

    def test_spot_false_not_available(self):
        self.b['symbols'][0]['isSpotTradingAllowed'] = False
        self.assertEqual(self.run_build()['portfolio'][0]['cmc_id'], 2)

    def test_duplicate_mapping_rejected(self):
        self.r['2']['binance_base'] = 'C1'
        with self.assertRaises(ValueError): self.run_build()

    def test_stale_fails(self):
        self.c['data'][0]['last_updated'] = '2026-09-29T13:00:00Z'
        with self.assertRaises(ValueError): self.run_build()

    def test_incomplete_universe_fails(self):
        self.c['data'] = self.c['data'][:14]
        with self.assertRaises(ValueError): self.run_build()

    def test_missing_rank_fails(self):
        del self.c['data'][0]
        with self.assertRaises(ValueError): self.run_build()

    def test_missing_tags_fails(self):
        del self.c['data'][0]['tags']
        with self.assertRaises(ValueError): self.run_build()

    def test_bad_market_cap_fails(self):
        self.c['data'][0]['quote'][0]['market_cap'] = float('nan')
        with self.assertRaises(ValueError): self.run_build()

    def test_api_error_fails(self):
        self.c['status'] = {'error_code': 1001}
        with self.assertRaises(ValueError): self.run_build()

    def test_string_success_code(self):
        self.c['status'] = {'error_code': '0'}
        self.assertEqual(self.run_build()['status'], 'composition_ready')


class CalendarTests(unittest.TestCase):
    def test_month_lengths_and_leap_year(self):
        for y, m, d in [(2026, 9, 30), (2026, 12, 31), (2026, 2, 28), (2028, 2, 29)]:
            self.assertTrue(due(datetime(y, m, d, 13, 0, tzinfo=timezone.utc)))
            self.assertFalse(due(datetime(y, m, d-1, 13, 0, tzinfo=timezone.utc)))

    def test_window(self):
        self.assertFalse(due(NOW.replace(hour=12, minute=59)))
        self.assertTrue(due(NOW.replace(minute=14)))
        self.assertFalse(due(NOW.replace(minute=15)))


if __name__ == '__main__':
    unittest.main()
