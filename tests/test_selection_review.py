import json
import unittest
import test_rebalance_daily as fixtures
from crypto_index.selection_review import review, resolve_selection


class SelectionReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RebalanceDailyTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.original = self.fixture.selection
        self.approved = self.fixture.root / 'approved.json'
        self.approved.write_text(json.dumps(self.fixture.registry))
        del self.fixture.registry['1']
        self.fixture.save_selection()

    def test_review_preserves_sources_and_can_rebalance(self):
        before = {p.name: p.read_bytes() for p in self.original.iterdir() if p.is_file()}
        result = review(self.original, self.approved, ['1'])
        self.assertEqual(result, self.original / 'reviewed')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.original.iterdir() if p.is_file()})
        report = json.loads((result / 'report.json').read_bytes())
        self.assertEqual(report['status'], 'composition_ready')
        self.assertEqual(report['selection_date'], '2026-09-29')
        self.fixture.selection = resolve_selection(self.original)
        self.assertTrue(self.fixture.run_script().exists())

    def test_original_without_review_is_used(self):
        self.assertEqual(resolve_selection(self.original), self.original)

    def test_repeated_review_does_not_overwrite(self):
        result = review(self.original, self.approved, ['1'])
        before = (result / 'report.json').read_bytes()
        with self.assertRaises(FileExistsError):
            review(self.original, self.approved, ['1'])
        self.assertEqual((result / 'report.json').read_bytes(), before)

    def test_market_data_change_is_rejected(self):
        result = review(self.original, self.approved, ['1'])
        (result / 'cmc.json').write_text('{}')
        with self.assertRaises(ValueError):
            resolve_selection(self.original)

    def test_existing_identity_cannot_be_reclassified(self):
        with self.assertRaises(ValueError):
            review(self.original, self.approved, ['2'])
        self.assertFalse((self.original / 'reviewed').exists())

    def test_original_report_change_is_rejected(self):
        review(self.original, self.approved, ['1'])
        path = self.original / 'report.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            resolve_selection(self.original)


if __name__ == '__main__':
    unittest.main()
