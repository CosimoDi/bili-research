"""Transactional task state, complete delivery receipts, append-only diaries.

Receipts verify delivery and acknowledgement, not a model's comprehension.
Every next video starts with all earlier diaries, paged without truncation.
"""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from .common import Problem, bvid, home, integer, private_dir, write_json
from .media import prepare, run_worker
from .report import write_report


def dump(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, allow_nan=False)


def now():
    return datetime.now(timezone.utc).isoformat()


def task_dir(task):
    if len(task) != 32 or any(c not in '0123456789abcdef' for c in task):
        raise Problem('invalid_task', '任务 ID 格式不正确。')
    return home() / 'tasks' / task


@contextmanager
def connect(task):
    p = task_dir(task) / 'task.sqlite'
    if not p.exists():
        raise Problem('task_missing', '任务不存在。')
    db = sqlite3.connect(str(p), timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except sqlite3.OperationalError:
        db.rollback()
        raise Problem('task_busy_or_storage_error', '任务被其他进程占用或存储不可用；未推进计数，请稍后重试。')
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def meta(db):
    return json.loads(db.execute('SELECT data FROM meta').fetchone()[0])


def create(goal, target, persona, followup, options):
    integer(target, 1, 1000, '观看数量')
    if not goal.strip() or len(goal) > 4000 or not persona.strip() or len(persona) > 8000 or len(followup) > 4000:
        raise Problem('invalid_task_input', '需要研究目标与模拟用户描述；目标/后续指令各限 4000 字，画像限 8000 字。')
    tid = uuid.uuid4().hex
    directory = private_dir(task_dir(tid))
    db = sqlite3.connect(str(directory / 'task.sqlite'))
    try:
        db.executescript('''
        CREATE TABLE meta(data TEXT NOT NULL);
        CREATE TABLE videos(id INTEGER PRIMARY KEY, bvid TEXT UNIQUE NOT NULL,
                            status TEXT NOT NULL DEFAULT 'queued', evidence TEXT, reason TEXT);
        CREATE TABLE packets(id INTEGER PRIMARY KEY, video_id INTEGER REFERENCES videos(id),
                             kind TEXT NOT NULL, body TEXT NOT NULL, receipt TEXT UNIQUE NOT NULL,
                             delivered INTEGER NOT NULL DEFAULT 0, reviewed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE diaries(seq INTEGER PRIMARY KEY, video_id INTEGER UNIQUE REFERENCES videos(id),
                             data TEXT NOT NULL, created TEXT NOT NULL);
        ''')
        db.execute('INSERT INTO meta VALUES(?)', (dump({'id': tid, 'goal': goal, 'target': target, 'persona': persona,
                   'followup': followup, 'options': options, 'created': now(),
                   'initial_mood': {'label': '平静、好奇', 'intensity': 2}, 'version': 1}),))
        db.commit()
    finally:
        db.close()
    return {'task': tid, 'target': target, 'state_dir': str(directory), 'next_action': 'discover_or_enqueue', 'report': refresh_report(tid)}


def overview(db):
    m = meta(db)
    counts = {r[0]: r[1] for r in db.execute('SELECT status,count(*) FROM videos GROUP BY status')}
    completed = db.execute('SELECT count(*) FROM diaries').fetchone()[0]
    return {'task': m['id'], 'target': m['target'], 'completed': completed,
            'remaining': max(0, m['target']-completed), 'counts': counts,
            'phase': 'ready_for_followup' if completed >= m['target'] else 'watching',
            'options': m['options']}


def status(task):
    with connect(task) as db:
        return dict(overview(db), videos=[dict(r) for r in db.execute('SELECT bvid,status,reason FROM videos ORDER BY id')])


def enqueue(task, values):
    videos = list(dict.fromkeys(bvid(v) for v in values))
    with connect(task) as db:
        added = 0
        for bv in videos:
            added += db.execute('INSERT OR IGNORE INTO videos(bvid) VALUES(?)', (bv,)).rowcount
        return dict(overview(db), added=added)


def text_packets(kind, value, limit=12000):
    """JSON text fragments, always complete when concatenated in order."""
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    parts = [text[i:i+limit] for i in range(0, len(text), limit)]
    return [(kind, {'fragment': i+1, 'fragments': len(parts), 'format': 'json_text_fragment', 'text': p})
            for i, p in enumerate(parts)]


def build_packets(db, video_id, evidence):
    packets = []
    for r in db.execute('SELECT seq,data,created FROM diaries ORDER BY seq'):
        packets += text_packets('prior_diary', {'sequence': r['seq'], 'created': r['created'], 'diary': json.loads(r['data'])})
    packets += text_packets('video_metadata', evidence['video'])
    for t in evidence['transcripts']:
        packets += text_packets('transcript', t)
    packets += text_packets('comments', evidence['comments'])
    for kind, body in packets:
        receipt = hashlib.sha256((uuid.uuid4().hex + dump(body)).encode()).hexdigest()
        db.execute('INSERT INTO packets(video_id,kind,body,receipt) VALUES(?,?,?,?)',
                   (video_id, kind, dump(body), receipt))


def current(db):
    return db.execute("SELECT * FROM videos WHERE status IN ('queued','prepared') ORDER BY id LIMIT 1").fetchone()


def previous_mood(db):
    d = db.execute('SELECT data FROM diaries ORDER BY seq DESC LIMIT 1').fetchone()
    return json.loads(d[0])['mood_after'] if d else meta(db)['initial_mood']


def next_packet(task, client_factory):
    with connect(task) as db:
        state, m = overview(db), meta(db)
        if not state['remaining']:
            return dict(state, goal=m['goal'], followup=m['followup'], next_action='export_then_follow_user_instruction',
                        qualification='模拟用户视角；没有真实用户研究的代表性。')
        row = current(db)
        if not row:
            return dict(state, next_action='discover_or_enqueue_more', message='候选不足；不得把跳过项计入已完成。')
        if row['status'] == 'queued':
            evidence = prepare(client_factory(), row['bvid'], m['options'])
            db.execute("UPDATE videos SET status='prepared',evidence=? WHERE id=?", (dump(evidence), row['id']))
            build_packets(db, row['id'], evidence)
        else:
            evidence = json.loads(row['evidence'])
        packet = db.execute('SELECT * FROM packets WHERE video_id=? AND reviewed=0 ORDER BY id LIMIT 1', (row['id'],)).fetchone()
        base = dict(state, bvid=row['bvid'], goal=m['goal'], persona=m['persona'], followup=m['followup'],
                    mood_before=previous_mood(db), boundary=evidence['interpretation_boundary'])
        if not packet:
            return dict(base, next_action='write_diary', diary_schema='references/protocol.md',
                        evidence_ids=[s['id'] for t in evidence['transcripts'] for s in t['segments']] +
                        [c['id'] for c in evidence['comments']['items']] + [f['id'] for f in evidence.get('frames', [])])
        db.execute('UPDATE packets SET delivered=1 WHERE id=?', (packet['id'],))
        return dict(base, next_action='read_then_ack', packet={'kind': packet['kind'], **json.loads(packet['body'])},
                    receipt=packet['receipt'], untrusted_material=True,
                    packets_left=db.execute('SELECT count(*) FROM packets WHERE video_id=? AND reviewed=0', (row['id'],)).fetchone()[0])


def ack(task, receipt):
    with connect(task) as db:
        row = current(db)
        p = db.execute('SELECT * FROM packets WHERE receipt=?', (receipt,)).fetchone()
        if not p or not row or p['video_id'] != row['id'] or not p['delivered']:
            raise Problem('invalid_receipt', '回执不属于当前已交付材料。')
        if p['reviewed']:
            return {'acknowledged': True, 'duplicate': True}
        first = db.execute('SELECT id FROM packets WHERE video_id=? AND reviewed=0 ORDER BY id LIMIT 1', (row['id'],)).fetchone()
        if first[0] != p['id']:
            raise Problem('out_of_order', '请按顺序阅读材料并回执。')
        db.execute('UPDATE packets SET reviewed=1 WHERE id=?', (p['id'],))
        return {'acknowledged': True, 'next_action': 'next'}


def nonempty(value, label, maxlen=10000):
    if not isinstance(value, str) or not value.strip() or len(value) > maxlen:
        raise Problem('invalid_diary', '%s 必须是非空文字，且不超过 %s 字。' % (label, maxlen))


def validate_quotes(quotes, evidence):
    if not isinstance(quotes, list) or not 1 <= len(quotes) <= 6:
        raise Problem('invalid_quotes', 'quotes 需要 1–6 条原文摘录及逐条点评。')
    sources = {}
    for track_index, track in enumerate(evidence['transcripts']):
        for index, segment in enumerate(track['segments']):
            sources[segment['id']] = ('transcript', track_index, index, segment, track)
    for comment in evidence['comments']['items']:
        sources[comment['id']] = ('comment', None, None, comment, None)
    resolved, kinds, seen = [], set(), set()
    total = 0
    compact = lambda text: ''.join(text.split())
    for item in quotes:
        if not isinstance(item, dict) or set(item) != {'text', 'evidence_ids', 'commentary'}:
            raise Problem('invalid_quotes', '每条摘录需要 text、evidence_ids 和 commentary。')
        nonempty(item['text'], '摘录原文', 160)
        nonempty(item['commentary'], '摘录点评', 3000)
        ids = item['evidence_ids']
        if (not isinstance(ids, list) or not ids or
                any(not isinstance(key, str) or key not in sources for key in ids) or len(set(ids)) != len(ids)):
            raise Problem('invalid_quote_reference', '摘录须引用本视频的文字或评论材料 ID，不能引用图片。')
        rows = [sources[key] for key in ids]
        kind, track_index, index, first, track = rows[0]
        if kind == 'comment':
            if len(rows) != 1:
                raise Problem('invalid_quote_reference', '一条评论摘录只能对应一条评论。')
            source = {'kind': 'comment', 'label': '评论摘录', 'comment_id': ids[0]}
        else:
            if any(row[0] != kind or row[1] != track_index or row[2] != index + offset
                   for offset, row in enumerate(rows)):
                raise Problem('invalid_quote_reference', '跨字幕段摘录须按顺序引用同一分 P 的连续片段。')
            part = track['part']
            source = {'kind': 'transcript', 'track_source': track['source'],
                      'label': '语音转写摘录（可能有识别误差）' if track['source'] == 'whisper' else '字幕摘录（未核对原音）',
                      'page': part.get('page', 1) if isinstance(part, dict) else part,
                      'start': first['start'], 'end': rows[-1][3]['end']}
        texts = [compact(row[3]['text']) for row in rows]
        quote = compact(item['text'])
        full = ''.join(texts)
        # Whitespace changes from subtitle line wrapping are harmless. Wording and
        # punctuation must remain exact; a span must actually cover every cited segment.
        positions = [pos for pos in range(len(full)) if full.startswith(quote, pos)]
        if not any(pos < len(texts[0]) and pos + len(quote) > len(full) - len(texts[-1]) for pos in positions):
            raise Problem('quote_text_mismatch', '摘录与引用原文不一致；保留原字词和标点，不拼接省略的片段。')
        identity = (tuple(ids), quote)
        if identity in seen:
            raise Problem('duplicate_quote', '同一摘录不能重复提交。')
        seen.add(identity)
        total += len(item['text'])
        kinds.add(kind)
        resolved.append(dict(item, source=source))
    if total > 480:
        raise Problem('quotes_too_long', '原文摘录合计最多 480 字；请缩短引用并把重点写在点评中。')
    if 'transcript' not in kinds:
        raise Problem('missing_transcript_quote', '至少摘录一处视频文字并点评。')
    if evidence['comments']['items'] and 'comment' not in kinds:
        raise Problem('missing_comment_quote', '已获取评论样本，至少摘录一条评论中的原话并点评。')
    return resolved


def validate_diary(note, evidence, mood):
    fields = {'summary', 'quotes', 'observations', 'reflection', 'mood_before', 'mood_after', 'mood_reason',
              'questions', 'next_interests', 'uncertainties'}
    if not isinstance(note, dict) or set(note) != fields:
        raise Problem('invalid_diary', '日记字段须与 references/protocol.md 一致。')
    if len(dump(note)) > 30000:
        raise Problem('invalid_diary', '单条日记超过 30000 字；请保留有依据的关键变化。')
    for field in ('summary', 'reflection', 'mood_reason'):
        nonempty(note[field], field)
    for field in ('questions', 'next_interests', 'uncertainties'):
        if not isinstance(note[field], list) or any(not isinstance(s, str) for s in note[field]):
            raise Problem('invalid_diary', field + ' 必须是文字数组。')
    for field in ('mood_before', 'mood_after'):
        value = note[field]
        if not isinstance(value, dict) or set(value) != {'label', 'intensity'}:
            raise Problem('invalid_diary', field + ' 需要 label 与 intensity。')
        nonempty(value['label'], field, 300)
        integer(value['intensity'], 0, 5, field + '.intensity')
    if note['mood_before'] != mood:
        raise Problem('mood_discontinuity', 'mood_before 必须承接上一条日记或任务初始状态。')
    valid = {s['id'] for t in evidence['transcripts'] for s in t['segments']}
    comment_ids = {c['id'] for c in evidence['comments']['items']}
    valid |= comment_ids | {f['id'] for f in evidence.get('frames', [])}
    observations, cited = note['observations'], set()
    if not isinstance(observations, list) or not observations:
        raise Problem('invalid_diary', 'observations 至少包含一条带材料引用的观察。')
    for item in observations:
        if not isinstance(item, dict) or set(item) != {'claim', 'evidence_ids'}:
            raise Problem('invalid_diary', '每条观察需要 claim 与 evidence_ids。')
        nonempty(item['claim'], 'claim')
        ids = item['evidence_ids']
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or x not in valid for x in ids):
            raise Problem('invalid_evidence_reference', '观察引用了当前视频不存在的材料 ID。')
        cited.update(ids)
    if not any(x.startswith('t:') for x in cited):
        raise Problem('missing_transcript_reference', '日记需要引用视频文字材料。')
    if comment_ids and not (cited & comment_ids):
        raise Problem('missing_comment_reference', '已获取评论样本，日记须包含对评论的有依据观察。')
    return validate_quotes(note['quotes'], evidence)


