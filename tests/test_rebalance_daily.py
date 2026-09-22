import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'rebalance_daily.py'
SPEC = importlib.util.spec_from_file_location('rebalance_daily_test_target', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class RebalanceDailyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'observations').mkdir()
        self.selection = self.root / 'selection'
        self.selection.mkdir()
        self.prior = self.root / 'portfolio_seed.json'
        self.now = datetime(2026, 9, 30, 13, 2, tzinfo=timezone.utc)
        self.captured = '2026-09-30T13:00:20+00:00'
        prior = {'cutoff_utc': '2026-08-31T13:00:00+00:00',
                 'initial_value_usdt': '100', 'base_level': '100', 'cash_usdt': '90',
                 'positions': [{'asset': 'BTC', 'pair': 'BTCUSDT', 'quantity': '0.1'}]}
        self.prior.write_text(json.dumps(prior), encoding='utf-8')
        closing = {'date': '2026-09-30', 'cutoff_local': '2026-09-30T07:00:00-06:00',
                   'portfolio_sha256': module.digest(self.prior.read_bytes()),
                   'prices_usdt': {'BTC': '110'}, 'value_usdt': '101', 'index_level': '101'}
        self.closing_path = self.root / 'observations' / '2026-09-30.json'
        self.closing_path.write_text(json.dumps(closing), encoding='utf-8')
        self.cmc = {'status': {'error_code': 0}, 'data': []}
        self.registry = {}
        for index in range(1, 16):
            symbol = 'ETH' if index == 1 else f'COIN{index}'
            self.cmc['data'].append({'id': index, 'symbol': symbol, 'cmc_rank': index,
                                     'last_updated': self.captured, 'tags': [],
                                     'quote': {'USD': {'market_cap': 1000 / index}}})
            self.registry[str(index)] = {'classification': 'eligible', 'symbol': symbol,
                                         'binance_base': symbol}
        self.exchange = {'symbols': [{'baseAsset': 'ETH', 'quoteAsset': 'USDT',
                                     'symbol': 'ETHUSDT', 'status': 'TRADING',
                                     'isSpotTradingAllowed': True}]}
        self.save_selection()
        self.calls = []

    def save_selection(self):
        hashes = {}
        for name, data in [('cmc.json', self.cmc), ('binance.json', self.exchange),
                           ('registry.json', self.registry)]:
            raw = json.dumps(data).encode()
            (self.selection / name).write_bytes(raw)
            hashes[name] = module.digest(raw)
        report = module.build(self.cmc, self.exchange, self.registry,
                              module.timestamp(self.captured))
        report.update(mode='scheduled', generated_utc=self.captured,
                      cmc_received_utc=self.captured, binance_received_utc=self.captured,
                      sha256=hashes)
        (self.selection / 'report.json').write_text(json.dumps(report), encoding='utf-8')

    def fetch(self, url):
        query = parse_qs(urlparse(url).query)
        pair = query['symbol'][0]
        self.calls.append(pair)
        start = int(query['startTime'][0])
        price = {'BTCUSDT': '110', 'ETHUSDT': '5'}[pair]
        return json.dumps([[start, price, price, price, price, '5',
                            start + 59999, '100', 2]]).encode()

    def run_script(self, **kwargs):
        return module.run(self.root, self.prior, self.selection, '2026-09-30',
                          now=kwargs.get('now', self.now), fetch=kwargs.get('fetch', self.fetch))

    def assert_no_portfolio(self):
        self.assertFalse((self.root / 'portfolios' / 'portfolio_2026-09-30.json').exists())
        self.assertFalse((self.root / 'update.lock').exists())

    def test_success_and_no_overwrite(self):
        closing_raw = self.closing_path.read_bytes()
        destination = self.run_script()
        raw = destination.read_bytes()
        report = json.loads(raw)
        self.assertEqual(self.calls, ['BTCUSDT', 'ETHUSDT'])
        self.assertEqual(Decimal(report['cash_usdt']), Decimal('90.9'))
        self.assertEqual(Decimal(report['positions'][0]['quantity']), Decimal('2.02'))
        self.assertEqual(Decimal(report['index_level']), Decimal('101'))
        self.assertEqual(self.closing_path.read_bytes(), closing_raw)
        with self.assertRaises(FileExistsError):
            self.run_script()
        self.assertEqual(destination.read_bytes(), raw)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse((self.root / 'update.lock').exists())

    def test_all_cash_selection(self):
        self.exchange['symbols'] = []
        self.save_selection()
        report = json.loads(self.run_script().read_bytes())
        self.assertEqual(report['positions'], [])
        self.assertEqual(Decimal(report['cash_usdt']), Decimal('101'))

    def test_corrupted_source(self):
        (self.selection / 'cmc.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Fuente modificada'):
            self.run_script()
        self.assertEqual(self.calls, [])
        self.assert_no_portfolio()

    def test_modified_selection(self):
        path = self.selection / 'report.json'
        report = json.loads(path.read_bytes())
        report['portfolio'][0]['asset'] = 'BTC'
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'no reproducible'):
            self.run_script()
        self.assert_no_portfolio()

    def test_stale_selection(self):
        self.captured = '2026-09-29T13:00:20+00:00'
        for coin in self.cmc['data']:
            coin['last_updated'] = self.captured
        self.save_selection()
        with self.assertRaisesRegex(ValueError, 'ventana'):
            self.run_script()
        self.assert_no_portfolio()

    def test_uncompleted_minute(self):
        with self.assertRaisesRegex(ValueError, 'completa'):
            self.run_script(now=self.now.replace(minute=0, second=30))
        self.assertEqual(self.calls, [])
        self.assert_no_portfolio()

    def test_missing_candle(self):
        with self.assertRaisesRegex(ValueError, 'vela única'):
            self.run_script(fetch=lambda url: b'[]')
        self.assert_no_portfolio()

    def test_price_disagrees_with_closing(self):
        closing = json.loads(self.closing_path.read_bytes())
        closing['prices_usdt']['BTC'] = '111'
        self.closing_path.write_text(json.dumps(closing))
        with self.assertRaisesRegex(ValueError, 'No concilia'):
            self.run_script()
        self.assert_no_portfolio()

    def test_wrong_prior_hash(self):
        self.prior.write_bytes(self.prior.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'otra cartera'):
            self.run_script()
        self.assert_no_portfolio()

    def test_existing_lock_is_preserved(self):
        lock = self.root / 'update.lock'
        lock.write_text('another-process')
        with self.assertRaises(FileExistsError):
            self.run_script()
        self.assertEqual(lock.read_text(), 'another-process')


if __name__ == '__main__':
    unittest.main()
