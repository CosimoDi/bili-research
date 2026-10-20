"""Offline HTML projection of saved diaries; no model-generated markup."""
import html
import base64
import hashlib
import os
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


LIVE_SCRIPT = '''(() => {
  if (!/^https?:$/.test(location.protocol)) return;
  let previous = '';
  async function update() {
    try {
      const response = await fetch(location.href, {cache: 'no-store'});
      if (!response.ok) return;
      const source = await response.text();
      if (source === previous) return;
      previous = source;
      const next = new DOMParser().parseFromString(source, 'text/html');
      const opened = [...document.querySelectorAll('article details[open]')]
        .map(el => el.closest('article').id);
      const [x, y] = [scrollX, scrollY];
      for (const tag of ['header', 'main', 'footer']) {
        const current = document.querySelector(tag), replacement = next.querySelector(tag);
        if (current && replacement && current.outerHTML !== replacement.outerHTML)
          current.replaceWith(replacement);
      }
      for (const id of opened) {
        const detail = document.getElementById(id)?.querySelector('details');
        if (detail) detail.open = true;
      }
      window.scrollTo({left: x, top: y, behavior: 'instant'});
    } catch (_) { /* Keep the last readable diary if the local service stops. */ }
    finally { setTimeout(update, 3000); }
  }
  setTimeout(update, 3000);
})();'''
SCRIPT_HASH = base64.b64encode(hashlib.sha256(LIVE_SCRIPT.encode()).digest()).decode()
CSP = ("default-src 'none'; style-src 'unsafe-inline'; connect-src 'self'; "
       "script-src 'sha256-%s'; base-uri 'none'; form-action 'none'" % SCRIPT_HASH)


def esc(value):
    return html.escape(str(value), quote=True)


def paragraph(value, cls=''):
    return '<p class="%s">%s</p>' % (cls, esc(value))


def items(values):
    return '<ul>' + ''.join('<li>%s</li>' % esc(v) for v in values) + '</ul>' if values else '<p class="muted">暂无</p>'


def mood(value):
    return '%s · %s/5' % (value['label'], value['intensity'])


