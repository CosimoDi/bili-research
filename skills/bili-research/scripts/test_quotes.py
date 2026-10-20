"""Quote fidelity and diary rendering tests using synthetic material only."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bili_core import engine, report
from bili_core.common import Problem


class QuoteTest(unittest.TestCase):
    def setUp(self):
        self.mood = {'label': '平静、好奇', 'intensity': 2}
        self.evidence = {
            'video': {'title': '测试视频', 'author': '测试作者'},
            'transcripts': [{'source': 'subtitle', 'part': {'page': 1},
                             'coverage': {'span_ratio': 1}, 'segments': [
                {'id': 't:p1:1', 'text': '先试一周。', 'start': 10, 'end': 12},
                {'id': 't:p1:2', 'text': '再看是否适合自己。', 'start': 12, 'end': 15},
                {'id': 't:p1:3', 'text': '也可以暂时不参加。', 'start': 16, 'end': 18}]}],
            'comments': {'items': [{'id': 'c:1', 'text': '试过才发现，我需要留时间休息。'},
                                   {'id': 'c:2', 'text': '我的课程安排不同。'}]},
            'interpretation_boundary': '独立测试材料'}
        self.note = {'summary': '测试讨论如何尝试校园活动。',
                     'quotes': [{'text': '先试一周。', 'evidence_ids': ['t:p1:1'],
                                 'commentary': '一周让我觉得可以尝试，但我要先看课程有没有空档。'},
                                {'text': '我需要留时间休息。', 'evidence_ids': ['c:1'],
                                 'commentary': '这提醒我还要考虑体力，报名多不代表能坚持。'}],
                     'observations': [{'claim': '视频建议短期尝试。', 'evidence_ids': ['t:p1:1']},
                                      {'claim': '评论补充休息成本。', 'evidence_ids': ['c:1']}],
                     'reflection': '我想先找一个活动试试，再根据体验调整。',
                     'mood_before': self.mood, 'mood_after': self.mood, 'mood_reason': '仍然好奇。',
                     'questions': [], 'next_interests': [], 'uncertainties': []}

    def check(self):
        return engine.validate_diary(self.note, self.evidence, self.mood)

    def test_exact_quote_has_derived_provenance(self):
        result = self.check()
        self.assertEqual(result[0]['source']['start'], 10)
        self.assertEqual(result[0]['source']['page'], 1)
        self.assertEqual(result[1]['source']['comment_id'], 'c:1')
        self.assertNotIn('source', self.note['quotes'][0])
        self.evidence['transcripts'][0]['source'] = 'whisper'
        self.assertIn('识别误差', self.check()[0]['source']['label'])

    def test_contiguous_segments_and_line_wrapping(self):
        self.note['quotes'][0].update(text='试一周。\n再看是否适合', evidence_ids=['t:p1:1', 't:p1:2'])
        result = self.check()
        self.assertEqual(result[0]['source']['end'], 15)

    def test_reworded_or_spliced_quote_rejected(self):
        for text in ('先试一个月。', '先试…一周。', '先试一周！'):
            self.note['quotes'][0]['text'] = text
            with self.assertRaises(Problem) as error:
                self.check()
            self.assertEqual(error.exception.code, 'quote_text_mismatch')

    def test_nonadjacent_reversed_or_mixed_sources_rejected(self):
        for ids in (['t:p1:1', 't:p1:3'], ['t:p1:2', 't:p1:1'], ['t:p1:1', 'c:1'], ['c:1', 'c:2']):
            self.note['quotes'][0]['evidence_ids'] = ids
            with self.assertRaises(Problem) as error:
                self.check()
            self.assertEqual(error.exception.code, 'invalid_quote_reference')

    def test_unknown_id_and_padding_citations_rejected(self):
        self.note['quotes'][0]['evidence_ids'] = ['t:p1:999']
        with self.assertRaises(Problem):
            self.check()
        self.note['quotes'][0]['evidence_ids'] = ['t:p1:1', 't:p1:2']
        with self.assertRaises(Problem) as error:
            self.check()
        self.assertEqual(error.exception.code, 'quote_text_mismatch')

    def test_summary_only_and_empty_commentary_rejected(self):
        note = copy.deepcopy(self.note)
        del self.note['quotes']
        with self.assertRaises(Problem):
            self.check()
        self.note = note
        self.note['quotes'][0]['commentary'] = ' '
        with self.assertRaises(Problem):
            self.check()

    def test_comment_quote_required_only_when_comments_exist(self):
        self.note['quotes'] = self.note['quotes'][:1]
        with self.assertRaises(Problem) as error:
            self.check()
        self.assertEqual(error.exception.code, 'missing_comment_quote')
        self.evidence['comments']['items'] = []
        self.note['observations'] = self.note['observations'][:1]
        self.assertEqual(len(self.check()), 1)

    def test_transcript_quote_required(self):
        self.note['quotes'] = self.note['quotes'][1:]
        with self.assertRaises(Problem) as error:
            self.check()
        self.assertEqual(error.exception.code, 'missing_transcript_quote')

    def test_duplicate_quote_rejected(self):
        self.note['quotes'].append(copy.deepcopy(self.note['quotes'][0]))
        with self.assertRaises(Problem) as error:
            self.check()
        self.assertEqual(error.exception.code, 'duplicate_quote')

    def test_quote_rendering_escapes_text_and_keeps_old_diaries_readable(self):
        quotes = self.check()
        quotes[0]['text'] = '<script>alert(1)</script>'
        quotes[0]['commentary'] = '<b>点评</b>'
        rendered = report.quote_cards({'quotes': quotes})
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('&lt;b&gt;点评&lt;/b&gt;', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('P1 · 00:10', rendered)
        self.assertEqual(report.quote_cards({}), '')

    def test_commit_rejects_fabrication_without_advancing_and_saves_valid_quotes(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'BILI_RESEARCH_HOME': root}):
            task = engine.create('独立测试', 1, '模拟学生', '', {})['task']
            with engine.connect(task) as db:
                db.execute('INSERT INTO videos(bvid,status,evidence) VALUES(?,?,?)',
                           ('BV1234567890', 'prepared', engine.dump(self.evidence)))
            bad = copy.deepcopy(self.note)
            bad['quotes'][0]['text'] = '不存在的原话'
            with self.assertRaises(Problem):
                engine.commit_diary(task, bad)
            self.assertEqual(engine.status(task)['completed'], 0)
            saved = engine.commit_diary(task, self.note)
            self.assertEqual(saved['completed'], 1)
            self.assertTrue(saved['report']['ready'])
            with engine.connect(task) as db:
                diary = engine.snapshot(db)['diaries'][0]
            self.assertEqual(diary['quotes'][0]['source']['start'], 10)
            page = Path(saved['report']['path']).read_text()
            self.assertIn('<blockquote>先试一周。</blockquote>', page)
            self.assertIn('报名多不代表能坚持', page)


if __name__ == '__main__':
    unittest.main()
