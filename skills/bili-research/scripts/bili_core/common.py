import json
import os
import re
import tempfile
from pathlib import Path


class Problem(Exception):
    def __init__(self, code, message, needs=None):
        super().__init__(message)
        self.code, self.message, self.needs = code, message, needs or []


def home():
    default = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'bili-research'
    return Path(os.environ.get('BILI_RESEARCH_HOME', default)).expanduser().resolve()


def private_dir(p):
    p.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        p.chmod(0o700)
    return p


def write_json(p, data):
    private_dir(p.parent)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise Problem('invalid_json', '文件无法读取或不是有效 JSON；请检查本地文件。')


def credentials():
    p = home() / 'credentials.json'
    if not p.is_file():
        raise Problem('setup_required', '需要用户在本机配置 B 站账号；不要把 Cookie 发到聊天中。',
                      ['运行 configure 的本地隐藏输入，或提供本地凭据文件路径'])
    d = read_json(p)
    if not isinstance(d, dict) or not isinstance(d.get('SESSDATA'), str) or not d['SESSDATA'].strip():
        raise Problem('setup_required', '凭据文件缺少 SESSDATA。', ['重新运行 configure'])
    return d


def normalize_credentials(d):
    if not isinstance(d, dict):
        raise Problem('invalid_credentials', '凭据必须是 JSON 对象。')
    result = {}
    for key in ('SESSDATA', 'bili_jct', 'buvid3'):
        value = d.get(key, d.get(key.lower(), ''))
        if not isinstance(value, str) or any(c in value for c in '\r\n;'):
            raise Problem('invalid_credentials', '凭据格式不正确。')
        result[key] = value.strip()
    if not result['SESSDATA']:
        raise Problem('invalid_credentials', 'SESSDATA 不能为空。')
    return result


def bvid(value):
    m = re.search(r'(?<![A-Za-z0-9])BV[0-9A-Za-z]{10}(?![A-Za-z0-9])', value)
    if not m:
        raise Problem('invalid_bvid', '请提供 BV 号或包含 BV 号的视频链接。')
    return m.group(0)


def integer(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Problem('invalid_argument', '%s 必须在 %s–%s 之间。' % (label, low, high))
    return value
