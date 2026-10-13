"""Real ffmpeg + loopback HTTP integration; no accounts or external AI charges."""
from video_parser import cli as cli_entry
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg and ffprobe required')
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = importlib.import_module('video_parser.services.videos')
        cls.workspace = tempfile.TemporaryDirectory(prefix='video-parser-test-')
        cls.root = Path(cls.workspace.name)
        cls.video = cls.root / 'fixture.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=10',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '2', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(cls.video)], check=True)
        for name, options in [('video', ['-an', '-c:v', 'copy']), ('audio', ['-vn', '-c:a', 'copy'])]:
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(cls.video), *options, '-f', 'mp4',
                            str(cls.root / f'{name}.m4s')], check=True)
        from PIL import Image
        cover = io.BytesIO()
        Image.new('RGB', (160, 90), 'blue').save(cover, format='JPEG')
        resources = {'/muxed': cls.video.read_bytes(), '/video': (cls.root / 'video.m4s').read_bytes(),
                     '/audio': (cls.root / 'audio.m4s').read_bytes(), '/cover.jpg': cover.getvalue(), '/not-image': b'<html>blocked</html>'}
        cls.requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = resources.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                if self.path != '/v1/chat/completions':
                    self.send_error(404)
                    return
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                cls.requests.append(payload)
                body = json.dumps({'id': 'local-test', 'object': 'chat.completion', 'created': 1, 'model': payload['model'],
                                   'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '本地测试：画面出现彩色测试图。'}, 'finish_reason': 'stop'}]}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.workspace.cleanup()

    def test_split_video_audio_download_merge_and_verify(self):
        parsed = self.cli.ParsedVideo({'platform': '哔哩哔哩', 'title': 'fixture', 'duration': 2}, {},
                                     [self.base + '/video'], [self.base + '/audio'])
        target = self.root / 'merged.mp4'
        result = self.cli.download_video(parsed, target)
        streams = {item['codec_type'] for item in result['media']['streams']}
        self.assertEqual(streams, {'video', 'audio'})
        self.assertGreater(target.stat().st_size, 0)
        with self.assertRaises(FileExistsError):
            self.cli.download_video(parsed, target)

    def test_direct_download_is_verified(self):
        parsed = self.cli.ParsedVideo({'platform': '快手', 'title': 'fixture'}, {}, [self.base + '/muxed'], [])
        target = self.root / 'direct.mp4'
        result = self.cli.download_video(parsed, target)
        self.assertAlmostEqual(float(result['media']['format']['duration']), 2, delta=.1)
        self.assertEqual(target.read_bytes(), self.video.read_bytes())

    def test_cover_download_and_reject_html(self):
        parsed = self.cli.ParsedVideo({'cover_url': self.base + '/cover.jpg'}, {}, [], [])
        target = self.root / 'cover.jpg'
        result = self.cli.save_cover(parsed, target)
        from PIL import Image
        with Image.open(result['path']) as image:
            self.assertEqual(image.size, (160, 90))
        parsed.metadata['cover_url'] = self.base + '/not-image'
        invalid = self.root / 'invalid.jpg'
        with self.assertRaises(Exception):
            self.cli.save_cover(parsed, invalid)
        self.assertFalse(invalid.exists())

    def test_frames_cli_outputs_requested_images_and_no_overwrite(self):
        target = self.root / '画面'
        command = [sys.executable, str(ROOT / 'cli.py'), 'frames', str(self.video), '--count', '3', '--output', str(target), '--json']
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        frames = json.loads(result.stdout)['frames']
        self.assertEqual(len(frames), 3)
        from PIL import Image
        for frame in frames:
            with Image.open(frame) as image:
                self.assertEqual(image.size, (160, 90))
        again = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(again.returncode, 1)
        self.assertEqual(len(list(target.glob('*.jpg'))), 3)

    def test_analysis_cli_real_extraction_and_local_model_roundtrip(self):
        report = self.root / '分析.md'
        env = dict(os.environ, QWEN_API_KEY='local-fixture-not-a-secret', QWEN_API_BASE_URL=self.base + '/v1',
                   QWEN_MODEL_ID='fixture-model', NO_PROXY='127.0.0.1,localhost')
        result = subprocess.run([sys.executable, str(ROOT / 'cli.py'), 'analyze', str(self.video), '--frames', '2',
                                 '--prompt', '描述画面', '--output', str(report), '--json'],
                                env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['analysis'], report.read_text(encoding='utf-8'))
        self.assertNotIn('local-fixture-not-a-secret', result.stdout + result.stderr)
        content = self.requests[-1]['messages'][0]['content']
        self.assertEqual(content[0]['text'], '描述画面')
        images = [item['image_url']['url'] for item in content if item['type'] == 'image_url']
        self.assertEqual(len(images), 2)
        self.assertTrue(all(image.startswith('data:image/jpeg;base64,') for image in images))

    def test_play_only_dispatches_system_open(self):
        if sys.platform != 'win32':
            self.skipTest('Windows system-player dispatch')
        with patch('os.startfile') as startfile, contextlib.redirect_stdout(io.StringIO()):
            status = cli_entry.main(['play', str(self.video)])
        self.assertEqual(status, 0)
        startfile.assert_called_once_with(str(self.video))


if __name__ == '__main__':
    unittest.main()
