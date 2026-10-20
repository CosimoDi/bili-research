#!/usr/bin/env python3
"""JSON command interface for any Agent with local process/file access."""
import argparse
import getpass
import json
import os
import shutil
import sys
from pathlib import Path

from bili_core import engine
from bili_core.api import Client
from bili_core.common import Problem, credentials, home, integer, normalize_credentials, read_json, write_json
from bili_core.media import dependencies, worker_python


def parser():
    p = argparse.ArgumentParser(description='Bilibili reading + cumulative diary, independent of any Harness')
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('doctor'); d.add_argument('--online', action='store_true')
    login = sub.add_parser('login', help='生成本地登录二维码，扫码确认后自动保存凭据')
    mode = login.add_mutually_exclusive_group()
    mode.add_argument('--poll', action='store_true')
    mode.add_argument('--cancel', action='store_true')
    login.add_argument('--wait', type=int, default=0, help='配合 --poll，单次等待 0–60 秒')
    login.add_argument('--task', help='绑定当前会话的任务，扫码验证后先打开该任务的日记')
    login.add_argument('--no-browser', action='store_true', help='返回本机预览 URL，由宿主打开')
    c = sub.add_parser('configure'); c.add_argument('--credentials-file')
    t = sub.add_parser('new')
    t.add_argument('--goal', required=True); t.add_argument('--count', required=True, type=int)
    group = t.add_mutually_exclusive_group(required=True)
    group.add_argument('--persona'); group.add_argument('--persona-file')
    t.add_argument('--followup', default='总结学到的内容、认知变化与仍待验证的问题。')
    t.add_argument('--transcript', choices=['auto', 'whisper-first', 'subtitle-only'], default='auto')
    t.add_argument('--whisper-model', choices=['tiny', 'base', 'small', 'medium', 'large-v3'], default='small')
    t.add_argument('--comments', type=int, default=30)
    t.add_argument('--threads', type=int, default=3)
    t.add_argument('--replies', type=int, default=10)
    d = sub.add_parser('discover'); d.add_argument('--query', required=True); d.add_argument('--limit', type=int, default=20)
    d.add_argument('--pages', type=int, default=3)
    e = sub.add_parser('enqueue'); e.add_argument('--task', required=True); e.add_argument('videos', nargs='+')
    for name in ('next', 'status', 'export', 'report'):
        sub.add_parser(name).add_argument('--task', required=True)
    server = sub.add_parser('serve-report'); server.add_argument('--task', required=True)
    server.add_argument('--port', type=int, default=0)
    server.add_argument('--register', action='store_true', help=argparse.SUPPRESS)
    diary = sub.add_parser('open-diary', help='启动或复用当前任务的实时日记页面')
    diary.add_argument('--task', required=True)
    diary.add_argument('--no-browser', action='store_true')
    a = sub.add_parser('ack'); a.add_argument('--task', required=True); a.add_argument('--receipt', required=True)
    j = sub.add_parser('journal'); j.add_argument('--task', required=True); j.add_argument('--file', required=True)
    s = sub.add_parser('skip'); s.add_argument('--task', required=True); s.add_argument('--reason', required=True)
    f = sub.add_parser('frames'); f.add_argument('--task', required=True); f.add_argument('--page', type=int, default=1); f.add_argument('--count', type=int, default=9)
    o = sub.add_parser('set-transcript'); o.add_argument('--task', required=True)
    o.add_argument('--mode', choices=['auto', 'whisper-first', 'subtitle-only'], required=True)
    return p


