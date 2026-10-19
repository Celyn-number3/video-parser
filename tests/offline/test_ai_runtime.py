"""Model start/state contract. Every process spawn is mocked; private settings are untouched."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import tempfile
import os
import subprocess
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from video_parser.services import ai_runtime, ai_settings, ai_startup
from video_parser.web.app import app


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ai-runtime-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('server.exe', 'model.gguf', 'vision.gguf'):
            (self.root / name).write_bytes(b'fixture')
        self.config = ai_startup.normalize({'server_path': str(self.root / 'server.exe'), 'model_path': str(self.root / 'model.gguf'),
                                            'vision_path': str(self.root / 'vision.gguf'), 'port': 18987})
        patches = [patch.object(ai_settings, 'SETTINGS_PATH', self.root / 'settings.json'),
                   patch.object(ai_runtime, '_process', None), patch.object(ai_runtime, '_identity', None),
                   patch.object(ai_runtime, '_started', 0), patch.object(ai_runtime, '_log_path', None),
                   patch.object(ai_runtime, 'LOG_ROOT', self.root / 'logs'), patch.object(ai_startup, 'occupied', return_value=False),
                   patch.object(ai_startup, 'same_running_model', return_value=False)]
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        ai_settings.save('llamacpp', ai_startup.endpoint(self.config), 'fixture-vl', startup=self.config)
        self.child = SimpleNamespace(poll=lambda: None, returncode=None)
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))

    def test_get_status_never_starts_a_process_and_disconnected_model_can_start(self):
        with patch.object(ai_runtime, 'Popen', return_value=self.child) as spawn:
            self.assertEqual(ai_runtime.status()['state'], 'stopped')
            spawn.assert_not_called()
            response = self.client.post('/api/workspace/ai/runtime/start', json={'confirm': True})
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()['state'], 'starting')
            self.assertEqual(ai_runtime.status()['state'], 'starting')
            args, options = spawn.call_args
            token = ai_settings.current()['api_key']
            self.assertNotIn(token, ' '.join(args[0]))
            self.assertEqual(options['env']['LLAMA_API_KEY'], token)
            self.assertFalse(options['shell'])
            self.assertNotIn(token, response.text)
            with patch.object(ai_startup, 'occupied', return_value=True), patch.object(ai_startup, 'same_running_model', return_value=True):
                self.assertEqual(ai_runtime.status()['state'], 'running')

    def test_hidden_console_uses_background_flags_private_logs_and_keeps_token_out_of_args(self):
        config = {**self.config, 'show_console': False}
        ai_settings.save('llamacpp', ai_startup.endpoint(config), 'fixture-vl', startup=config)
        with patch.object(ai_runtime, 'Popen', return_value=self.child) as spawn:
            result = ai_runtime.start()
            options = spawn.call_args.kwargs
            self.assertIn('后台加载', result['message'])
            if os.name == 'nt': self.assertEqual(options['creationflags'], subprocess.CREATE_NO_WINDOW)
            self.assertEqual(options['stderr'], subprocess.STDOUT)
            self.assertTrue(options['stdout'].closed)
            self.assertTrue(ai_runtime._log_path.is_file())
            token = ai_settings.current()['api_key']
            self.assertNotIn(token, str(spawn.call_args.args))
            self.assertNotIn(token, str(result))
            changed = {**config, 'show_console': True}
            ai_settings.save('llamacpp', ai_startup.endpoint(changed), 'fixture-vl', startup=changed)
            self.assertEqual(ai_runtime.status()['state'], 'starting')
            ai_runtime.start(); spawn.assert_called_once()

    def test_concurrent_start_is_idempotent_and_does_not_launch_duplicates(self):
        with patch.object(ai_runtime, 'Popen', return_value=self.child) as spawn:
            with ThreadPoolExecutor(max_workers=4) as pool:
                states = list(pool.map(lambda _: ai_runtime.start()['state'], range(8)))
            self.assertEqual(states, ['starting'] * 8)
            spawn.assert_called_once()

    def test_existing_service_is_reused_but_other_service_is_not_killed(self):
        with patch.object(ai_startup, 'occupied', return_value=True), patch.object(ai_runtime, 'Popen') as spawn:
            with patch.object(ai_startup, 'same_running_model', return_value=True):
                self.assertEqual(ai_runtime.start()['state'], 'running')
            with self.assertRaises(BlockingIOError): ai_runtime.start()
            spawn.assert_not_called()

    def test_exit_and_spawn_error_are_visible_and_retry_is_available(self):
        with patch.object(ai_runtime, 'Popen', return_value=self.child): ai_runtime.start()
        self.child.returncode = 7
        self.child.poll = lambda: 7
        self.assertEqual(ai_runtime.status()['state'], 'failed')
        with patch.object(ai_runtime, 'Popen', side_effect=OSError('fixture-private-detail')):
            with self.assertRaisesRegex(RuntimeError, '无法启动') as error: ai_runtime.start()
            self.assertNotIn('fixture-private-detail', str(error.exception))
        next_child = SimpleNamespace(poll=lambda: None, returncode=None)
        with patch.object(ai_runtime, 'Popen', return_value=next_child):
            self.assertEqual(ai_runtime.start()['state'], 'starting')

    def test_changed_configuration_cannot_spawn_while_previous_owned_model_runs(self):
        with patch.object(ai_runtime, 'Popen', return_value=self.child) as spawn:
            ai_runtime.start()
            changed = {**self.config, 'port': 18986}
            ai_settings.save('llamacpp', ai_startup.endpoint(changed), 'fixture-vl', startup=changed)
            self.assertEqual(ai_runtime.status()['state'], 'occupied')
            with self.assertRaises(BlockingIOError): ai_runtime.start()
            spawn.assert_called_once()

    def test_missing_files_are_rejected_without_launch_or_settings_mutation(self):
        (self.root / 'model.gguf').unlink()
        before = ai_settings.SETTINGS_PATH.read_bytes()
        with patch.object(ai_runtime, 'Popen') as spawn:
            response = self.client.post('/api/workspace/ai/runtime/start', json={'confirm': True})
            self.assertEqual(response.status_code, 400)
            spawn.assert_not_called()
        self.assertEqual(before, ai_settings.SETTINGS_PATH.read_bytes())

    def test_http_start_requires_explicit_confirmation_and_same_origin_no_command_input(self):
        with patch.object(ai_runtime, 'Popen') as spawn:
            for payload in [{}, {'confirm': False}, {'confirm': 1}, {'confirm': True, 'command': 'unsafe'}]:
                response = self.client.post('/api/workspace/ai/runtime/start', json=payload)
                self.assertEqual(response.status_code, 422, response.text)
            foreign = self.client.post('/api/workspace/ai/runtime/start', json={'confirm': True}, headers={'Origin': 'https://outside.invalid'})
            self.assertEqual(foreign.status_code, 403)
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