def quote_cards(diary):
    blocks = []
    for item in diary.get('quotes', []):
        source = item['source']
        label = source['label']
        if source['kind'] == 'transcript':
            seconds = max(0, int(source['start']))
            label += ' · P%s · %02d:%02d' % (source['page'], seconds // 60, seconds % 60)
        else:
            label += ' · ' + source['comment_id']
        blocks.append('<section class="quote-note"><blockquote>%s</blockquote><p class="muted">%s</p>'
                      '<p class="quote-comment"><strong>我的点评</strong><br>%s</p>'
                      '<small>材料：%s</small></section>' %
                      (esc(item['text']), esc(label), esc(item['commentary']), esc(' · '.join(item['evidence_ids']))))
    return '<h3>让我停下来的几句话</h3>' + ''.join(blocks) if blocks else ''


def render(snapshot):
    task, status, diaries = snapshot['task'], snapshot['status'], snapshot['diaries']
    cards, navigation = [], []
    for i, d in enumerate(diaries, 1):
        video = d['video']
        title = video.get('title', d['bvid'])
        navigation.append('<a href="#entry-%d"><span>%02d</span>%s</a>' % (i, i, esc(title)))
        # Construct platform URLs from validated identifiers, never trust source hrefs.
        bv = d['bvid']
        link = ('<a href="https://www.bilibili.com/video/%s" target="_blank" rel="noopener noreferrer">打开原视频 ↗</a>' % esc(bv)
                if re.fullmatch(r'BV[0-9A-Za-z]{10}', bv) else '')
        observations = ''.join('<li>%s<small>材料：%s</small></li>' % (esc(o['claim']), esc(' · '.join(o['evidence_ids']))) for o in d['observations'])
        coverage = []
        for t in d.get('transcript_coverage', []):
            part = t['part'].get('page', '?') if isinstance(t['part'], dict) else t['part']
            source = {'subtitle': '字幕', 'whisper': 'Whisper 语音转写'}.get(t['source'], '文字轨')
            coverage.append('分 P %s · %s · 文字时间跨度 %.0f%%；%s' % (
                part, source, 100 * t['coverage'].get('span_ratio', 0), t['coverage'].get('warning', '')))

        scope = d.get('comment_scope', {})
        cards.append('''<article id="entry-%(i)s">
<div class="entry-top"><span class="eyebrow">观看日记 / %(num)s</span>%(link)s</div>
<h2>%(title)s</h2><p class="muted">%(author)s · %(bv)s</p>
%(summary)s%(quotes)s<div class="mood"><span>观看前<br><strong>%(before)s</strong></span><b aria-hidden="true">→</b><span>观看后<br><strong>%(after)s</strong></span></div>
%(reason)s<h3>此刻的感悟</h3>%(reflection)s
<h3>视频与评论带来的认识</h3><ul>%(observations)s</ul>
<div class="columns"><section><h3>还在想的问题</h3>%(questions)s</section><section><h3>接下来想了解</h3>%(interests)s</section></div>
<details><summary>证据范围与不确定性</summary>%(uncertainties)s%(boundary)s%(coverage)s%(scope)s</details>
</article>''' % dict(i=i, num='%02d' % i, title=esc(title), author=esc(video.get('author', '')), bv=esc(bv), link=link,
        summary=paragraph(d['summary'], 'lead'), quotes=quote_cards(d), before=esc(mood(d['mood_before'])), after=esc(mood(d['mood_after'])),
        reason=paragraph(d['mood_reason'], 'muted'), reflection=paragraph(d['reflection']), observations=observations,
        questions=items(d['questions']), interests=items(d['next_interests']), uncertainties=items(d['uncertainties']),
        boundary=paragraph(d.get('material_boundary', '')), coverage=items(coverage),
        scope=paragraph('评论已关闭。' if scope.get('status') == 'closed' else '评论来自热评、最新评论及部分楼中楼，仅代表本次读取的样本。', 'muted')))
    empty = '<article class="empty"><h2>第一篇日记正在路上</h2><p>每读完一条视频和评论，这里就会多一篇记录。你可以继续在原会话里向 Agent 下达指令。</p></article>'
    phase = '观看目标已完成' if not status['remaining'] else '连续阅读中'
    return '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="%(csp)s"><title>观看日记 · %(goal)s</title>
<style>
:root{color-scheme:light;--ink:#203a35;--muted:#657770;--line:#dce4de;--accent:#316b58}
.quote-note{margin:16px 0 24px;padding:20px 24px;background:#f5f7f2;border-radius:12px}.quote-note blockquote{margin:0 0 12px;padding-left:16px;border-left:3px solid var(--accent);font-size:18px;white-space:pre-wrap;overflow-wrap:anywhere}.quote-comment{margin-bottom:8px}.quote-comment strong{font-size:13px;color:var(--accent)}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:#f4f5ef;color:var(--ink);font:16px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}header,main,footer{max-width:1160px;margin:auto;padding:40px 32px}header{padding-bottom:24px}h1{font-size:42px;letter-spacing:-1.5px;margin:8px 0 14px}h2{font-size:24px;line-height:1.5;margin:10px 0}h3{font-size:16px;margin:24px 0 8px}p{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 14px}li{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}ul{padding-left:22px}small{display:block;color:var(--muted);font-size:12px;margin-top:4px}.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--accent)}.muted{color:var(--muted);font-size:14px}.lead{font-size:17px}.intro{max-width:780px}.progress-row{display:flex;gap:24px;align-items:center;margin:24px 0 10px}.count{font-size:28px;font-weight:650}.count small{display:inline;font-weight:400;font-size:16px}progress{flex:1;height:9px;accent-color:var(--accent);max-width:520px}main{display:grid;grid-template-columns:250px minmax(0,1fr);gap:32px;padding-top:8px}aside{align-self:start;position:sticky;top:24px}aside h3{margin-top:0}aside a{display:flex;gap:12px;font-size:14px;padding:9px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}aside a span{font-size:12px;color:var(--muted);padding-top:3px}.persona{border-top:1px solid var(--line);padding-top:20px;margin-top:24px}article{background:#fff;border:1px solid var(--line);border-radius:18px;padding:30px 34px;margin-bottom:24px;box-shadow:0 5px 20px #203a3504}.entry-top{display:flex;justify-content:space-between;gap:16px;font-size:12px}.mood{display:flex;gap:24px;align-items:center;background:#edf3ed;border-radius:12px;padding:18px 22px;margin:22px 0 8px;font-size:12px}.mood strong{font-size:16px}.mood b{font-size:22px;font-weight:400}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}details{border-top:1px solid var(--line);margin-top:24px;padding-top:16px;font-size:14px;color:var(--muted)}summary{cursor:pointer}.followup{border-left:3px solid var(--accent);padding:4px 0 4px 20px;margin:28px 0}.empty{padding:48px 34px}footer{font-size:12px;color:var(--muted);padding-top:0}
@media(max-width:760px){header,main,footer{padding:24px 20px}h1{font-size:34px}main{display:block}aside{position:static;margin-bottom:24px}nav{max-height:180px;overflow:auto}.persona{margin-top:16px}article{padding:24px 20px}.columns{grid-template-columns:1fr;gap:0}.mood{gap:14px;padding:14px}.progress-row{gap:12px}.entry-top{flex-wrap:wrap}}
@media print{body{background:#fff}main{display:block}aside{display:none}article{break-inside:avoid;box-shadow:none}header,main{padding:16px}details{display:block}}
</style></head><body><header><div class="eyebrow">BILI RESEARCH / READING JOURNAL</div><h1>看过之后，留下什么。</h1>
<p class="intro lead">%(goal)s</p><div class="progress-row"><span class="count">%(completed)s <small>/ %(target)s 条</small></span><progress value="%(completed)s" max="%(target)s" aria-label="观看进度"></progress><span class="muted">%(phase)s</span></div>
<p class="muted">%(qualification)s</p></header><main><aside><h3>阅读足迹</h3><nav>%(navigation)s</nav><div class="persona"><span class="eyebrow">模拟用户视角</span>%(persona)s</div></aside>
<div>%(cards)s<div class="followup"><h3>接下来，在原会话继续</h3>%(followup)s<p class="muted">这份网页用于阅读日记。继续向原会话中的 Agent 提问、提供作品或调整任务即可。</p></div></div></main>
<footer>本地日记报告 · %(completed)s 篇已保存 · 在线预览每 3 秒同步新日记 · %(created)s</footer><script>%(script)s</script></body></html>''' % dict(csp=esc(CSP), script=LIVE_SCRIPT, goal=esc(task['goal']), completed=status['completed'], target=status['target'], phase=phase,
    qualification=esc(snapshot['qualification']), navigation=''.join(navigation) or '<p class="muted">等待第一条视频</p>',
    persona=paragraph(task['persona']), cards=''.join(cards) or empty, followup=paragraph(task['followup']), created=esc(task['created']))


def write_report(path, snapshot):
    content = render(snapshot)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.report-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'ready': True, 'path': str(path.resolve()), 'url': path.resolve().as_uri(),
            'browser_action': 'open_or_refresh_report', 'completed': snapshot['status']['completed']}


def make_server(path, route, port=0, task=None):
    """Serve exactly one report on loopback; never expose the runtime directory."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(False)

        def do_HEAD(self):
            self.respond(True)

        def respond(self, head):
            if urlsplit(self.path).path != route:
                self.send_error(404)
                return
            try:
                content = path.read_bytes()
            except OSError:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', CSP)
            self.send_header('X-Content-Type-Options', 'nosniff')
            if task:
                self.send_header('X-Bili-Task', task)
            self.end_headers()
            if not head:
                self.wfile.write(content)

        def log_message(self, *args):
            pass
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)
