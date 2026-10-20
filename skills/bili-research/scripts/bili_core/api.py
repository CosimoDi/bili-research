"""Read-only API adapter.

WBI signing adapted from Alterssss/dsh-bili-whale (MIT, 2026 ALTERSSSS).
Subtitle selection follows c1overzz/dsh-bili-scroll's vendored bilibili-mcp
(MIT, 2026 AGI_Ananas). Full upstream notices ship in licenses/.
"""
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .common import Problem, credentials

MIXIN = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52]
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sign(params, image_key, sub_key, now=None):
    key = ''.join((image_key + sub_key)[i] for i in MIXIN)[:32]
    p = dict(params, wts=int(time.time() if now is None else now))
    query = urllib.parse.urlencode([(k, re.sub(r"[!'()*]", '', str(p[k]))) for k in sorted(p)], quote_via=urllib.parse.quote)
    return query + '&w_rid=' + hashlib.md5((query + key).encode()).hexdigest()


class Client:
    def __init__(self):
        c = credentials()
        self.cookie = '; '.join(k + '=' + v for k, v in c.items() if k in ('SESSDATA', 'bili_jct', 'buvid3') and v)
        self.last_request = 0
        self.nav_data = None

    def fetch_json(self, url, authenticated=True):
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or '').lower()
        allowed = any(host == d or host.endswith('.' + d) for d in ('bilibili.com', 'hdslb.com', 'bilivideo.com'))
        if parsed.scheme != 'https' or not allowed:
            raise Problem('unexpected_source', '拒绝读取非预期来源的字幕链接。')
        time.sleep(max(0, 0.65 - (time.monotonic() - self.last_request)))
        headers = {'User-Agent': UA, 'Referer': 'https://www.bilibili.com/'}
        # Never send account cookies to subtitle CDNs.
        if authenticated and host == 'api.bilibili.com':
            headers['Cookie'] = self.cookie
        request = urllib.request.Request(url, headers=headers, method='GET')
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=35) as r:
                if r.geturl() != url:
                    raise Problem('unexpected_redirect', '接口发生重定向，停止读取。')
                body = r.read(16 * 1024 * 1024 + 1)
            if len(body) > 16 * 1024 * 1024:
                raise Problem('response_too_large', '接口返回超出单次读取上限。')
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except urllib.error.HTTPError as e:
            code = 'platform_blocked' if e.code in (403, 412, 429) else 'network_error'
            raise Problem(code, 'B 站请求失败（HTTP %s）；停止本次请求，不自动绕过或反复重试。' % e.code)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            raise Problem('network_error', '接口不可达或未返回有效 JSON；检查网络后再继续。')
        finally:
            self.last_request = time.monotonic()

    def api(self, endpoint, params=None, signed=False):
        if signed:
            nav = self.nav()
            try:
                keys = [nav['wbi_img'][k].rsplit('/', 1)[-1].split('.')[0] for k in ('img_url', 'sub_url')]
                query = sign(params or {}, *keys)
            except (KeyError, IndexError):
                raise Problem('api_changed', 'WBI 签名字段发生变化，需要更新适配器。')
        else:
            query = urllib.parse.urlencode(params or {})
        raw = self.fetch_json('https://api.bilibili.com' + endpoint + ('?' + query if query else ''))
        code = raw.get('code')
        if code != 0:
            if code in (-101, -111):
                raise Problem('login_required', 'B 站登录状态失效，请在本机更新凭据。')
            if code in (-352, -412, -509, -401, -403):
                raise Problem('platform_blocked', 'B 站风控或限流（code=%s）；停止任务，等待用户处理。' % code)
            if code == 12002:
                raise Problem('comments_closed', '该视频已关闭评论。')
            raise Problem('api_error', 'B 站接口返回 code=%s；不把失败当成空结果。' % code)
        return raw.get('data') or {}

    def nav(self):
        if self.nav_data is None:
            self.nav_data = self.api('/x/web-interface/nav')
            if not self.nav_data.get('isLogin'):
                raise Problem('login_required', 'B 站账号未登录，请更新本地凭据。')
        return self.nav_data

    def search(self, query, limit=20, pages=3):
        self.nav()
        found, seen = [], set()
        for page in range(1, pages + 1):
            data = self.api('/x/web-interface/wbi/search/type',
                            {'search_type': 'video', 'keyword': query, 'page': page, 'order': 'totalrank'}, signed=True)
            rows = data.get('result') or []
            for row in rows:
                bv = row.get('bvid')
                if not bv or bv in seen:
                    continue
                seen.add(bv)
                found.append({'bvid': bv, 'title': html.unescape(re.sub('<[^>]*>', '', row.get('title', ''))),
                              'author': row.get('author'), 'description': row.get('description', ''),
                              'duration': row.get('duration'), 'published_at': row.get('pubdate'),
                              'url': 'https://www.bilibili.com/video/' + bv})
                if len(found) >= limit:
                    return found
            if not rows:
                break
        return found

    def video(self, bv):
        self.nav()
        d = self.api('/x/web-interface/view', {'bvid': bv})
        pages = d.get('pages') or []
        if not pages:
            raise Problem('unavailable_video', '无法获得视频分 P 信息。')
        return {'bvid': bv, 'aid': d['aid'], 'title': d['title'], 'author': d['owner']['name'],
                'description': d.get('desc', ''), 'duration': sum(p.get('duration', 0) for p in pages),
                'cover': d.get('pic'), 'published_at': d.get('pubdate'),
                'url': 'https://www.bilibili.com/video/' + bv,
                'parts': [{'page': p['page'], 'cid': p['cid'], 'title': p.get('part', ''),
                           'duration': p.get('duration', 0)} for p in pages]}

    def subtitles(self, bv, part):
        d = self.api('/x/player/wbi/v2', {'bvid': bv, 'cid': part['cid']}, signed=True)
        tracks = d.get('subtitle', {}).get('subtitles') or []
        if not tracks:
            return None
        preferred = sorted(tracks, key=lambda t: {'zh-CN': 0, 'zh': 0, 'ai-zh': 1}.get(t.get('lan'), 2))[0]
        url = preferred['subtitle_url']
        url = 'https:' + url if url.startswith('//') else url
        raw = self.fetch_json(url, authenticated=False)
        rows = raw.get('body')
        if not isinstance(rows, list):
            raise Problem('api_changed', '字幕数据缺少 body；不能视为无字幕。')
        segs = [{'start': float(s['from']), 'end': float(s['to']), 'text': str(s['content'])}
                for s in rows if str(s.get('content', '')).strip()]
        return {'source': 'subtitle', 'language': preferred.get('lan'), 'segments': segs,
                'scope': 'entire_available_track', 'audio_processed_full': False}

    @staticmethod
    def comment(row, parent=None, order='hot'):
        # Deliberately exclude account UID, avatar and other irrelevant user metadata.
        return {'id': 'c:' + str(row['rpid']), 'parent': parent, 'order': order,
                'text': row.get('content', {}).get('message', ''), 'likes': row.get('like', 0),
                'created_at': row.get('ctime'), 'reply_total': row.get('rcount', 0)}

    def comments(self, aid, count=30, threads=3, replies=10):
        items, seen, totals, roots = [], set(), [], []
        for sort, label, budget in ((2, 'hot', (count + 1) // 2), (0, 'recent', count // 2)):
            taken, page = 0, 1
            while taken < budget:
                try:
                    data = self.api('/x/v2/reply', {'type': 1, 'oid': aid, 'sort': sort, 'pn': page, 'ps': 20})
                except Problem as e:
                    if e.code == 'comments_closed':
                        return {'status': 'closed', 'items': [], 'scope': 'comments_disabled', 'available_total': 0}
                    raise
                if 'page' not in data:
                    raise Problem('api_changed', '评论接口缺少分页信息；无法确认评论是否为空。')
                totals.append(data['page'].get('count', 0))
                rows = data.get('replies') or []
                for row in rows[:budget-taken]:
                    taken += 1
                    if row['rpid'] not in seen:
                        seen.add(row['rpid'])
                        item = self.comment(row, order=label)
                        items.append(item)
                        if item['reply_total'] and len(roots) < threads:
                            roots.append(row['rpid'])
                if not rows or page * 20 >= max(totals or [0]):
                    break
                page += 1
        for root in roots:
            data = self.api('/x/v2/reply/reply', {'type': 1, 'oid': aid, 'root': root, 'pn': 1, 'ps': replies})
            for row in (data.get('replies') or [])[:replies]:
                if row['rpid'] not in seen:
                    seen.add(row['rpid'])
                    items.append(self.comment(row, parent='c:' + str(root), order='thread'))
        if max(totals or [0]) > 0 and not items:
            raise Problem('comments_unavailable', '接口报告存在评论但未返回样本，不能计为已读取评论。')
        return {'status': 'ok', 'items': items, 'available_total': max(totals or [0]),
                'scope': 'sample_hot_recent_and_threads', 'requested_top_level': count,
                'requested_threads': threads, 'requested_replies_per_thread': replies,
                'warning': '评论为有偏样本，去重后数量可能减少；未读取全部评论或所有楼中楼。'}
