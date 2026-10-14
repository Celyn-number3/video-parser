"""Offline HTTP regression for the React bridge; CLI network/model boundaries are mocked."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from video_parser.services import videos as cli
from video_parser.web import routes as workspace
from video_parser.services import library as library
from video_parser.services import ai_settings
class ReactAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patch.object(library, 'LIBRARY_ROOT', self.root / 'library').start()
        self.addCleanup(patch.stopall)
        patch.object(workspace, 'WORKSPACE_ROOT', self.root / 'cache').start()
        # Never read the user's saved model settings (.local/ai/settings.json).
        patch.object(ai_settings, 'SETTINGS_PATH', self.root / 'ai' / 'settings.json').start()
        workspace.entries.clear()
        app = FastAPI()
        app.include_router(workspace.router)
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 12345))
        self.parsed = cli.ParsedVideo({'title': '测试视频', 'platform': '抖音', 'video_id': 'one',
            'source_url': 'https://www.douyin.com/video/1', 'cover_url': 'https://cdn.example/cover',
            'video_url': 'https://cdn.example/video'}, {'Referer': 'https://www.douyin.com/'},
            ['https://cdn.example/video'], [])
        self.parse_mock = patch.object(cli, 'parse_link', return_value=self.parsed).start()
        def cover(parsed, target):
            Image.new('RGB', (16, 9), 'green').save(target, format='PNG')
        self.cover_mock = patch.object(cli, 'save_cover', side_effect=cover).start()
        def download(parsed, target):
            target.write_bytes(b'test video content')
            return {'size_bytes': 18, 'media': {'format': {'duration': '2.0'},
                    'streams': [{'codec_type': 'video', 'width': 640, 'height': 360}]}}
        self.download_mock = patch.object(cli, 'download_video', side_effect=download).start()

    def parse(self):
        response = self.client.post('/api/workspace/parse', json={'text': self.parsed.metadata['source_url']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def prepare(self, entry):
        return self.client.post(f"/api/workspace/videos/{entry['id']}/prepare", json={})

    def test_config_exposes_archive_root_and_only_safe_status(self):
        response = self.client.get('/api/workspace/config')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['archive_root'], str((self.root / 'library').resolve()))
        for key in ('platforms', 'ai_configured', 'media_ready', 'subtitles_ready',
                    'transcription_ready', 'transcription_upload_limit'):
            self.assertIn(key, data)
        self.assertNotIn('QWEN_API_KEY', data)
        self.assertNotIn('cookie', data)
    def test_parse_cover_and_safe_metadata(self):
        data = self.parse()
        self.assertEqual(data['title'], '测试视频')
        self.assertNotIn('video_url', data)
        self.assertNotIn('headers', data)
        response = self.client.get(data['cover_url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        saved = self.client.get(data['cover_download_url'])
        self.assertIn('attachment', saved.headers['content-disposition'])
        self.assertIn('.png', saved.headers['content-disposition'])

    def test_prepare_cached_download_and_range(self):
        data = self.parse()
        first = self.prepare(data)
        second = self.prepare(data)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(self.download_mock.call_count, 1)
        self.assertEqual(first.json()['duration'], 2.0)
        media = self.client.get(first.json()['preview_url'], headers={'Range': 'bytes=0-3'})
        self.assertEqual(media.status_code, 206)
        self.assertEqual(media.content, b'test')
        self.assertIn('attachment', self.client.get(first.json()['download_url']).headers['content-disposition'])

    def test_isolation_and_unknown_resources(self):
        first, second = self.parse(), self.parse()
        self.assertNotEqual(first['id'], second['id'])
        self.prepare(first)
        self.assertEqual(self.client.get(f"/api/workspace/files/{second['id']}/video").status_code, 404)
        self.assertEqual(self.client.post('/api/workspace/videos/missing/prepare', json={}).status_code, 404)
        self.assertEqual(self.client.get('/api/workspace/files/missing/video').status_code, 404)
        self.assertEqual(self.client.get(f"/api/workspace/files/{first['id']}/secret").status_code, 404)

    def test_failure_retry_and_no_partial_publication(self):
        data = self.parse()
        self.download_mock.side_effect = RuntimeError('private backend path /secret')
        response = self.prepare(data)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('/secret', response.text)
        self.assertEqual(self.client.get(f"/api/workspace/files/{data['id']}/video").status_code, 404)
        def retry(parsed, target):
            target.write_bytes(b'video')
            return {'size_bytes': 5, 'media': {'format': {'duration': 2}, 'streams': [{'codec_type': 'video'}]}}
        self.download_mock.side_effect = retry
        self.assertEqual(self.prepare(data).status_code, 200)

    def test_transcription_sources_list_only_intact_archived_videos(self):
        sources = lambda: self.client.get('/api/workspace/transcriptions/sources').json()['sources']
        data = self.parse()
        self.assertEqual(sources(), [])
        prepared = self.prepare(data).json()
        listed = sources()
        self.assertEqual([(item['project_id'], item['resource']) for item in listed], [(data['project']['id'], prepared['resource'])])
        self.assertEqual((listed[0]['title'], listed[0]['platform'], listed[0]['duration_seconds'], listed[0]['size_bytes']), ('测试视频', '抖音', 2.0, 18))
        with (library.get(data['project']['id'])['directory'] / prepared['resource']).open('ab') as video: video.write(b'changed')
        self.assertEqual(sources(), [])

    def test_project_persists_and_same_video_reuses_download(self):
        first = self.parse()
        prepared = self.prepare(first).json()
        second = self.parse()
        self.assertEqual(first['project']['id'], second['project']['id'])
        self.assertEqual(second['media'], prepared)
        workspace.entries.clear()
        self.assertEqual(self.client.get(prepared['preview_url']).status_code, 200)
        self.assertEqual(self.client.get(first['project']['archive_url']).status_code, 200)
        details = self.client.get('/api/workspace/projects/' + first['project']['id'])
        self.assertEqual(details.status_code, 200)
        self.assertEqual(self.download_mock.call_count, 1)

    def test_open_project_uses_only_registered_controlled_path(self):
        data=self.parse()
        with patch('video_parser.web.routes.os.startfile', create=True) as open_folder, patch('video_parser.web.routes.sys.platform','win32'):
            response=self.client.post('/api/workspace/projects/' + data['project']['id'] + '/open',json={})
            self.assertEqual(response.status_code,200)
            opened=Path(open_folder.call_args.args[0])
            self.assertTrue(opened.is_relative_to(library.LIBRARY_ROOT))
            self.assertEqual(self.client.post('/api/workspace/projects/missing/open',json={}).status_code,404)
            self.assertEqual(open_folder.call_count,1)

    def test_douyin_platform_error_is_visible_without_raw_response(self):
        self.parse_mock.side_effect = workspace.DouyinAccessError()
        response = self.client.post('/api/workspace/parse', json={'text': 'https://www.douyin.com/video/7617880126232085627'})
        self.assertEqual(response.status_code, 502)
        self.assertIn('抖音链接已识别', response.json()['detail'])
        self.assertIn('当前未下载视频', response.json()['detail'])
        self.assertNotIn('JSONDecodeError', response.text)
        self.assertNotIn('Cookie', response.text)

    def test_parse_no_video_download_and_quality_variants_select_exact_version(self):
        self.parsed.metadata.update(platform='哔哩哔哩',video_id='BV1TaqYBcEJc',source_url='https://www.bilibili.com/video/BV1TaqYBcEJc')
        self.parsed.audio_urls=['https://fixture/audio']
        self.parsed.variants={f'{h}p':{'id':f'{h}p','label':f'{h}p','height':h,'width':w,'codec':'avc1','track_id':h,'video_urls':[f'https://fixture/{h}']} for h,w in [(1080,1920),(720,1280)]}
        data=self.parse()
        self.download_mock.assert_not_called()
        self.assertEqual([q['height'] for q in data['qualities']],[1080,720])
        self.assertNotIn('https://fixture',str(data['qualities']))
        def download(parsed,target):
            selected=parsed.metadata['selected_quality']
            target.write_bytes(str(selected['height']).encode())
            return {'size_bytes':target.stat().st_size,'media':{'format':{'duration':2},'streams':[{'codec_type':'video','width':selected['width'],'height':selected['height']},{'codec_type':'audio'}]}}
        self.download_mock.side_effect=download
        url=f"/api/workspace/videos/{data['id']}/prepare"
        high=self.client.post(url,json={'quality_id':'1080p'})
        low=self.client.post(url,json={'quality_id':'720p'})
        self.assertEqual(high.status_code,200,high.text)
        self.assertEqual(low.status_code,200,low.text)
        self.assertNotEqual(high.json()['preview_url'],low.json()['preview_url'])
        self.assertEqual(self.client.get(high.json()['download_url']).content,b'1080')
        self.assertEqual(self.client.get(low.json()['download_url']).content,b'720')
        self.assertEqual(self.client.post(url,json={'quality_id':'720p'}).json(),low.json())
        self.assertEqual(self.download_mock.call_count,2)
        invalid=self.client.post(url,json={'quality_id':'2160p'})
        self.assertEqual(invalid.status_code,400)
        with patch.dict(os.environ,{'QWEN_API_KEY':'local'}),patch('video_parser.services.analysis.analyze_video',return_value='selected low') as analyze:
            self.assertEqual(self.client.post(f"/api/workspace/videos/{data['id']}/analyze",json={'quality_id':'720p','consent':True}).status_code,200)
            self.assertEqual(Path(analyze.call_args.args[0]).read_bytes(),b'720')
        workspace.entries.clear()
        resumed=self.client.get('/api/workspace/projects/'+data['project']['id']+'/resume')
        self.assertEqual(resumed.status_code,200)
        self.assertEqual(len(resumed.json()['qualities']),2)

    def test_cover_failure_does_not_discard_video(self):
        self.cover_mock.side_effect = RuntimeError('offline')
        data = self.parse()
        self.assertIsNone(data['cover_url'])
        self.assertTrue(data['warning'])
        self.assertEqual(self.prepare(data).status_code, 200)

    def test_validation_and_local_origin_boundary(self):
        for text in ('', ' '):
            self.assertEqual(self.client.post('/api/workspace/parse', json={'text': text}).status_code, 422)
        self.assertEqual(self.client.post('/api/workspace/parse', json={'text': 'a' * 8193}).status_code, 422)
        self.parse_mock.assert_not_called()
        for headers in ({'Origin': 'https://evil.example'}, {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            response = self.client.post('/api/workspace/parse', json={'text': 'https://www.douyin.com/video/1'}, headers=headers)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post('/api/workspace/parse', content='text=x', headers={'Content-Type': 'application/x-www-form-urlencoded'}).status_code, 415)
        other = TestClient(self.client.app, base_url='http://127.0.0.1:15001', client=('10.0.0.2', 12345))
        self.assertEqual(other.get('/api/workspace/config').status_code, 403)
        self.parse_mock.side_effect = ValueError('bad URL')
        self.assertEqual(self.client.post('/api/workspace/parse', json={'text': 'bad'}).status_code, 400)

    def test_duplicate_work_returns_conflict(self):
        data = self.parse()
        entry = workspace.entries[data['id']]
        with entry.lock:
            self.assertEqual(self.prepare(data).status_code, 409)
        self.download_mock.assert_not_called()

    def test_expiry_and_capacity(self):
        data = self.parse()
        workspace.entries[data['id']].created_at -= workspace.SESSION_TTL + 1
        self.assertEqual(self.prepare(data).status_code, 404)
        with patch.object(workspace, 'MAX_SESSIONS', 1):
            self.parse()
            response = self.client.post('/api/workspace/parse', json={'text': 'https://www.douyin.com/video/2'})
            self.assertEqual(response.status_code, 429)

    def test_arbitrary_paths_and_symlink_escape(self):
        data = self.parse()
        self.prepare(data)
        secret = self.root / 'secret.txt'
        secret.write_text('secret')
        target = library.find(data['project']['id'], 'video')[1]
        target.unlink()
        try:
            target.symlink_to(secret)
        except OSError:
            # Exercise the same canonical-path guard even without Windows symlink privileges.
            with patch.object(library, 'resource', side_effect=ValueError('Outside project')):
                self.assertEqual(self.client.get(f"/api/workspace/files/{data['id']}/video").status_code, 404)
            return
        self.assertEqual(self.client.get(f"/api/workspace/files/{data['id']}/video").status_code, 404)

    def test_ai_preconditions_and_config_no_secrets(self):
        data = self.parse()
        url = f"/api/workspace/videos/{data['id']}/analyze"
        with patch.dict(os.environ, {'QWEN_API_KEY': ''}):
            config = self.client.get('/api/workspace/config').json()
            self.assertFalse(config['ai_configured'])
            self.assertNotIn('api_key', config)
            self.assertEqual(self.client.post(url, json={'consent': True, 'count': 6, 'prompt': ''}).status_code, 503)
        with patch.dict(os.environ, {'QWEN_API_KEY': 'not-a-real-secret'}):
            for body in ({'consent': False}, {'consent': True, 'count': 17}, {'consent': True, 'count': 0}, {'consent': 1}, {'consent': True, 'count': True}, {'consent': True, 'prompt': 'a' * 4001}):
                self.assertEqual(self.client.post(url, json=body).status_code, 422)
            self.assertEqual(self.client.post(url, json={'consent': True}).status_code, 409)
            self.prepare(data)
            with patch('video_parser.services.analysis.analyze_video', return_value='本地画面分析') as analyze:
                response = self.client.post(url, json={'consent': True, 'count': 4, 'prompt': '描述画面'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['text'], '本地画面分析')
                self.assertEqual(analyze.call_args.kwargs['num_frames'], 4)
                self.assertFalse(analyze.call_args.kwargs['stream'])
            with patch('video_parser.services.analysis.analyze_video', side_effect=RuntimeError('secret-key')):
                response = self.client.post(url, json={'consent': True})
                self.assertEqual(response.status_code, 502)
                self.assertNotIn('secret-key', response.text)


if __name__ == '__main__':
    unittest.main()
