"""Usage aggregation and the read-only archive health report."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from video_parser.services import ai_settings, archive_health, library, usage_report
from video_parser.web.app import app

NOW = datetime.now(timezone.utc).isoformat(timespec='seconds')


class InsightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in (('LIBRARY_ROOT', self.root / 'library'),):
            mock = patch.object(library, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.settings = patch.object(ai_settings, 'current', return_value={
            'provider': 'custom', 'base_url': 'https://example.invalid/v1', 'model': 'fixture',
            'api_key': '', 'price_input': 1.0, 'price_output': 2.0, 'started': None}).start()
        self.addCleanup(patch.stopall)
        self.first = library.ensure({'platform': 'bilibili', 'video_id': 'BV1TaqYBcEJc', 'title': '课程甲',
                                     'source_url': 'https://www.bilibili.com/video/BV1TaqYBcEJc?p=1'})
        self.second = library.ensure({'platform': 'bilibili', 'video_id': 'BV1TaqYBcEJd', 'title': '课程乙',
                                      'source_url': 'https://www.bilibili.com/video/BV1TaqYBcEJd'})
        source = self.root / 'clip'
        source.write_bytes(b'duplicate media fixture')
        self.video = 'video/test.mp4'
        for project in (self.first, self.second):
            library.import_file(project['id'], source, self.video, 'video', {'media': {'format': {'duration': '60'}}})
        self.save_usage(self.first['id'], 'analysis', '分析正文', {'usage': {'prompt_tokens': 100, 'completion_tokens': 50},
                                                                  'planning_usage': {'prompt_tokens': 10, 'completion_tokens': 5},
                                                                  'model': 'fixture', 'agent': {'engine': 'api'}})
        self.save_usage(self.first['id'], 'analysis-followup', '追问正文', {'usage': {'prompt_tokens': 20, 'completion_tokens': 10},
                                                                         'model': 'fixture', 'agent': {'engine': 'api'}})
        self.save_usage(self.first['id'], 'conversation-message', '对话正文',
                        {'usage': {'prompt_tokens': 30, 'completion_tokens': 15}, 'model': 'fixture', 'agent': {'engine': 'api'},
                         'context': {'planner_usage': {'prompt_tokens': 5, 'completion_tokens': 2}}})
        self.save_usage(self.second['id'], 'analysis', '另一份分析', {'usage': {'prompt_tokens': 40, 'completion_tokens': 20},
                                                                  'model': 'fixture', 'agent': {'engine': 'claude'}})
        extra = self.root / 'extra'
        extra.write_bytes(b'extra subtitle')
        self.extra = 'subtitles/extra.srt'
        library.import_file(self.first['id'], extra, self.extra, 'subtitle')

    def save_usage(self, project_id, kind, text, details):
        return library.save_text(project_id, kind, text, {**details, 'created_at': NOW, 'video_resource': self.video})

    def test_usage_totals_breakdowns_and_cost(self):
        report = usage_report.collect(0)
        totals = report['totals']
        self.assertEqual(totals['calls'], 6)
        self.assertEqual(totals['prompt_tokens'], 205)
        self.assertEqual(totals['completion_tokens'], 102)
        self.assertEqual(totals['total_tokens'], 307)
        self.assertEqual(totals['projects'], 2)
        self.assertEqual(totals['native_calls'], 1)
        # 165 input tokens at ¥1/M and 82 output tokens at ¥2/M; the native call is subscription-based.
        self.assertAlmostEqual(totals['cost'], (205 - 40) / 1e6 + (102 - 20) / 1e6 * 2, places=6)
        labels = {row['label']: row['calls'] for row in report['by_kind']}
        self.assertEqual(labels, {'分析': 2, '追问': 1, '对话': 1, '选帧规划': 2})
        self.assertEqual(report['by_model'][0]['model'], 'fixture')
        self.assertEqual([row['title'] for row in report['by_project']], ['课程甲', '课程乙'])
        self.assertEqual(report['by_day'][-1]['calls'], 6)
        self.assertEqual(report['prices']['configured'], True)
        self.assertIn('翻译', report['coverage'])

    def test_usage_window_and_missing_prices(self):
        self.assertEqual(usage_report.collect(1)['totals']['calls'], 6)
        with patch.object(ai_settings, 'current', return_value={'price_input': None, 'price_output': None}):
            report = usage_report.collect(0)
        self.assertIsNone(report['totals']['cost'])
        self.assertEqual(report['totals']['unpriced_calls'], 5)
        self.assertFalse(report['prices']['configured'])

    def test_health_reports_missing_moved_orphan_and_duplicates(self):
        directory = library.get(self.first['id'])['directory']
        (directory / 'subtitles' / 'extra.srt').unlink()
        (directory / 'moved').mkdir()
        (directory / 'moved' / 'extra.srt').write_bytes(b'extra subtitle')
        (directory / 'stray.txt').write_text('manual note', encoding='utf-8')
        report = archive_health.inspect()
        self.assertTrue(report['read_only'])
        self.assertEqual(report['totals']['projects'], 2)
        self.assertEqual(report['totals']['missing'], 1)
        self.assertEqual(report['totals']['orphan_files'], 2)
        self.assertEqual(report['totals']['duplicate_groups'], 1)
        self.assertGreater(report['totals']['duplicate_bytes'], 0)
        missing = report['issues']['missing']['items'][0]
        self.assertEqual(missing['suspected_move'], 'moved/extra.srt')
        markdown, name = archive_health.export_markdown(report)
        self.assertIn('只读体检', markdown)
        self.assertIn('缺失文件', markdown)
        self.assertIn('重复内容', markdown)
        self.assertIn('归档体检', name)

    def test_http_endpoints_are_local_and_read_only(self):
        client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))
        usage = client.get('/api/workspace/usage', params={'days': 30})
        self.assertEqual(usage.status_code, 200, usage.text)
        self.assertEqual(usage.json()['totals']['calls'], 6)
        self.assertIn('no-store', usage.headers['cache-control'])
        self.assertEqual(client.get('/api/workspace/usage', params={'days': -1}).status_code, 422)
        health = client.get('/api/workspace/archive/health')
        self.assertEqual(health.status_code, 200, health.text)
        self.assertTrue(health.json()['read_only'])
        report = client.get('/api/workspace/archive/health/export', params={'format': 'md'})
        self.assertEqual(report.status_code, 200)
        self.assertIn('归档体检报告', report.content.decode('utf-8'))
        self.assertIn("filename*=UTF-8''", report.headers['content-disposition'])
        self.assertEqual(client.get('/api/workspace/archive/health/export', params={'format': 'zip'}).status_code, 422)
        self.assertEqual(client.get('/api/workspace/archive/health', headers={'Origin': 'https://evil.invalid'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
