"""Isolated dependency worker. Never print cookies or downloader exception text."""
import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bili_core.common import Problem, credentials, home, private_dir


class QuietLog:
    def debug(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


def execute(a):
    from yt_dlp import YoutubeDL
    root = Path(a.work)
    opts = {'format': 'bestaudio/best' if a.mode == 'audio' else 'bestvideo[ext=mp4][height<=720]/best[ext=mp4]',
            'outtmpl': str(root / 'source.%(ext)s'), 'paths': {'home': str(root), 'temp': str(root)},
            'quiet': True, 'no_warnings': True, 'logger': QuietLog(), 'noplaylist': True,
            'cachedir': False, 'retries': 0, 'fragment_retries': 0, 'socket_timeout': 35,
            'http_headers': {'Referer': 'https://www.bilibili.com/'}}
    with YoutubeDL(opts) as ydl:
        for name, value in credentials().items():
            if name not in ('SESSDATA', 'bili_jct', 'buvid3') or not value:
                continue
            ydl.cookiejar.set_cookie(http.cookiejar.Cookie(
                0, name, value, None, False, '.bilibili.com', True, True, '/', True,
                True, None, True, None, None, {}, False))
        info = ydl.extract_info('https://www.bilibili.com/video/%s?p=%s' % (a.bvid, a.page), download=True)
        if info.get('_type') in ('playlist', 'multi_video') or not info.get('duration'):
            raise Problem('media_scope_unverified', '下载结果无法确认分 P 或完整时长，停止计数。')
        if abs(float(info['duration'])-a.duration) > max(5, a.duration*0.02):
            raise Problem('media_duration_mismatch', '下载音视频时长与目标分 P 不一致，停止计数。')
        source = ydl.prepare_filename(info)
    if a.mode == 'frames':
        out = Path(a.output)
        private_dir(out.parent)
        # Explicit visual supplement only; timestamped separate images preserve legibility.
        result = []
        for i in range(a.count):
            t = a.duration * (i + 0.5) / a.count
            dest = out.parent / ('%s-p%s-f%s.jpg' % (a.bvid, a.page, i+1))
            p = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', str(t), '-i', source,
                                '-frames:v', '1', '-vf', 'scale=1280:-2', str(dest)], capture_output=True, timeout=90)
            if p.returncode or not dest.exists():
                raise Problem('frame_failed', '抽帧失败。')
            result.append({'id': 'v:p%s:%s' % (a.page, i+1), 'time': t, 'path': str(dest)})
        return {'frames': result, 'warning': '稀疏采样，仅作补充；没有读取画面之间的内容。'}
    from faster_whisper import WhisperModel
    cache = private_dir(home() / 'models')
    model = WhisperModel(a.model, device='cpu', compute_type='int8', download_root=str(cache))
    rows, info = model.transcribe(source, language=None, vad_filter=True, beam_size=5)
    segments = [{'start': float(s.start), 'end': float(s.end), 'text': s.text.strip()}
                for s in rows if s.text.strip()]
    if abs(info.duration-a.duration) > max(5, a.duration*0.02):
        raise Problem('audio_duration_mismatch', 'Whisper 实际处理时长与目标分 P 不一致。')
    return {'source': 'whisper', 'model': a.model, 'language': info.language,
            'audio_processed_full': True, 'processed_seconds': info.duration,
            'scope': 'full_audio', 'segments': segments}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for k in ('bvid', 'mode', 'model', 'work', 'result'):
        p.add_argument('--' + k, required=True)
    p.add_argument('--page', type=int, required=True)
    p.add_argument('--duration', type=float, required=True)
    p.add_argument('--count', type=int, default=9)
    p.add_argument('--output')
    args = p.parse_args()
    try:
        payload, code = {'ok': True, 'data': execute(args)}, 0
    except Problem as e:
        payload, code = {'ok': False, 'code': e.code, 'message': e.message}, 1
    except Exception:
        payload, code = {'ok': False, 'code': 'media_failed',
                         'message': '媒体下载或 Whisper 处理失败。检查平台访问、本地依赖及模型下载网络；不自动重试。'}, 1
    Path(args.result).write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    sys.exit(code)
