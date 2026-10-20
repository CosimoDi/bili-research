"""Device-confirmed QR login. Credentials never enter the CLI result or QR renderer.

Wire protocol reference: https://github.com/ylw1997/bilibili-API/blob/master/login/login_action/QR.md
"""
import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie, CookieError

from .api import NoRedirect, UA
from .common import Problem, home, integer, normalize_credentials, private_dir, read_json, write_json
from .media import worker_python

BASE = 'https://passport.bilibili.com/x/passport-login/web/qrcode/'
INTERVAL = 5
LIFETIME = 180


def qr_available():
    try:
        result = subprocess.run([worker_python(), '-c', 'import qrcode, png'],
                                capture_output=True, timeout=20)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def request(action, key=None):
    if action not in ('generate', 'poll'):
        raise Problem('invalid_argument', '未知登录操作。')
    url = BASE + action
    if key is not None:
        url += '?' + urllib.parse.urlencode({'qrcode_key': key})
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Referer': 'https://www.bilibili.com/', 'Accept-Encoding': 'identity'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=15) as response:
            if response.geturl() != url:
                raise Problem('unexpected_redirect', '登录接口发生重定向，已停止。')
            body = response.read(1024 * 1024 + 1)
            headers = response.headers.get_all('Set-Cookie', [])
        if len(body) > 1024 * 1024:
            raise Problem('response_too_large', '登录响应超过大小上限。')
        raw = json.loads(body)
    except urllib.error.HTTPError as exc:
        code = 'platform_blocked' if exc.code in (403, 412, 429) else 'network_error'
        raise Problem(code, '登录接口返回 HTTP %s，已停止；不自动重试。' % exc.code) from None
    except urllib.error.URLError as exc:
        # Only expose the exception class, never a URL, response, or credential.
        raise Problem('network_error', '登录接口连接失败（%s）；已停止。' % type(exc.reason).__name__) from None
    except (TimeoutError, OSError):
        raise Problem('network_error', '登录接口连接失败或超时；已停止。') from None
    except (ValueError, UnicodeError):
        raise Problem('invalid_response', '登录接口未返回有效 JSON；已停止。') from None
    if not isinstance(raw, dict):
        raise Problem('invalid_response', '登录响应结构发生变化。')
    if raw.get('code') in (-352, -412, -509, -401, -403):
        raise Problem('platform_blocked', '登录触发平台风控，已停止。')
    if raw.get('code') != 0 or not isinstance(raw.get('data'), dict):
        raise Problem('api_error', '登录接口未返回成功状态；已停止。')
    cookies = {}
    try:
        for header in headers:
            parsed = SimpleCookie()
            parsed.load(header)
            for name in ('SESSDATA', 'bili_jct', 'buvid3'):
                if name in parsed and parsed[name]['domain'].lstrip('.') in ('', 'bilibili.com', 'passport.bilibili.com'):
                    cookies[name] = parsed[name].value
    except CookieError:
        raise Problem('invalid_response', '登录 Cookie 格式异常；已停止。') from None
    return raw['data'], cookies


