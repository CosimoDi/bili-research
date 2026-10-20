"""One loopback report service per task, opened before reading begins."""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import webbrowser
from pathlib import Path

from .api import NoRedirect
from .common import Problem, read_json, write_json
from . import engine
from .report import make_server


def registry(task):
    return engine.task_dir(task) / 'preview.json'


def running(task):
    try:
        data = read_json(registry(task))
        url = urllib.parse.urlsplit(data['url'])
        route = '/' + task + '/journal.html'
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
                or url.username or url.password or url.path != route or url.query or url.fragment):
            return None
        req = urllib.request.Request(data['url'], method='HEAD')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(req, timeout=0.5) as response:
            if response.status == 200 and response.headers.get('X-Bili-Task') == task:
                return data
    except (Problem, OSError, ValueError, KeyError, TypeError):
        pass
    return None


def serve(task, port=0, register=False):
    report = engine.refresh_report(task)
    if not report['ready']:
        raise Problem('report_generation_failed', report['message'])
    route = '/' + task + '/journal.html'
    with make_server(Path(report['path']), route, port, task=task) as server:
        data = {'url': 'http://127.0.0.1:%s%s' % (server.server_port, route),
                'task': task, 'browser_action': 'open_report', 'live_updates': True,
                'lifetime': 'until_process_stops'}
        if register:
            write_json(registry(task), data)
        print(json.dumps({'ok': True, 'data': data}, ensure_ascii=False), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return {'server_stopped': True}


def open_report(task, browser=True):
    report = engine.refresh_report(task)
    if not report['ready']:
        raise Problem('report_generation_failed', report['message'])
    existing = running(task)
    if existing is None:
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'bili.py'),
                   'serve-report', '--task', task, '--register']
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and process.poll() is None:
            existing = running(task)
            if existing:
                break
            time.sleep(0.1)
        if existing is None:
            process.terminate()
            process.wait(timeout=3)
            raise Problem('preview_unavailable', '本地日记预览未能启动，日记文件仍保留。')
    requested = existing.get('browser_open_requested', False)
    if browser and not requested:
        try:
            requested = bool(webbrowser.open(existing['url'], new=2))
        except webbrowser.Error:
            requested = False
        existing['browser_open_requested'] = requested
        write_json(registry(task), existing)
    return dict(report, url=existing['url'], live_updates=True,
                browser_open_requested=requested, browser_verified=False,
                browser_action='verify_open_report' if requested else 'open_report')
