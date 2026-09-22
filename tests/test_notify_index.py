import importlib.util
import io
import unittest
from pathlib import Path
from urllib.parse import parse_qs

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/notify_index.py'
SPEC = importlib.util.spec_from_file_location('notify_index_tests_target', SCRIPT)
notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notify)


class NotifyIndexTests(unittest.TestCase):
    def test_sends_fixed_message_as_post(self):
        seen = []
        def opener(request, timeout):
            seen.append(request)
            self.assertEqual(timeout, 20)
            return io.BytesIO(b'{"status":1}')
        notify.send('crypto-index-daily.service',
                    {'PUSHOVER_TOKEN': 'test-token', 'PUSHOVER_USER': 'test-user'}, opener)
        self.assertEqual(seen[0].method, 'POST')
        payload = parse_qs(seen[0].data.decode())
        self.assertEqual(payload['priority'], ['0'])
        self.assertNotIn('test-token', payload['message'][0])

    def test_missing_credentials(self):
        with self.assertRaises(ValueError):
            notify.send('crypto-index-daily.service', {})

    def test_error_details_are_not_exposed(self):
        def opener(*args, **kwargs):
            raise RuntimeError('SECRET_FROM_PROVIDER')
        with self.assertRaisesRegex(RuntimeError, '^No se pudo confirmar') as caught:
            notify.send('crypto-index-daily.service',
                        {'PUSHOVER_TOKEN': 'a', 'PUSHOVER_USER': 'b'}, opener)
        self.assertNotIn('SECRET_FROM_PROVIDER', str(caught.exception))

    def test_rejected_message_is_not_success(self):
        with self.assertRaises(RuntimeError):
            notify.send('crypto-index-capture.service',
                        {'PUSHOVER_TOKEN': 'a', 'PUSHOVER_USER': 'b'},
                        lambda *a, **k: io.BytesIO(b'{"status":0}'))


if __name__ == '__main__':
    unittest.main()
