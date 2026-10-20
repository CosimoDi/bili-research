"""Isolated preview/login integration tests. No real account, task, or browser."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import bili
from bili_core import engine, login, live_report, report
from bili_core.common import Problem, read_json, write_json


class LiveReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'BILI_RESEARCH_HOME': str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.task = engine.create('独立测试任务', 2, '测试用模拟学生', '', {})['task']

    def start_server(self):
        page = engine.task_dir(self.task) / 'journal.html'
        route = '/' + self.task + '/journal.html'
        server = report.make_server(page, route, task=self.task)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.addCleanup(close)
        url = 'http://127.0.0.1:%s%s' % (server.server_port, route)
        write_json(live_report.registry(self.task), {'url': url, 'task': self.task})
        return url

    def test_live_service_reused_and_browser_opened_once(self):
        url = self.start_server()
        with patch.object(live_report.webbrowser, 'open', return_value=True) as browser, \
             patch.object(live_report.subprocess, 'Popen') as spawn:
            first = live_report.open_report(self.task)
            second = live_report.open_report(self.task)
        spawn.assert_not_called()
        browser.assert_called_once_with(url, new=2)
        self.assertEqual(first['url'], second['url'])
        self.assertTrue(first['live_updates'])
        self.assertFalse(first['browser_verified'])

    def test_host_browser_mode_does_not_open_system_browser(self):
        self.start_server()
        with patch.object(live_report.webbrowser, 'open') as browser:
            result = live_report.open_report(self.task, browser=False)
        browser.assert_not_called()
        self.assertEqual(result['browser_action'], 'open_report')

    def test_service_starts_in_isolated_process_and_is_reused(self):
        original = live_report.subprocess.Popen
        processes = []
        def spawn(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        def cleanup():
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=3)
        self.addCleanup(cleanup)
        with patch.object(live_report.subprocess, 'Popen', side_effect=spawn):
            first = live_report.open_report(self.task, browser=False)
            second = live_report.open_report(self.task, browser=False)
        self.assertEqual(len(processes), 1)
        self.assertEqual(first['url'], second['url'])
        self.assertTrue(live_report.running(self.task))

    def test_served_content_updates_without_restart_and_keeps_secrets_private(self):
        url = self.start_server()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url) as response:
            first = response.read().decode()
            self.assertIn("script-src 'sha256-", response.headers['Content-Security-Policy'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('第一篇日记正在路上', first)
        with engine.connect(self.task) as db:
            snapshot = engine.snapshot(db)
        snapshot['status'].update(completed=1, remaining=1)
        snapshot['diaries'] = [{
            'bvid': 'BV1234567890', 'video': {'title': '测试视频', 'author': '测试作者'},
            'summary': '测试内容', 'mood_before': {'label': '好奇', 'intensity': 2},
            'mood_after': {'label': '安心', 'intensity': 3}, 'mood_reason': '找到可以尝试的办法',
            'reflection': '我想先试一周，再看这条建议适不适合我。<script>alert(1)</script>',
            'observations': [{'claim': '测试观点', 'evidence_ids': ['test:1']}],
            'questions': ['实际执行会遇到什么问题？'], 'next_interests': [], 'uncertainties': []}]
        report.write_report(engine.task_dir(self.task) / 'journal.html', snapshot)
        with opener.open(url) as response:
            updated = response.read().decode()
        self.assertIn('我想先试一周', updated)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', updated)
        self.assertNotIn('第一篇日记正在路上', updated)
        self.assertIn(report.LIVE_SCRIPT, updated)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            opener.open(url.replace('journal.html', 'credentials.json'))
        self.assertEqual(denied.exception.code, 404)

    def test_registry_cannot_redirect_health_check_to_remote_host(self):
        write_json(live_report.registry(self.task), {'url': 'https://example.com/'})
        with patch.object(live_report.urllib.request, 'build_opener') as opener:
            self.assertIsNone(live_report.running(self.task))
        opener.assert_not_called()

    def pending_login(self):
        write_json(login.paths()[0], {'status': 'waiting_scan', 'key': 'test-secret',
                                     'expires_at': 300, 'next_poll_at': 0, 'task': self.task})

    def test_confirmation_verifies_account_then_opens_bound_diary(self):
        self.pending_login()
        events = []
        with patch.object(login.time, 'time', return_value=100), \
             patch.object(login, 'request', return_value=({'code': 0}, {'SESSDATA': 'test-session'})), \
             patch.object(bili.Client, 'nav', side_effect=lambda: events.append('verify')), \
             patch.object(live_report, 'open_report', side_effect=lambda task, browser: events.append(('open', task, browser)) or {'ready': True}):
            result = bili.run(bili.parser().parse_args(['login', '--poll', '--no-browser']))
        self.assertEqual(events, ['verify', ('open', self.task, False)])
        self.assertEqual(result['task'], self.task)
        self.assertTrue(result['online_verified'])
        self.assertEqual(read_json(login.paths()[0]), {'status': 'configured', 'task': self.task})

    def test_no_preview_before_confirmation_or_when_verification_fails(self):
        self.pending_login()
        with patch.object(login.time, 'time', return_value=100), \
             patch.object(login, 'request', return_value=({'code': 86090}, {})), \
             patch.object(live_report, 'open_report') as preview, patch.object(bili.Client, 'nav') as nav:
            bili.run(bili.parser().parse_args(['login', '--poll']))
        preview.assert_not_called()
        nav.assert_not_called()
        with patch.object(login.time, 'time', return_value=106), \
             patch.object(login, 'request', return_value=({'code': 0}, {'SESSDATA': 'test-session'})), \
             patch.object(bili.Client, 'nav', side_effect=Problem('network_error', 'test')), \
             patch.object(live_report, 'open_report') as preview:
            with self.assertRaises(Problem):
                bili.run(bili.parser().parse_args(['login', '--poll']))
        preview.assert_not_called()

    def test_different_task_cannot_take_over_login(self):
        self.pending_login()
        other = engine.create('另一个独立测试任务', 1, '测试', '', {})['task']
        with patch.object(login, 'poll') as poll:
            with self.assertRaises(Problem) as error:
                bili.run(bili.parser().parse_args(['login', '--poll', '--task', other]))
        self.assertEqual(error.exception.code, 'login_task_mismatch')
        poll.assert_not_called()


if __name__ == '__main__':
    unittest.main()
