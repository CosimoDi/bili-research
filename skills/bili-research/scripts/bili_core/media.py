"""Full-audio Whisper fallback and explicit frame extraction.

Audio download/transcribe flow adapted from dsh-bili-scroll/lib/asr.py
(MIT, 2026 dsh-bili-duty contributors); frame tiling inspired by
dsh-bili-whale/tools/commands/bili-watch.mjs (MIT, 2026 ALTERSSSS).
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import Problem, home, private_dir


def worker_python():
    venv = home() / 'venv'
    candidate = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if candidate.exists():
        return str(candidate)
    return sys.executable


def dependencies():
    p = subprocess.run([worker_python(), '-c',
                        'import importlib.util,json; print(json.dumps({m:importlib.util.find_spec(m) is not None for m in ["yt_dlp","faster_whisper"]}))'],
                       capture_output=True, text=True, timeout=20)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {'yt_dlp': False, 'faster_whisper': False}


def run_worker(bv, part, mode='audio', model='small', output=None, count=9):
    dep = dependencies()
    needed = ['yt_dlp'] + (['faster_whisper'] if mode == 'audio' else [])
    if any(not dep.get(k) for k in needed):
        raise Problem('setup_required', '缺少本地媒体依赖。', ['运行 scripts/setup.py 创建隔离环境并安装依赖'])
    if mode == 'frames' and not shutil.which('ffmpeg'):
        raise Problem('setup_required', '按需抽帧需要 ffmpeg。', ['安装 ffmpeg 或将其加入 PATH'])
    private_dir(home() / 'tmp')
    with tempfile.TemporaryDirectory(dir=home() / 'tmp', prefix='media-') as tmp:
        target = Path(tmp) / 'result.json'
        command = [worker_python(), str(Path(__file__).with_name('media_worker.py')),
                   '--bvid', bv, '--page', str(part['page']), '--duration', str(part['duration']),
                   '--mode', mode, '--model', model, '--work', tmp, '--result', str(target), '--count', str(count)]
        if output:
            command += ['--output', str(output)]
        try:
            p = subprocess.run(command, capture_output=True, text=True, timeout=7200)
        except subprocess.TimeoutExpired:
            raise Problem('media_timeout', '媒体处理超过两小时，未计为已观看；可调整转写模型后重试。')
        if not target.exists():
            raise Problem('media_failed', '媒体工具未产生结果；可能被平台限制或本地依赖失败。未输出含凭据的底层日志。')
        result = json.loads(target.read_text(encoding='utf-8'))
        if p.returncode or not result.get('ok'):
            raise Problem(result.get('code', 'media_failed'), result.get('message', '媒体处理失败。'))
        return result['data']


def coverage(transcript, duration):
    segs = transcript.get('segments') or []
    if not segs:
        return {'span_ratio': 0, 'large_gaps': [], 'warning': '无可读文字。'}
    if any(s['start'] < 0 or s['end'] < s['start'] or not s['text'].strip() for s in segs):
        raise Problem('bad_transcript', '转写时间轴无效。')
    segs.sort(key=lambda s: s['start'])
    gaps, end = [], 0.0
    for s in segs:
        if s['start'] - end > 30:
            gaps.append([end, s['start']])
        end = max(end, s['end'])
    if duration-end > 30:
        gaps.append([end, duration])
    ratio = min(1, max(0, end-segs[0]['start']) / max(1, duration))
    return {'span_ratio': round(ratio, 3), 'large_gaps': gaps,
            'warning': '时间跨度不能证明每句话都识别正确；空白可能是静音、画面信息或识别遗漏。'}


def prepare(client, bv, options):
    video = client.video(bv)
    transcripts = []
    for part in video['parts']:
        transcript = None
        if options['transcript'] != 'whisper-first':
            transcript = client.subtitles(bv, part)
            if transcript and (not transcript['segments'] or coverage(transcript, part['duration'])['span_ratio'] < 0.70):
                transcript = None
        if not transcript:
            if options['transcript'] == 'subtitle-only':
                raise Problem('transcript_missing', '字幕缺失或时间跨度不足，不能计为完整观看；可切换 auto 或 whisper-first。')
            transcript = run_worker(bv, part, model=options['whisper_model'])
        if not transcript.get('segments'):
            raise Problem('transcript_empty', '整段音频处理后未得到可读文字；不能计为完整观看。')
        transcript['part'] = part
        transcript['coverage'] = coverage(transcript, part['duration'])
        for i, row in enumerate(transcript['segments'], 1):
            row['id'] = 't:p%s:%s' % (part['page'], i)
        transcripts.append(transcript)
    # A failed comment request never becomes a successful empty comment sample.
    comments = client.comments(video['aid'], options['comments'], options['threads'], options['replies'])
    return {'video': video, 'transcripts': transcripts, 'comments': comments,
            'interpretation_boundary': '已获取所有分 P 的可用字幕轨或处理完整音频。默认未看画面；评论是样本。材料完整交付不等于模型理解已获独立验证。'}
