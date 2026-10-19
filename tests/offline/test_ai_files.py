"""Native selection contract with a fake PowerShell process; no GUI, settings write or model launch."""
import base64
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from video_parser.services import ai_files, ai_runtime, ai_settings, ai_startup, folders
from video_parser.web.app import app


class FilePickerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="model-picker-中文 ' ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "模型 ' one.gguf"; self.model.write_bytes(b'fixture')
        self.server = self.root / 'llama-server.exe'; self.server.write_bytes(b'fixture')
        for item in [patch.object(ai_settings, 'SETTINGS_PATH', self.root / 'settings.json'), patch.object(ai_files.sys, 'platform', 'win32')]:
            item.start(); self.addCleanup(item.stop)
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))

    def output(self, path):
        return SimpleNamespace(returncode=0, stdout=base64.b64encode(str(path).encode('utf-8')).decode())

    def test_selects_gguf_and_exe_with_safe_native_dialog_and_never_saves_or_launches(self):
        for field, path in [('model_path', self.model), ('vision_path', self.model), ('server_path', self.server)]:
            with patch.object(ai_files, 'run', return_value=self.output(path)) as runner, patch.object(ai_runtime, 'Popen') as launch:
                response = self.client.post('/api/workspace/ai/files/pick', json={'field': field})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(Path(response.json()['path']), path.resolve())
                args, options = runner.call_args
                self.assertEqual(args[0][:3], ['powershell.exe', '-NoProfile', '-STA'])
                script = base64.b64decode(args[0][-1]).decode('utf-16-le')
                self.assertIn('OpenFileDialog', script)
                self.assertIn('$dialog.Multiselect = $false', script)
                self.assertFalse(options['shell'])
                launch.assert_not_called()
                self.assertFalse(ai_settings.SETTINGS_PATH.exists())

    def test_cancel_returns_null_and_preserves_saved_configuration(self):
        ai_settings.save('llamacpp', 'http://127.0.0.1:8888/v1', 'fixture', startup=ai_startup.DEFAULTS)
        before = ai_settings.SETTINGS_PATH.read_bytes()
        with patch.object(ai_files, 'run', return_value=SimpleNamespace(returncode=0, stdout='')):
            self.assertIsNone(ai_files.pick('model_path'))
        self.assertEqual(before, ai_settings.SETTINGS_PATH.read_bytes())

    def test_invalid_selection_and_failure_release_shared_dialog_lock(self):
        for output in [self.output(self.server), self.output(self.root / 'missing.gguf'), SimpleNamespace(returncode=0, stdout='not-base64!')]:
            with patch.object(ai_files, 'run', return_value=output), self.assertRaises(ValueError): ai_files.pick('model_path')
            self.assertFalse(folders.dialog_lock.locked())
        for exception in [subprocess.TimeoutExpired('fixture', 900), OSError('private-detail')]:
            with patch.object(ai_files, 'run', side_effect=exception), self.assertRaises(RuntimeError) as error: ai_files.pick('model_path')
            self.assertNotIn('private-detail', str(error.exception)); self.assertFalse(folders.dialog_lock.locked())
        with patch.object(ai_files, 'run', return_value=SimpleNamespace(returncode=1, stdout='private-detail')), self.assertRaises(RuntimeError): ai_files.pick('model_path')

    def test_concurrent_native_dialog_is_rejected_without_spawning(self):
        folders.dialog_lock.acquire()
        try:
            with patch.object(ai_files, 'run') as runner, self.assertRaises(BlockingIOError): ai_files.pick('vision_path')
            runner.assert_not_called()
        finally: folders.dialog_lock.release()

    def test_api_rejects_unknown_fields_commands_and_foreign_origin(self):
        with patch.object(ai_files, 'run') as runner:
            for payload in [{}, {'field': 'anything'}, {'field': 'model_path', 'command': 'unsafe'}]:
                self.assertEqual(self.client.post('/api/workspace/ai/files/pick', json=payload).status_code, 422)
            self.assertEqual(self.client.post('/api/workspace/ai/files/pick', json={'field': 'model_path'}, headers={'Origin': 'https://outside.invalid'}).status_code, 403)
            runner.assert_not_called()


if __name__ == '__main__': unittest.main()