def render_qr(url, path):
    # Encode locally; never submit the login URL to an external QR service.
    program = '''import os, sys, qrcode
from qrcode.image.pure import PyPNGImage
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "wb") as output:
    qrcode.make(sys.stdin.read(), image_factory=PyPNGImage).save(output)
'''
    try:
        result = subprocess.run([worker_python(), '-c', program, str(path)], input=url,
                                text=True, capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        raise Problem('qr_render_failed', '本地二维码生成失败。') from None
    if result.returncode:
        raise Problem('qr_render_failed', '本地二维码生成失败；检查 qrcode 和 pypng 依赖。')


def paths():
    folder = home() / 'login'
    return folder / 'state.json', folder / 'qr.png'


def finish(status, task=None):
    state_path, qr_path = paths()
    write_json(state_path, dict(status=status, **({'task': task} if task else {})))
    qr_path.unlink(missing_ok=True)


def start(task=None):
    if task:
        from .engine import status
        status(task)  # Validate the explicitly bound task before creating a challenge.
    if not qr_available():
        raise Problem('setup_required', '缺少本地二维码依赖。',
                      ['运行 scripts/setup.py 安装 qrcode 和 pypng'])
    state_path, qr_path = paths()
    private_dir(state_path.parent)
    # Invalidate the old challenge locally; existing credentials remain untouched.
    finish('starting')
    created = time.time()
    data, _ = request('generate')
    url, key = data.get('url'), data.get('qrcode_key')
    if not isinstance(url, str) or not isinstance(key, str) or not key or len(key) > 512:
        raise Problem('invalid_response', '登录接口缺少二维码信息。')
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc not in ('passport.bilibili.com', 'account.bilibili.com'):
        raise Problem('unexpected_source', '二维码不是预期的 B 站 HTTPS 登录地址。')
    try:
        render_qr(url, qr_path)
        write_json(state_path, {'status': 'waiting_scan', 'key': key,
                               'expires_at': created + LIFETIME, 'next_poll_at': 0,
                               **({'task': task} if task else {})})
    except Exception:
        finish('failed')
        raise
    return {'status': 'waiting_scan', 'qr_path': str(qr_path), 'expires_in_seconds': LIFETIME,
            'next_action': 'display_qr_then_login_poll', 'poll_interval_seconds': INTERVAL,
            'user_action': '用 B 站 App 扫码，并在手机端确认登录；凭据将保存到本机。',
            **({'task': task} if task else {})}


def poll_once():
    state_path, _ = paths()
    if not state_path.exists():
        raise Problem('login_required', '尚未生成二维码；运行 login。')
    state = read_json(state_path)
    status = state.get('status')
    task = state.get('task')
    if status not in ('waiting_scan', 'waiting_confirmation'):
        return {'status': status, 'next_action': 'doctor --online' if status == 'configured' else 'login',
                **({'task': task} if task else {})}
    now = time.time()
    if now >= state['expires_at']:
        finish('expired')
        return {'status': 'expired', 'next_action': 'login'}
    if now < state['next_poll_at']:
        return {'status': status, 'retry_after_seconds': math.ceil(state['next_poll_at'] - now)}
    # Persist throttling before I/O so successive CLI invocations cannot busy-poll.
    state['next_poll_at'] = now + INTERVAL
    write_json(state_path, state)
    try:
        data, cookies = request('poll', state['key'])
        code = data.get('code')
        if code == 0:
            # Never report configured for a success-shaped response with empty cookies.
            normalized = normalize_credentials(cookies)
            write_json(home() / 'credentials.json', normalized)
            finish('configured', task)
            return {'status': 'configured', 'configured': True, 'credentials_echoed': False,
                    'online_verified': False, 'next_action': 'doctor --online',
                    **({'task': task} if task else {})}
        if code == 86038:
            finish('expired')
            return {'status': 'expired', 'next_action': 'login'}
        if code not in (86101, 86090):
            if code in (-352, -412, -509, -401, -403):
                raise Problem('platform_blocked', '扫码登录触发平台风控，已停止。')
            raise Problem('api_error', '扫码状态异常，已停止；未修改已有凭据。')
        state['status'] = 'waiting_scan' if code == 86101 else 'waiting_confirmation'
        write_json(state_path, state)
        return {'status': state['status'], 'retry_after_seconds': INTERVAL,
                'next_action': 'login --poll'}
    except Exception:
        finish('failed')
        raise


def poll(wait=0):
    integer(wait, 0, 60, '单次等待秒数')
    deadline = time.monotonic() + wait
    while True:
        result = poll_once()
        if result['status'] not in ('waiting_scan', 'waiting_confirmation'):
            return result
        delay = result.get('retry_after_seconds', INTERVAL)
        # Reserve the request timeout so a bounded wait never starts a late request.
        if time.monotonic() + delay + 15 > deadline:
            return result
        time.sleep(delay)


def cancel():
    finish('cancelled')
    return {'status': 'cancelled', 'credentials_changed': False}