def run(a):
    if a.command == 'login':
        from bili_core import login
        if a.wait and not a.poll:
            raise Problem('invalid_argument', '--wait 只能配合 --poll 使用。')
        if a.cancel:
            return login.cancel()
        if not a.poll:
            return login.start(a.task)
        if a.task:
            engine.status(a.task)
            state_path, _ = login.paths()
            state = read_json(state_path)
            if state.get('task') and state['task'] != a.task:
                raise Problem('login_task_mismatch', '扫码流程已绑定其他任务；不要切换正在登录的任务。')
            state['task'] = a.task
            write_json(state_path, state)
        result = login.poll(a.wait)
        if result.get('status') == 'configured' and result.get('task'):
            Client().nav()
            from bili_core.live_report import open_report
            result.update(online_verified=True, report=open_report(result['task'], browser=not a.no_browser),
                          next_action='verify_diary_open_then_discover_or_enqueue')
        return result
    if a.command == 'doctor':
        from bili_core.login import qr_available
        needs = []
        configured = True
        try:
            credentials()
        except Problem:
            configured = False
            needs.append({'kind': 'account', 'action': '运行 login 并向用户展示二维码，用户用 B 站 App 扫码确认后运行 login --poll。'})
        dep = dependencies()
        if not all(dep.values()):
            needs.append({'kind': 'dependencies', 'action': '运行随包 scripts/setup.py；Whisper 模型首次使用会下载。'})
        data = {'runtime_home': str(home()), 'credentials_configured': configured, 'media_python': worker_python(),
                'dependencies': dep, 'ffmpeg_available': bool(shutil.which('ffmpeg')), 'needs': needs,
                'ready_for_subtitles': configured, 'ready_for_asr': configured and all(dep.values()),
                'model_policy': '不需要单独配置大模型 API；由调用 Skill 的 Agent 阅读、判断和写日记。',
                'online_verified': False, 'qr_login_ready': qr_available()}
        if a.online:
            Client().nav()
            data['online_verified'] = True
        return data
    if a.command == 'configure':
        if a.credentials_file:
            raw = read_json(Path(a.credentials_file).expanduser())
        else:
            if not sys.stdin.isatty():
                raise Problem('user_input_required', '请让用户在本地终端运行 configure，或传入用户提供的凭据文件路径。')
            raw = {k: getpass.getpass(k + ('（可留空）' if k != 'SESSDATA' else '') + ': ') for k in ('SESSDATA', 'bili_jct', 'buvid3')}
        write_json(home() / 'credentials.json', normalize_credentials(raw))
        return {'configured': True, 'next_action': 'doctor --online', 'credentials_echoed': False}
    if a.command == 'new':
        persona = Path(a.persona_file).read_text(encoding='utf-8') if a.persona_file else a.persona
        options = {'transcript': a.transcript, 'whisper_model': a.whisper_model,
                   'comments': integer(a.comments, 1, 200, '主评论样本数'),
                   'threads': integer(a.threads, 0, 10, '楼中楼线程数'),
                   'replies': integer(a.replies, 1, 20, '每线程回复数')}
        return engine.create(a.goal, a.count, persona, a.followup, options)
    if a.command == 'discover':
        if not a.query.strip() or len(a.query) > 500:
            raise Problem('invalid_argument', '搜索词必须为 1–500 字。')
        rows = Client().search(a.query, integer(a.limit, 1, 100, '搜索结果数'), integer(a.pages, 1, 5, '搜索页数'))
        return {'untrusted_material': True, 'candidates': rows, 'returned': len(rows),
                'next_action': 'select_relevant_candidates_then_enqueue', 'scope': '有限搜索结果；不保证覆盖全部相关视频。'}
    if a.command == 'enqueue': return engine.enqueue(a.task, a.videos)
    if a.command == 'next': return engine.next_packet(a.task, Client)
    if a.command == 'ack': return engine.ack(a.task, a.receipt)
    if a.command == 'journal': return engine.commit_diary(a.task, read_json(a.file))
    if a.command == 'skip': return engine.skip(a.task, a.reason)
    if a.command == 'frames': return engine.frames(a.task, a.page, a.count)
    if a.command == 'set-transcript': return engine.set_transcript(a.task, a.mode)
    if a.command == 'status': return engine.status(a.task)
    if a.command == 'export': return engine.export(a.task)
    if a.command == 'report': return engine.refresh_report(a.task)
    if a.command == 'open-diary':
        from bili_core.live_report import open_report
        return open_report(a.task, browser=not a.no_browser)
    if a.command == 'serve-report':
        from bili_core.live_report import serve
        return serve(a.task, integer(a.port, 0, 65535, '端口'), a.register)
    raise Problem('unknown_command', '未知命令。')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    a = parser().parse_args()
    try:
        out, code = {'ok': True, 'data': run(a)}, 0
    except Problem as e:
        out, code = {'ok': False, 'error': {'code': e.code, 'message': e.message, 'needs': e.needs}}, 2
    except KeyboardInterrupt:
        out, code = {'ok': False, 'error': {'code': 'interrupted', 'message': '操作中断，未完成的视频不计数。'}}, 130
    except Exception as e:
        # Exception strings may include signed subtitle URLs or account data.
        out, code = {'ok': False, 'error': {'code': 'unexpected_error', 'type': type(e).__name__,
                                         'message': '操作失败；未输出可能包含凭据的底层异常。'}}, 1
    print(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
