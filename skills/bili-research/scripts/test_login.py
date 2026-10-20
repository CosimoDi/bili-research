"""Offline login regression tests; no real account or network required."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

import bili
from bili_core import login
from bili_core.common import Problem, read_json, write_json


class LoginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'BILI_RESEARCH_HOME': str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.old = {'SESSDATA': 'old-session', 'bili_jct': '', 'buvid3': ''}
        write_json(self.root / 'credentials.json', self.old)

    def pending(self, **extra):
        state, qr = login.paths()
        write_json(state, dict(status='waiting_scan', key='private-key',
                               expires_at=300, next_poll_at=0, **extra))
        qr.write_bytes(b'old qr')

    def assert_old_preserved(self):
        self.assertEqual(read_json(self.root / 'credentials.json'), self.old)

    def test_start_returns_only_display_info(self):
        with patch.object(login, 'qr_available', return_value=True), \
             patch.object(login, 'request', return_value=({'url': 'https://passport.bilibili.com/h5-app/passport/login/scan?key=private-key', 'qrcode_key': 'private-key'}, {})), \
             patch.object(login, 'render_qr', side_effect=lambda url, path: path.write_bytes(b'qr')), \
             patch.object(login.time, 'time', return_value=100):
            result = login.start()
        self.assertEqual(result['status'], 'waiting_scan')
        self.assertNotIn('private-key', json.dumps(result))
        self.assertEqual(read_json(login.paths()[0])['expires_at'], 280)
        self.assert_old_preserved()

    def test_rejects_non_bilibili_qr(self):
        with patch.object(login, 'qr_available', return_value=True), \
             patch.object(login, 'request', return_value=({'url': 'https://evil.example/login', 'qrcode_key': 'secret'}, {})), \
             patch.object(login, 'render_qr') as render:
            with self.assertRaises(Problem) as error:
                login.start()
        self.assertEqual(error.exception.code, 'unexpected_source')
        render.assert_not_called()
        self.assert_old_preserved()

    def test_current_account_domain_is_supported(self):
        with patch.object(login, 'qr_available', return_value=True), \
             patch.object(login, 'request', return_value=({'url': 'https://account.bilibili.com/h5/account-h5/auth/scan-web?key=private-key', 'qrcode_key': 'private-key'}, {})), \
             patch.object(login, 'render_qr'):
            self.assertEqual(login.start()['status'], 'waiting_scan')

    def test_wait_scan_confirmation_and_throttle(self):
        self.pending()
        with patch.object(login, 'request', side_effect=[({'code': 86101}, {}), ({'code': 86090}, {})]) as req:
            with patch.object(login.time, 'time', return_value=100):
                self.assertEqual(login.poll()['status'], 'waiting_scan')
                self.assertEqual(login.poll()['retry_after_seconds'], 5)
                self.assertEqual(req.call_count, 1)
            with patch.object(login.time, 'time', return_value=105):
                self.assertEqual(login.poll()['status'], 'waiting_confirmation')
        self.assert_old_preserved()

    def test_success_saves_private_credentials_without_echo(self):
        self.pending()
        cookies = {'SESSDATA': 'new-secret%2Cencoded', 'bili_jct': 'csrf-secret', 'ignored': 'no'}
        with patch.object(login, 'request', return_value=({'code': 0, 'refresh_token': 'never-save'}, cookies)), \
             patch.object(login.time, 'time', return_value=100), \
             patch('sys.argv', ['bili.py', 'login', '--poll']):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(bili.main(), 0)
        result = json.loads(output.getvalue())['data']
        self.assertTrue(result['configured'])
        self.assertFalse(result['online_verified'])
        for secret in ('new-secret', 'csrf-secret', 'private-key', 'never-save'):
            self.assertNotIn(secret, output.getvalue())
        saved = read_json(self.root / 'credentials.json')
        self.assertEqual(saved, {'SESSDATA': cookies['SESSDATA'], 'bili_jct': 'csrf-secret', 'buvid3': ''})
        state, qr = login.paths()
        self.assertEqual(read_json(state), {'status': 'configured'})
        self.assertFalse(qr.exists())
        if os.name != 'nt':
            self.assertEqual((self.root / 'credentials.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_empty_success_does_not_overwrite_old_credentials(self):
        self.pending()
        with patch.object(login, 'request', return_value=({'code': 0}, {})), \
             patch.object(login.time, 'time', return_value=100):
            with self.assertRaises(Problem):
                login.poll()
        self.assert_old_preserved()
        self.assertEqual(read_json(login.paths()[0]), {'status': 'failed'})

    def test_expiry_stops_before_network(self):
        self.pending()
        with patch.object(login.time, 'time', return_value=301), patch.object(login, 'request') as req:
            self.assertEqual(login.poll()['status'], 'expired')
        req.assert_not_called()
        self.assertFalse(login.paths()[1].exists())
        self.assert_old_preserved()

    def test_platform_expiry_and_cancel(self):
        self.pending()
        with patch.object(login.time, 'time', return_value=100), \
             patch.object(login, 'request', return_value=({'code': 86038}, {})):
            self.assertEqual(login.poll()['status'], 'expired')
        self.pending()
        self.assertEqual(login.cancel()['status'], 'cancelled')
        with patch.object(login, 'request') as req:
            self.assertEqual(login.poll()['status'], 'cancelled')
        req.assert_not_called()
        self.assert_old_preserved()

    def test_network_or_blocked_error_is_terminal(self):
        for code in ('network_error', 'platform_blocked'):
            self.pending()
            with patch.object(login.time, 'time', return_value=100), \
                 patch.object(login, 'request', side_effect=Problem(code, 'safe error')) as req:
                with self.assertRaises(Problem):
                    login.poll(60)
                self.assertEqual(login.poll()['status'], 'failed')
                self.assertEqual(req.call_count, 1)
            self.assert_old_preserved()

    def test_request_cookie_filter_and_no_redirect_follow(self):
        headers = Message()
        headers.add_header('Set-Cookie', 'SESSDATA=encoded%2Cvalue; Domain=.bilibili.com; Secure; HttpOnly')
        headers.add_header('Set-Cookie', 'bili_jct=csrf; Domain=bilibili.com')
        headers.add_header('Set-Cookie', 'DedeUserID=123; Domain=bilibili.com')
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{"code":0,"data":{"code":0}}'
            def geturl(self): return login.BASE + 'poll?qrcode_key=test-key'
        response = Response()
        response.headers = headers
        with patch.object(login.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            data, cookies = login.request('poll', 'test-key')
            self.assertIsInstance(opener.call_args.args[0], login.NoRedirect)
            self.assertNotIn('Cookie', opener.return_value.open.call_args.args[0].headers)
        self.assertEqual(cookies, {'SESSDATA': 'encoded%2Cvalue', 'bili_jct': 'csrf'})
        self.assertEqual(data['code'], 0)

    def test_http_block_does_not_leak_sensitive_url(self):
        with patch.object(login.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect = urllib.error.HTTPError('https://example.com/?secret=hidden', 412, 'hidden', {}, None)
            with self.assertRaises(Problem) as error:
                login.request('poll', 'hidden')
        self.assertEqual(error.exception.code, 'platform_blocked')
        self.assertNotIn('hidden', error.exception.message)


if __name__ == '__main__':
    unittest.main()