def commit_diary(task, note):
    with connect(task) as db:
        state = overview(db)
        if not state['remaining']:
            raise Problem('target_reached', '已达到目标数量；请进入后续研究。')
        row = current(db)
        if not row or row['status'] != 'prepared':
            raise Problem('no_video_ready', '当前没有已准备的视频。')
        if db.execute('SELECT count(*) FROM packets WHERE video_id=? AND reviewed=0', (row['id'],)).fetchone()[0]:
            raise Problem('unread_material', '尚有日记或视频/评论材料未读取确认，不能完成这条视频。')
        evidence = json.loads(row['evidence'])
        quotes = validate_diary(note, evidence, previous_mood(db))
        record = dict(note, quotes=quotes, bvid=row['bvid'], video=evidence['video'],
                      material_boundary=evidence['interpretation_boundary'],
                      comment_scope={k: v for k, v in evidence['comments'].items() if k != 'items'},
                      transcript_coverage=[{'part': t['part'], 'source': t['source'], 'coverage': t['coverage']} for t in evidence['transcripts']])
        db.execute('INSERT INTO diaries(video_id,data,created) VALUES(?,?,?)', (row['id'], dump(record), now()))
        db.execute("UPDATE videos SET status='done' WHERE id=?", (row['id'],))
        result = dict(overview(db), journal_saved=True, next_action='next')
    # Rendering failures must never make a committed diary appear unsaved.
    result['report'] = refresh_report(task)
    return result


