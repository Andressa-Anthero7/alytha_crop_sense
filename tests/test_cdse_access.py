import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from app import cdse_access, web_app


class AccessTests(unittest.TestCase):
    def gate(self):
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        return cdse_access.RateGate(clock=lambda: now[0], sleep=sleep), now

    def test_requests_have_minimum_gap(self):
        gate, now = self.gate()
        opener = Mock(side_effect=lambda *a, **k: io.BytesIO(b'ok'))
        for _ in range(2):
            with gate.open('request', opener) as response:
                self.assertEqual(response.read(), b'ok')
        self.assertEqual(now[0], 5)

    def test_rate_limit_respects_milliseconds(self):
        gate, now = self.gate()
        opener = Mock(side_effect=[HTTPError('url', 429, 'limited', {'Retry-After': '90000'}, None), io.BytesIO(b'ok')])
        with gate.open('request', opener):
            pass
        self.assertEqual(now[0], 90)
        self.assertEqual(opener.call_count, 2)

    def test_retries_are_bounded(self):
        gate, now = self.gate()
        opener = Mock(side_effect=lambda *a, **k: (_ for _ in ()).throw(HTTPError('url', 429, 'limited', {}, None)))
        with self.assertRaises(HTTPError):
            with gate.open('request', opener):
                pass
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(now[0], 90)
        self.assertEqual(gate.next_at, 210)

    def test_forbidden_is_not_retried(self):
        gate, _ = self.gate()
        opener = Mock(side_effect=HTTPError('url', 403, 'forbidden', {}, None))
        with self.assertRaises(HTTPError):
            with gate.open('request', opener):
                pass
        self.assertEqual(opener.call_count, 1)

    def test_token_reused_until_expiry(self):
        gate, now = self.gate()
        opener = Mock(side_effect=lambda *a, **k: io.BytesIO(json.dumps({'access_token': 'fixture', 'expires_in': 300}).encode()))
        env = {'CDSE_CLIENT_ID': 'fixture-id', 'CDSE_CLIENT_SECRET': 'fixture-secret'}
        with patch.object(cdse_access, 'RATE', gate), patch.dict(cdse_access.TOKEN, {'credentials': None, 'value': None, 'expires_at': 0}), patch.object(web_app, 'read_app_env', return_value=env), patch.object(web_app, 'urlopen', opener):
            self.assertEqual(web_app.get_cdse_access_token(), 'fixture')
            self.assertEqual(web_app.get_cdse_access_token(), 'fixture')
            self.assertEqual(opener.call_count, 1)
            now[0] = 271
            web_app.get_cdse_access_token()
            self.assertEqual(opener.call_count, 2)


if __name__ == '__main__':
    unittest.main()
