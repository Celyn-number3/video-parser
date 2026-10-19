"""Offline adapter and HTTP regression; never reads real cookies or visits Bilibili."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from video_parser.services import subtitles
from video_parser.web import routes as workspace
from video_parser.services import library as library
class SubtitleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patch.object(library, 'LIBRARY_ROOT', self.root / 'library').start()
        self.tool = self.root / 'tool'
        self.tool.mkdir()
        (self.tool / 'b站.py').write_text('# fixture')
        self.addCleanup(patch.stopall)
        patch.object(subtitles, 'TOOL_ROOT', self.tool).start()
        patch.object(subtitles, 'CHECKER_PATH', Path(__file__).resolve().parents[1] / 'fixtures' / 'subtitle_checker.py').start()
        patch.object(subtitles, 'CACHE_ROOT', self.root / 'cache').start()
        subtitles.jobs.clear()
        self.resolve = patch.object(subtitles.videos, 'resolve_url', return_value=('https://www.bilibili.com/video/BV1TaqYBcEJc?p=3', '哔哩哔哩')).start()
        app = FastAPI()
        app.include_router(workspace.router)
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 12345))

    def triplet(self, ep=3, valid=True):
        base = self.tool / 'subtitle_download' / '本地课程'
        name = f'P{ep:02d}_第{ep}节'
        for folder, ext in [('_json', 'json'), ('_srt', 'srt'), ('_md', 'md')]:
            target = base / folder / f'{name}.{ext}'
            target.parent.mkdir(parents=True, exist_ok=True)
            if ext == 'json':
                target.write_text(json.dumps({'body': [{'from': 0, 'to': 1, 'content': '测试字幕'}]}, ensure_ascii=False), encoding='utf-8')
            elif valid:
                target.write_text('1\n00:00:00,000 --> 00:00:01,000\n测试字幕' if ext == 'srt' else '测试字幕', encoding='utf-8')
        return base

    def finish(self, job):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.client.get(f"/api/workspace/subtitles/{job['id']}")
            self.assertEqual(result.status_code, 200)
            if result.json()['state'] not in ('queued','running'):
                return result.json()
            time.sleep(.02)
        self.fail('Fixture job did not complete')

    def start(self, **extra):
        result = self.client.post('/api/workspace/subtitles', json={'text': 'https://www.bilibili.com/video/BV1TaqYBcEJc?p=3', **extra})
        self.assertEqual(result.status_code, 202, result.text)
        return result.json()

    def test_current_episode_and_safe_process_args(self):
        url, episodes = subtitles.selection('link', 'current', '')
        self.assertEqual(episodes, [3])
        self.assertEqual(subtitles.command(url, episodes)[-2:], ['--ep', '3'])
        self.assertIn('-u', subtitles.command(url, episodes))
        with patch.object(subtitles, 'run_cli', return_value=(0, 'series: 本地课程  (BV1TaqYBcEJc)\nselected 1/4 episodes: [3]\n[P3] exists, skip')):
            self.triplet()
            result = self.finish(self.start())
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['existing'], 1)
        self.assertEqual(result['downloaded'], 0)
        self.assertNotIn(str(self.tool), json.dumps(result))
        self.assertNotIn('archive_url', result)
        self.assertEqual(len(result['results'][0]['files']), 3)
        for item in result['results'][0]['files']:
            self.assertEqual(self.client.get(item['url']).status_code, 200)
        self.assertFalse(list(subtitles.jobs[result['id']].directory.rglob('*.zip')))

    def test_new_download_and_partial_out_of_range(self):
        def cli_result(url, episodes):
            self.triplet(2)
            return 0, 'series: 本地课程  (BV1TaqYBcEJc)\nselected 1/4 episodes: [2]\n[P2] 第2节'
        with patch.object(subtitles, 'run_cli', side_effect=cli_result):
            result = self.finish(self.start(scope='custom', episodes='2,8'))
        self.assertEqual(result['state'], 'partial')
        self.assertEqual((result['downloaded'], result['failed']), (1, 1))
        self.assertIn('总集数', result['results'][1]['message'])
        for item in result['results'][0]['files']:
            response = self.client.get(item['url'])
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment', response.headers['content-disposition'])

    def test_login_prompt_before_success_does_not_hide_valid_subtitles(self):
        self.triplet()
        log = ('please login manually in browser (scan QR code)...\nlogin detected!\n'
               'series: 本地课程  (BV1TaqYBcEJc)\nselected 1/4 episodes: [3]\n[P3] exists, skip')
        with patch.object(subtitles, 'run_cli', return_value=(0, log)):
            result = self.finish(self.start())
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['existing'], 1)
        self.assertEqual(len(result['results'][0]['files']), 3)

    def test_login_prompt_without_confirmed_target_requests_login(self):
        with patch.object(subtitles, 'run_cli', return_value=(1, 'please login manually in browser (scan QR code)...')):
            result = self.finish(self.start())
        self.assertEqual(result['state'], 'login_required')
        self.assertEqual(result['results'], [])

    def test_incomplete_existing_files_are_not_reported_success(self):
        self.triplet(valid=False)
        with patch.object(subtitles, 'run_cli', return_value=(0, 'series: 本地课程  (BV1TaqYBcEJc)\nselected 1/4 episodes: [3]\n[P3] exists, skip')):
            result = self.finish(self.start())
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('archive_url', result)
        self.assertEqual(result['failed'], 1)
        self.assertTrue((self.tool / 'subtitle_download/本地课程/_json/P03_第3节.json').exists())

    def test_title_sanitization_matches_existing_cli(self):
        self.assertEqual(subtitles.sanitize_title('a\\b/c:*?"<>| 标题'), 'a_b_c________标题')

    def test_registered_file_cannot_escape_output_root(self):
        self.triplet()
        with patch.object(subtitles, 'run_cli', return_value=(0, 'series: 本地课程  (BV1TaqYBcEJc)\nselected 1/4 episodes: [3]\n[P3] exists, skip')):
            result = self.finish(self.start())
        secret = self.root / 'private.txt'
        secret.write_text('private')
        subtitles.jobs[result['id']].files['3-srt'] = secret
        self.assertEqual(self.client.get(f"/api/workspace/subtitles/{result['id']}/files/3-srt").status_code, 404)

    def test_all_and_failed_exit_must_keep_missing_episodes(self):
        self.triplet(1)
        with patch.object(subtitles, 'run_cli', return_value=(1, 'series: 本地课程  (BV1TaqYBcEJc)\nselected 2/2 episodes: [1,2]\n[P1] exists, skip')):
            result = self.finish(self.start(scope='all'))
        self.assertEqual(result['state'], 'partial')
        self.assertEqual((result['existing'], result['failed']), (1, 1))
        self.assertIn('异常', result['message'])
        self.assertEqual(subtitles.command('https://example', None)[-1], '--all')

    def test_validation_and_non_bilibili(self):
        for value in ['0', '-1', '5-2', '1.5', '1,,2', '1;echo test', '1-1001']:
            response = self.client.post('/api/workspace/subtitles', json={'text': 'url', 'scope': 'custom', 'episodes': value})
            self.assertEqual(response.status_code, 400, response.text)
        self.resolve.return_value = ('https://www.douyin.com/video/1', '抖音')
        self.assertEqual(self.client.post('/api/workspace/subtitles', json={'text': 'url'}).status_code, 400)
        self.resolve.return_value = ('https://www.bilibili.com/video/BV1TaqYBcEJc?p=0', '哔哩哔哩')
        self.assertEqual(self.client.post('/api/workspace/subtitles', json={'text': 'url'}).status_code, 400)
        self.assertEqual(self.client.post('/api/workspace/subtitles', json={'text': 'url'}, headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_login_requirement_and_missing_tool(self):
        with patch.object(subtitles, 'run_cli', return_value=(1, '缺少登录 Cookie：无头模式无法在浏览器窗口扫码。')):
            result = self.finish(self.start())
        self.assertEqual(result['state'], 'login_required')
        self.assertIn('工作台扫码登录', result['message'])
        (self.tool / 'b站.py').unlink()
        self.assertEqual(self.client.post('/api/workspace/subtitles', json={'text': 'url'}).status_code, 503)

    def test_one_job_only_unknown_files_and_expiry(self):
        with subtitles.cli_lock:
            self.assertEqual(self.client.post('/api/workspace/subtitles', json={'text': 'url'}).status_code, 409)
        self.assertEqual(self.client.get('/api/workspace/subtitles/missing').status_code, 404)
        self.assertEqual(self.client.get('/api/workspace/subtitles/missing/files/secret').status_code, 404)
        with patch.object(subtitles, 'run_cli', return_value=(0, 'no __INITIAL_STATE__, cannot continue')):
            result = self.finish(self.start())
        self.assertEqual(result['state'], 'failed')
        job = subtitles.jobs[result['id']]
        job.created_at -= subtitles.JOB_TTL + 1
        restored=self.client.get(f"/api/workspace/subtitles/{job.id}")
        self.assertEqual(restored.status_code,200)
        self.assertEqual(restored.json()["state"],"failed")
        self.assertEqual(restored.json()["id"],job.id)

    def archive_subtitle(self, part):
        project = library.ensure({'platform': '哔哩哔哩', 'video_id': 'BV1TaqYBcEJc', 'title': '本地课程',
                                  'source_url': f'https://www.bilibili.com/video/BV1TaqYBcEJc?p={part}',
                                  'episodes': [{'part': number, 'title': f'第{number}节'} for number in range(1, 5)]})
        source = self.root / f'archived-{part}.srt'
        source.write_text('1\n00:00:00,000 --> 00:00:01,000\n测试字幕', encoding='utf-8')
        library.import_file(project['id'], source, f'subtitles/p{part}.平台字幕.srt', 'subtitle')
        return project

    def test_archived_episodes_are_listed_offline_and_not_enqueued_again(self):
        self.archive_subtitle(3)
        inventory = self.client.post('/api/workspace/subtitles/inventory', json={'text': '看这个 https://www.bilibili.com/video/BV1TaqYBcEJc?p=3'})
        self.assertEqual(inventory.status_code, 200, inventory.text)
        self.assertEqual((inventory.json()['total'], inventory.json()['archived']), (4, [3]))
        self.resolve.assert_not_called()
        self.assertEqual(self.client.post('/api/workspace/subtitles/inventory', json={'text': 'no id'}).json()['archived'], [])
        with patch.object(subtitles, 'run_cli') as run_cli:
            response = self.client.post('/api/workspace/subtitles', json={'text': 'https://www.bilibili.com/video/BV1TaqYBcEJc?p=3'})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn('无需重复下载', response.json()['detail'])
            run_cli.assert_not_called()
        def cli_result(url, episodes):
            self.assertEqual(episodes, [1, 2, 4])
            for number in episodes: self.triplet(number)
            return 0, 'series: 本地课程  (BV1TaqYBcEJc)\nselected 3/4 episodes: [1,2,4]\n[P1] 第1节'
        with patch.object(subtitles, 'run_cli', side_effect=cli_result):
            result = self.finish(self.start(scope='all'))
        self.assertEqual(result['skipped'], [3])
        self.assertEqual([row['episode'] for row in result['results']], [1, 2, 4])
        self.assertIn('已跳过本地已有字幕 1 集', result['message'])
        self.assertEqual(library.subtitle_inventory('BV1TaqYBcEJc')['archived'], [1, 2, 3, 4])

    def test_all_skip_uses_catalogued_episode_numbers_and_preserves_unknown_range(self):
        inventory = {'total': 2, 'archived': [3], 'episodes': [{'part': 3}, {'part': 4}]}
        with patch.object(library, 'subtitle_inventory', return_value=inventory):
            url = 'https://www.bilibili.com/video/BV1TaqYBcEJc'
            self.assertEqual(subtitles.skip_archived(url, None), ([4], [3]))
            self.assertEqual(subtitles.skip_archived(url, [2, 3, 4]), ([2, 4], [3]))
            inventory['archived'] = [3, 4]
            with self.assertRaisesRegex(ValueError, '无需重复下载'):
                subtitles.skip_archived(url, None)
            inventory.update(total=None, episodes=[])
            self.assertEqual(subtitles.skip_archived(url, None), (None, []))


if __name__ == '__main__':
    unittest.main()