def skip(task, reason):
    nonempty(reason, '跳过原因', 1000)
    with connect(task) as db:
        row = current(db)
        if not row:
            raise Problem('no_current_video', '当前没有可跳过的视频。')
        db.execute("UPDATE videos SET status='skipped',reason=? WHERE id=?", (reason, row['id']))
        return dict(overview(db), skipped=row['bvid'])


def set_transcript(task, mode):
    if mode not in ('auto', 'whisper-first', 'subtitle-only'):
        raise Problem('invalid_argument', '无效的转写模式。')
    with connect(task) as db:
        m = meta(db)
        m['options']['transcript'] = mode
        db.execute('UPDATE meta SET data=?', (dump(m),))
        return dict(overview(db), message='仅影响尚未准备的视频。')


def frames(task, page, count):
    integer(count, 1, 16, '抽帧数量')
    with connect(task) as db:
        row = current(db)
        if not row or row['status'] != 'prepared':
            raise Problem('no_video_ready', '先用 next 准备当前视频文字材料。')
        data = json.loads(row['evidence'])
        part = next((p for p in data['video']['parts'] if p['page'] == page), None)
        if not part:
            raise Problem('invalid_part', '分 P 不存在。')
        if any(f['id'].startswith('v:p%s:' % page) for f in data.get('frames', [])):
            raise Problem('frames_exist', '此分 P 已有抽帧；请读取已有图像材料。')
        result = run_worker(row['bvid'], part, mode='frames', count=count,
                            output=task_dir(task) / 'frames' / 'output.jpg')
        data.setdefault('frames', []).extend(result['frames'])
        db.execute('UPDATE videos SET evidence=? WHERE id=?', (dump(data), row['id']))
        for kind, body in text_packets('images_open_with_host_image_tool', result):
            db.execute('INSERT INTO packets(video_id,kind,body,receipt) VALUES(?,?,?,?)',
                       (row['id'], kind, dump(body), uuid.uuid4().hex))
        return {'next_action': 'next', 'images_added': len(result['frames'])}


def snapshot(db):
    return {'task': meta(db), 'status': overview(db),
            'diaries': [json.loads(r[0]) for r in db.execute('SELECT data FROM diaries ORDER BY seq')],
            'videos': [dict(r) for r in db.execute('SELECT bvid,status,reason FROM videos ORDER BY id')],
            'qualification': '模拟用户学习记录；未验证真实用户反应，不能代表市场。'}


def refresh_report(task):
    path = task_dir(task) / 'journal.html'
    try:
        # Keep snapshot and projection serialized with other task writes.
        with connect(task) as db:
            return write_report(path, snapshot(db))
    except Exception:
        return {'ready': False, 'error': 'report_generation_failed',
                'message': '任务与已保存日记保留；请用 report 命令重新生成网页，无需重写日记。',
                'retry_command': 'report --task ' + task}


def export(task):
    with connect(task) as db:
        data = snapshot(db)
        p = task_dir(task) / 'export.json'
        write_json(p, data)
    return {'path': str(p), 'status': data['status'], 'followup': data['task']['followup'],
            'report': refresh_report(task),
            'next_action': 'read_export_and_continue' if not data['status']['remaining'] else 'continue_or_report_partial'}
