"""Offline CLI regressions; network boundaries are replaced with local fixtures."""
from video_parser import cli as cli_entry
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / 'cli.py'


class EntryTests(unittest.TestCase):
    def invoke(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(ENTRY), *args], cwd=cwd or ROOT,
                              capture_output=True, text=True, encoding='utf-8')

    def test_help_without_web_server(self):
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('download', result.stdout)
        self.assertIn('analyze', result.stdout)

    def test_capabilities_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke('capabilities', '--json', cwd=directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['platforms']), 4)
        self.assertIn('YouTube', data['platforms'])
        self.assertIn('cover', data['commands'])
        self.assertTrue(data['speech_transcription'])

    def test_list_custom_directory_only(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'example.mp4').write_bytes(b'video')
            (Path(directory) / 'other.txt').write_text('ignored')
            result = self.invoke('--json', 'list', '--directory', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            files = json.loads(result.stdout)['files']
            self.assertEqual([Path(file['path']).name for file in files], ['example.mp4'])
            self.assertTrue(Path(files[0]['path']).is_absolute())

    def test_missing_video_is_nonzero_json_error(self):
        result = self.invoke('frames', 'does-not-exist.mp4', '--json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['ok'])

    def test_frames_count_must_be_positive(self):
        result = self.invoke('frames', 'file.mp4', '--count', '0')
        self.assertEqual(result.returncode, 2)
        self.assertIn('正整数', result.stderr)


class LogicTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ENTRY.exists(), 'CLI entrypoint not implemented')
        self.cli = importlib.import_module('video_parser.services.videos')

    def test_share_text_and_bilibili_part_preserved(self):
        url, platform = self.cli.resolve_url('标题 https://bilibili.com/video/BV123?p=2&vd_source=x ，')
        self.assertEqual(platform, '哔哩哔哩')
        self.assertEqual(url, 'https://www.bilibili.com/video/BV123?p=2')

    def test_xiaohongshu_token_preserved(self):
        url, platform = self.cli.resolve_url('https://www.xiaohongshu.com/explore/abc?xsec_token=a%2Bb&xsec_source=pc_share&share=x')
        self.assertEqual(platform, '小红书')
        self.assertIn('xsec_token=a%2Bb', url)
        self.assertNotIn('share=', url)

    def test_unsupported_host_rejected_before_network(self):
        with patch('requests.get') as request:
            with self.assertRaises(ValueError):
                self.cli.resolve_url('https://www.bilibili.com.evil.example/video/x')
        request.assert_not_called()

    def test_shortlink_resolved_using_existing_fetcher(self):
        with patch('video_parser.platforms.web_fetcher.WebFetcher.fetch_redirect_url', return_value='https://www.bilibili.com/video/BV123'):
            self.assertEqual(self.cli.resolve_url('https://b23.tv/example')[1], '哔哩哔哩')

    def test_shortlink_preserves_bilibili_part_from_redirect(self):
        response = type('Response', (), {'status_code': 302, 'headers': {'location': 'https://www.bilibili.com/video/BV123?p=2&share=x'}, 'raise_for_status': lambda self: None})()
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
             patch('video_parser.platforms.web_fetcher.requests.get', return_value=response):
            url, platform = self.cli.resolve_url('https://b23.tv/example')
        self.assertEqual(url, 'https://www.bilibili.com/video/BV123?p=2')

    def test_existing_web_fetcher_default_normalization_is_unchanged(self):
        from video_parser.platforms.web_fetcher import WebFetcher
        response = type('Response', (), {'status_code': 302, 'headers': {'location': 'https://www.bilibili.com/video/BV123?p=2&share=x'}, 'raise_for_status': lambda self: None})()
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
             patch('video_parser.platforms.web_fetcher.requests.get', return_value=response):
            self.assertEqual(WebFetcher.fetch_redirect_url('https://b23.tv/example'), 'https://www.bilibili.com/video/BV123')

    def test_empty_frame_extraction_removes_temp_directory(self):
        from video_parser.services import analysis as qwen3vl
        with tempfile.TemporaryDirectory() as directory:
            frames_dir = Path(directory) / 'frames'
            frames_dir.mkdir()
            with patch.object(qwen3vl, 'get_video_duration', return_value=1), patch.object(qwen3vl.tempfile, 'mkdtemp', return_value=str(frames_dir)), patch.object(qwen3vl.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(qwen3vl.extract_frames('fixture.mp4', 1), [])
            self.assertFalse(frames_dir.exists(), 'Empty extraction leaked temporary directory')

    def test_bilibili_best_tracks_and_backup_urls(self):
        fake = type('Downloader', (), {
            'headers': {'Referer': 'https://www.bilibili.com/'},
            'data': json.dumps({'data': {'dash': {
                'duration': 10, 'video': [
                    {'height': 360, 'width': 640, 'baseUrl': 'https://cdn/v360'},
                    {'height': 480, 'width': 852, 'baseUrl': 'https://cdn/v480', 'backupUrl': ['https://cdn/backup']}],
                'audio': [{'baseUrl': 'https://cdn/audio', 'bandwidth': 100}]}}}),
            'get_title_content': lambda self: '测试标题',
            'get_cover_photo_url': lambda self: 'https://cdn/cover.jpg',
            'get_real_video_url': lambda self: 'https://cdn/v360',
            'get_audio_url': lambda self: 'https://cdn/audio',
        })()
        with patch('video_parser.platforms.factory.DownloaderFactory.create_downloader', return_value=fake):
            parsed = self.cli.parse_link('https://www.bilibili.com/video/BV123')
        self.assertEqual(parsed.metadata['height'], 480)
        self.assertEqual(parsed.video_urls, ['https://cdn/v480', 'https://cdn/backup'])
        self.assertEqual(parsed.audio_urls, ['https://cdn/audio'])
        self.assertNotIn('headers', parsed.metadata)

    def test_empty_parse_is_a_failure_not_success(self):
        fake = type('Downloader', (), {
            'headers': {}, 'get_title_content': lambda self: 'title',
            'get_cover_photo_url': lambda self: None,
            'get_real_video_url': lambda self: None,
        })()
        with patch('video_parser.platforms.factory.DownloaderFactory.create_downloader', return_value=fake):
            with self.assertRaises(RuntimeError):
                self.cli.parse_link('https://www.xiaohongshu.com/explore/123')

    def test_safe_name_no_traversal_or_windows_reserved_name(self):
        for title in ['../../CON', 'CON', 'AUX.txt', 'a:b/c\\d?', '....', '']:
            name = self.cli.safe_name(title, 'BV123')
            self.assertNotIn('/', name)
            self.assertNotIn('\\', name)
            self.assertNotIn(':', name)
            self.assertTrue(name.strip('. '))
            self.assertNotIn(name.split('.')[0].upper(), ['CON', 'AUX'])

    def test_publish_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            original, staged = Path(directory) / 'old.mp4', Path(directory) / 'new.mp4'
            original.write_bytes(b'original')
            staged.write_bytes(b'replacement')
            with self.assertRaises(FileExistsError):
                self.cli.publish(staged, original)
            self.assertEqual(original.read_bytes(), b'original')

    def test_download_falls_back_after_truncated_track(self):
        class Response:
            headers = {'Content-Length': '5'}
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def raise_for_status(self): pass
            def iter_content(self, chunk_size): yield self.data
        with tempfile.TemporaryDirectory() as directory, patch('requests.get', side_effect=[Response(b'ab'), Response(b'abcde')]):
            path = Path(directory) / 'track.m4s'
            self.cli.download_resource(['https://cdn/one', 'https://cdn/two'], path, {})
            self.assertEqual(path.read_bytes(), b'abcde')

    def test_download_failure_has_no_final_file(self):
        parsed = self.cli.ParsedVideo({'title': 'title', 'video_id': '123', 'platform': '小红书'}, {}, ['https://cdn/video'], [])
        with tempfile.TemporaryDirectory() as directory, patch.object(self.cli, 'download_resource', side_effect=RuntimeError('offline')):
            target = Path(directory) / 'final.mp4'
            with self.assertRaises(RuntimeError):
                self.cli.download_video(parsed, target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_bilibili_missing_audio_fails_before_download(self):
        parsed = self.cli.ParsedVideo({'title': 'title', 'video_id': '123', 'platform': '哔哩哔哩'}, {}, ['https://cdn/video'], [])
        with tempfile.TemporaryDirectory() as directory, patch.object(self.cli, 'download_resource') as download:
            with self.assertRaises(RuntimeError):
                self.cli.download_video(parsed, Path(directory) / 'video.mp4')
        download.assert_not_called()

    def test_cover_only_note_does_not_require_video(self):
        fake = type('Downloader', (), {
            'headers': {}, 'get_title_content': lambda self: '图文',
            'get_cover_photo_url': lambda self: 'https://cdn/cover.webp',
            'get_real_video_url': lambda self: None,
        })()
        with patch('video_parser.platforms.factory.DownloaderFactory.create_downloader', return_value=fake):
            parsed = self.cli.parse_link('https://www.xiaohongshu.com/explore/123', require_video=False)
        self.assertEqual(parsed.metadata['cover_url'], 'https://cdn/cover.webp')

    def test_cli_json_remains_clean_when_backend_prints(self):
        def noisy(args):
            print('backend progress')
            return {'path': '/test/video.mp4'}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.cli, 'execute', side_effect=noisy), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli_entry.main(['download', 'https://b23.tv/x', '--json'])
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(stdout.getvalue())['ok'])
        self.assertIn('backend progress', stderr.getvalue())

    def test_missing_ai_key_does_not_download(self):
        with patch.dict(os.environ, {'QWEN_API_KEY': ''}), patch.object(self.cli, 'parse_link') as parse:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = cli_entry.main(['analyze', 'https://b23.tv/example'])
        self.assertEqual(status, 1)
        parse.assert_not_called()

    def test_remote_analysis_report_is_not_download_destination(self):
        parsed = self.cli.ParsedVideo({'source_url': 'https://www.bilibili.com/video/BV123', 'title': 'title', 'video_id': 'BV123', 'platform': '哔哩哔哩'}, {}, ['https://cdn/video'], ['https://cdn/audio'])
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.md'
            downloads = Path(directory) / 'downloads'
            def download(video, target):
                self.assertEqual(Path(target).parent, downloads)
                self.assertEqual(Path(target).suffix, '.mp4')
                return {'path': str(target)}
            with patch.dict(os.environ, {'QWEN_API_KEY': 'test-only'}), patch.object(self.cli, 'require_tools'), patch.object(self.cli, 'parse_link', return_value=parsed), patch.object(self.cli, 'download_video', side_effect=download), patch.object(self.cli, 'probe', return_value={'streams': [{'codec_type': 'video'}]}), patch('video_parser.services.analysis.analyze_video', return_value='测试分析'), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = cli_entry.main(['analyze', 'https://b23.tv/x', '--output', str(report), '--output-dir', str(downloads)])
            self.assertEqual(status, 0)
            self.assertEqual(report.read_text(encoding='utf-8'), '测试分析')

    def test_qwen_failure_cleans_sampled_frames(self):
        from video_parser.services import analysis as qwen3vl
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.mp4'
            source.write_bytes(b'fixture')
            frames_dir = Path(directory) / 'frames'
            frames_dir.mkdir()
            frame = frames_dir / 'frame.jpg'
            frame.write_bytes(b'image')
            with patch.object(qwen3vl, 'extract_frames', return_value=[str(frame)]), patch.object(qwen3vl, 'OpenAI', side_effect=RuntimeError('model unavailable')), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    qwen3vl.analyze_video(str(source), stream=False)
            self.assertFalse(frame.exists(), 'Model failure leaked sampled frame')
            self.assertFalse(frames_dir.exists())

    def test_doctor_does_not_expose_key(self):
        with patch.dict(os.environ, {'QWEN_API_KEY': 'private-test-value'}):
            report = self.cli.doctor()
        self.assertTrue(report['ai_configured'])
        self.assertNotIn('private-test-value', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
