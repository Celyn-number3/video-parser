"""Offline regressions: the GPU process is the only mocked boundary."""
from video_parser import cli as cli_entry
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from video_parser.services import videos as cli
from video_parser.services import library as library
from video_parser.web import routes as workspace
class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('video_parser.services.transcription'), '本机转录模块尚未实现')
        from video_parser.services import transcription
        self.t = transcription
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tool = self.root / 'whisper'
        for name in ('.venv/Scripts/python.exe', 'cli.py', 'models/large-v3-turbo/model.bin'):
            path = self.tool / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        for name, value in (('TOOL_ROOT', self.tool), ('OUTPUT_ROOT', self.root / 'outputs'),
                            ('UPLOAD_ROOT', self.root / 'uploads')):
            patch.object(self.t, name, value).start()
        patch.object(library, 'LIBRARY_ROOT', self.root / 'library').start()
        self.addCleanup(patch.stopall)
        self.t.jobs.clear()
        self.source = self.root / '会议 & sample.wav'
        self.source.write_bytes(b'audio')
        self.actual_run_whisper = self.t.run_whisper
        self.process = patch.object(self.t, 'run_whisper', side_effect=self.whisper).start()
        app = FastAPI()
        app.include_router(workspace.router)
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))

    def whisper(self, command, **kwargs):
        source = Path(command[command.index('transcribe') + 1])
        directory = Path(command[command.index('--output-dir') + 1])
        directory.mkdir(parents=True, exist_ok=True)
        data = {'text': '你好，世界。', 'language': 'zh', 'segments': [
            {'start': 0.0, 'end': 1.5, 'text': '你好，世界。'}]}
        (directory / (source.stem + '.json')).write_text(json.dumps(data), encoding='utf-8')
        (directory / (source.stem + '.txt')).write_text(data['text'], encoding='utf-8')
        (directory / (source.stem + '.srt')).write_text('1\n00:00:00,000 --> 00:00:01,500\n你好，世界。\n', encoding='utf-8')
        return subprocess.CompletedProcess(command, 0, stderr='模型加载完成')

    def finish(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        identifier = response.json()['id']
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.client.get('/api/workspace/transcriptions/' + identifier).json()
            if result['state'] not in ('queued', 'running'):
                return result
            time.sleep(.01)
        self.fail('转录任务未结束')

    def upload(self, data=b'audio', filename='会议.wav', **kwargs):
        return self.client.post('/api/workspace/transcriptions/upload',
            params={'filename': filename, 'language': 'auto'}, content=data,
            headers={'Content-Type': 'application/octet-stream', **kwargs})

    def test_cli_registration_and_no_shell(self):
        args = cli_entry.build_parser().parse_args(['transcribe', str(self.source), '--language', 'auto'])
        result = cli_entry.execute(args)
        self.assertEqual(result['text'], '你好，世界。')
        self.assertEqual(result['language'], 'zh')
        self.assertEqual(len(result['files']), 2)
        command = self.process.call_args.args[0]
        self.assertIn(str(self.source.resolve()), command)
        self.assertIn('txt,srt,json', command)
        self.assertNotIn('--overwrite', command)
        self.assertFalse(self.process.call_args.kwargs.get('shell', False))
        self.assertTrue(cli.capabilities()['speech_transcription'])
        self.assertTrue(cli.doctor()['transcription_ready'])

    def test_rejects_bad_language_missing_input_and_overwrite_before_process(self):
        with self.assertRaises(ValueError): self.t.transcribe(self.source, language='fr')
        with self.assertRaises(FileNotFoundError): self.t.transcribe(self.root / 'missing.wav')
        output = self.root / 'export'
        output.mkdir()
        preserved = output / (self.source.stem + '.txt')
        preserved.write_text('保留', encoding='utf-8')
        with self.assertRaises(FileExistsError): self.t.transcribe(self.source, output_dir=output)
        self.assertEqual(preserved.read_text(encoding='utf-8'), '保留')
        self.process.assert_not_called()

    def test_uploaded_file_result_and_private_downloads(self):
        result = self.finish(self.upload())
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['language'], 'zh')
        self.assertEqual(result['title'], '会议.wav')
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertFalse(list(self.t.UPLOAD_ROOT.rglob('*.wav')))
        self.assertEqual([file['format'] for file in result['files']], ['txt', 'srt'])
        for file in result['files']:
            response = self.client.get(file['url'])
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment', response.headers['content-disposition'])
            self.assertEqual(response.headers['cache-control'], 'private, no-store')
        bad = f"/api/workspace/transcriptions/{result['id']}/files/json"
        self.assertEqual(self.client.get(bad).status_code, 404)

    def test_upload_validation_and_cross_origin(self):
        self.assertEqual(self.upload(b'').status_code, 400)
        self.assertEqual(self.upload(filename='../secret.wav').status_code, 400)
        self.assertEqual(self.upload(filename='program.exe').status_code, 400)
        self.assertEqual(self.upload(Origin='https://evil.example').status_code, 403)
        with patch.object(self.t, 'MAX_UPLOAD_BYTES', 3):
            self.assertEqual(self.upload(b'abcd').status_code, 413)
            self.assertEqual(self.upload(b'abcd', **{'Content-Length': '1'}).status_code, 413)
        self.process.assert_not_called()

    def test_legacy_json_only_rule_stays_intact(self):
        response = self.client.post('/api/workspace/parse', content='x', headers={'Content-Type': 'application/octet-stream'})
        self.assertEqual(response.status_code, 415)

    def test_missing_tool_is_actionable(self):
        (self.tool / 'cli.py').unlink()
        self.assertEqual(self.upload().status_code, 503)
        self.assertFalse(self.t.available())
        self.process.assert_not_called()

    def test_process_failure_and_timeout_never_publish_partial_results(self):
        self.process.side_effect = None
        self.process.return_value = subprocess.CompletedProcess([], 1, stderr='CUDA out of memory ' + str(self.source))
        result = self.finish(self.upload())
        self.assertEqual(result['state'], 'failed')
        self.assertIn('显存', result['message'])
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(result['files'], [])
        self.process.side_effect = subprocess.TimeoutExpired('whisper', 1)
        result = self.finish(self.upload())
        self.assertEqual(result['state'], 'failed')
        self.assertIn('超时', result['message'])

    def test_malformed_segments_fail_validation(self):
        def invalid(command, **kwargs):
            result = self.whisper(command, **kwargs)
            directory = Path(command[command.index('--output-dir') + 1])
            path = next(directory.glob('*.json'))
            data = json.loads(path.read_text(encoding='utf-8'))
            data['segments'][0]['end'] = -1
            path.write_text(json.dumps(data), encoding='utf-8')
            return result
        self.process.side_effect = invalid
        result = self.finish(self.upload())
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['files'], [])

    def test_silent_audio_is_not_reported_as_recognized_speech(self):
        def silence(command, **kwargs):
            result = self.whisper(command, **kwargs)
            directory = Path(command[command.index('--output-dir') + 1])
            next(directory.glob('*.json')).write_text('{"text":"","language":"en","segments":[]}', encoding='utf-8')
            for extension in ('*.txt', '*.srt'): next(directory.glob(extension)).write_text('', encoding='utf-8')
            return result
        self.process.side_effect = silence
        result = self.finish(self.upload())
        self.assertEqual(result['state'], 'empty')
        self.assertIn('未识别', result['message'])
        self.assertEqual(result['files'], [])

    def test_video_uses_exact_registered_resource_and_archives_outputs(self):
        project = library.ensure({'platform': '抖音', 'video_id': '123', 'title': '测试视频'})
        name = library.import_file(project['id'], self.source, 'videos/720p.mp4', 'video')
        response = self.client.post('/api/workspace/transcriptions', json={
            'project_id': project['id'], 'resource': name, 'language': 'en'})
        result = self.finish(response)
        self.assertEqual(result['state'], 'completed')
        resources = library.get(project['id'])['resources']
        saved = [item for item in resources.values() if item['kind'] == 'transcription']
        self.assertEqual(len(saved), 2)
        self.assertTrue(all(item['video_resource'] == name for item in saved))
        command = self.process.call_args.args[0]
        self.assertEqual(command[command.index('--language') + 1], 'en')
        for invalid in ('../../secret.wav', 'not-registered.mp4'):
            response = self.client.post('/api/workspace/transcriptions', json={
                'project_id': project['id'], 'resource': invalid})
            self.assertEqual(response.status_code, 404)

    def test_registered_nonvideo_is_rejected_and_changed_file_is_not_served(self):
        project = library.local_project(self.source)
        name = library.import_file(project['id'], self.source, 'cover.png', 'cover')
        response = self.client.post('/api/workspace/transcriptions', json={
            'project_id': project['id'], 'resource': name})
        self.assertEqual(response.status_code, 400)
        result = self.finish(self.upload())
        path = self.t.download_file(result['id'], 'txt')
        path.write_text('changed', encoding='utf-8')
        self.assertEqual(self.client.get(result['files'][0]['url']).status_code, 404)

    def test_cli_and_web_share_the_same_gpu_lock(self):
        entered, release, second_entered = Event(), Event(), Event()
        counter = [0]
        def slow(command, **kwargs):
            counter[0] += 1
            if counter[0] == 1:
                entered.set()
                if not release.wait(5): raise RuntimeError('Fixture timed out')
            else:
                second_entered.set()
            return self.whisper(command, **kwargs)
        self.process.side_effect = slow
        response = self.upload()
        self.assertTrue(entered.wait(5))
        results, errors = [], []
        def cli_task():
            try: results.append(self.t.transcribe(self.source))
            except Exception as error: errors.append(error)
        thread = Thread(target=cli_task)
        thread.start()
        try:
            self.assertFalse(second_entered.wait(.15), 'CLI entered GPU while web was running')
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors, errors)
        self.assertEqual(len(results), 1)
        self.assertEqual(self.finish(response)['state'], 'completed')
        self.assertTrue(second_entered.is_set())

    def test_different_files_can_share_explicit_output_directory_without_log_collisions(self):
        other = self.root / '另一段.wav'
        other.write_bytes(b'audio')
        output = self.root / 'shared'
        self.t.transcribe(self.source, output_dir=output)
        result = self.t.transcribe(other, output_dir=output)
        self.assertEqual(result['text'], '你好，世界。')
        self.assertEqual(len(list(output.glob('*.whisper.log'))), 2)
        with self.assertRaises(FileExistsError): self.t.transcribe(other, output_dir=output)

    def test_job_capacity_expiry_and_completed_outputs_are_preserved(self):
        with patch.object(self.t, 'MAX_JOBS', 0):
            self.assertEqual(self.upload().status_code, 429)
        self.assertFalse(list(self.t.UPLOAD_ROOT.rglob('*.wav')))
        result = self.finish(self.upload())
        path = self.t.download_file(result['id'], 'txt')
        job = self.t.jobs[result['id']]
        job.created_at -= self.t.JOB_TTL + 1
        restored=self.client.get('/api/workspace/transcriptions/'+job.id)
        self.assertEqual(restored.status_code,200)
        self.assertEqual(restored.json()['state'],'completed')
        self.assertEqual(self.client.get(result['files'][0]['url']).status_code,200)
        self.assertTrue(path.is_file())

    def test_public_download_rejects_relocated_output(self):
        result = self.finish(self.upload())
        secret = self.root / 'secret.txt'
        secret.write_text('private', encoding='utf-8')
        self.t.jobs[result['id']].files['txt'] = {'path': secret, 'sha256': library.digest(secret), 'relative': None}
        self.assertEqual(self.client.get(result['files'][0]['url']).status_code, 404)


    def test_timeout_stops_the_owned_windows_process_tree(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.communicate.return_value=(None,'timeout')
        process.poll.return_value = None
        process.pid = 12345
        command = ['python', 'whisper']
        with patch.object(self.t.subprocess, 'Popen', return_value=process) as launch, \
                patch.object(self.t.subprocess, 'run') as kill_tree, \
                patch('video_parser.services.task_runtime.time.monotonic',side_effect=[0,7201]):
            with self.assertRaises(subprocess.TimeoutExpired): self.actual_run_whisper(command)
        launch.assert_called_once()
        self.assertFalse(launch.call_args.kwargs.get('shell', False))
        if self.t.os.name == 'nt':
            kill_tree.assert_called_once_with(['taskkill', '/PID', '12345', '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 1)



if __name__ == '__main__':
    unittest.main()
