import contextlib
import importlib.util
import io
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import test_rebalance_daily as fixtures

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'monthly_cycle.py'
SPEC = importlib.util.spec_from_file_location('monthly_cycle_tests_target', SCRIPT)
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)


class MonthlyCycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RebalanceDailyTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.project = self.fixture.root / 'project'
        self.daily = self.project / 'runs' / 'daily'
        self.daily.mkdir(parents=True)
        shutil.copytree(self.fixture.root / 'observations', self.daily / 'observations')
        shutil.copyfile(self.fixture.prior, self.daily / 'portfolio_seed.json')
        manifest = {'portfolio_file': 'portfolio_seed.json', 'sha256': {
            'portfolio_seed.json': fixtures.module.digest(self.fixture.prior.read_bytes())}}
        (self.daily / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        self.calls = []

    def execute(self, args):
        self.calls.append(args)
        if args[:2] == ['-m', 'crypto_index.cli']:
            directory = Path(args[args.index('--output') + 1]) / '2026-09'
            if not directory.exists():
                shutil.copytree(self.fixture.selection, directory)
        elif args[0] == 'scripts/rebalance_daily.py':
            fixtures.module.run(
                self.daily, Path(args[args.index('--portfolio') + 1]),
                Path(args[args.index('--selection') + 1]), '2026-09-30',
                now=self.fixture.now, fetch=self.fixture.fetch)
        else:
            self.fail(f'Unexpected command: {args}')

    def run_cycle(self, phase, **kwargs):
        with (patch.object(cycle, 'PROJECT', self.project),
              contextlib.redirect_stdout(io.StringIO())):
            return cycle.run(phase, now=kwargs.get('now', self.fixture.now),
                             cutoff=kwargs.get('cutoff'), execute_step=self.execute)

    def test_capture_finalize_and_repeat_preserve_portfolio(self):
        self.assertEqual(self.run_cycle('capture')['status'], 'selection_ready')
        self.assertEqual(self.run_cycle('finalize')['status'], 'portfolio_ready')
        path = self.daily / 'portfolios' / 'portfolio_2026-09-30.json'
        raw = path.read_bytes()
        count = len(self.calls)
        self.assertEqual(self.run_cycle('finalize')['status'], 'portfolio_ready')
        self.assertEqual(len(self.calls), count)
        self.assertEqual(path.read_bytes(), raw)
        self.assertFalse((self.project / 'runs/monthly/cycle.lock').exists())

    def test_missing_capture_blocks_without_commands(self):
        with self.assertRaisesRegex(ValueError, 'Falta la captura'):
            self.run_cycle('finalize')
        self.assertEqual(self.calls, [])
        status_paths = list((self.project / 'runs/monthly').glob('*finalize*.json'))
        self.assertEqual(json.loads(status_paths[0].read_bytes())['status'], 'action_required')

    def test_unknown_asset_blocks_publication(self):
        report_path = self.fixture.selection / 'report.json'
        report = json.loads(report_path.read_bytes())
        report['status'] = 'review_required'
        report['review'] = [{'cmc_id': 123456, 'symbol': 'NEW'}]
        report_path.write_text(json.dumps(report), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'pendiente de revisión'):
            self.run_cycle('capture')
        with self.assertRaisesRegex(ValueError, 'pendiente de revisión'):
            self.run_cycle('finalize')
        self.assertFalse((self.daily / 'portfolios').exists())

    def test_capture_outside_window_does_not_fetch(self):
        with self.assertRaisesRegex(ValueError, 'captura requiere'):
            self.run_cycle('capture', now=self.fixture.now.replace(hour=14))
        self.assertEqual(self.calls, [])

    def test_recovery_uses_saved_selection(self):
        self.run_cycle('capture')
        later = self.fixture.now.replace(month=10, day=1)
        self.assertEqual(self.run_cycle('finalize', now=later,
                                       cutoff='2026-09-30')['status'], 'portfolio_ready')
        self.assertEqual(sum(args[0] == '-m' for args in self.calls), 1)

    def test_existing_lock_is_preserved(self):
        root = self.project / 'runs/monthly'
        root.mkdir()
        lock = root / 'cycle.lock'
        lock.write_text('another-process')
        with self.assertRaises(FileExistsError):
            self.run_cycle('capture')
        self.assertEqual(lock.read_text(), 'another-process')

    def test_corrupt_seed_blocks_rebalance(self):
        self.run_cycle('capture')
        with (self.daily / 'portfolio_seed.json').open('ab') as stream:
            stream.write(b' ')
        with self.assertRaisesRegex(ValueError, 'Semilla modificada'):
            self.run_cycle('finalize')
        self.assertFalse((self.daily / 'portfolios').exists())


if __name__ == '__main__':
    unittest.main()
