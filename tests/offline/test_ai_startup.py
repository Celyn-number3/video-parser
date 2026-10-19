"""Local AI launch config tests; no model process or private settings are modified."""
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from video_parser.services import ai_settings, ai_startup
from video_parser.web.app import app

ROOT = Path(__file__).resolve().parents[2]


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ai-startup-中文 空格-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(ai_settings, 'SETTINGS_PATH', self.root / '.local/ai/settings.json'),
                        patch.object(ai_startup, 'ROOT', self.root),
                        patch.dict(os.environ, {'QWEN_API_KEY': '', 'QWEN_API_BASE_URL': '', 'QWEN_MODEL_ID': ''}),
                        patch.object(ai_startup, 'occupied', return_value=False)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.config = ai_startup.normalize({'server_path': "bin/runtime's server.exe", 'model_path': "models/模型 ' one.gguf",
                                            'vision_path': 'models/vision.gguf', 'port': 18988})
        for field in ('server_path', 'model_path', 'vision_path'):
            path = self.root / self.config[field]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fake-local-file')
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))

    def save(self, config=None, **extra):
        config = config or self.config
        return ai_settings.save('llamacpp', ai_startup.endpoint(config), 'fixture-vl', startup=config, **extra)

    def test_default_paths_match_existing_install_and_save_keeps_local_token_private(self):
        self.assertEqual(ai_settings.public()['startup'], ai_startup.DEFAULTS)
        public = self.save()
        secret = ai_settings.current()['api_key']
        self.assertGreaterEqual(len(secret), 32)
        self.assertNotIn(secret, json.dumps(public))
        self.assertEqual(public['startup'], self.config)
        self.assertEqual(public['base_url'], 'http://127.0.0.1:18988/v1')
        self.save()
        self.assertEqual(ai_settings.current()['api_key'], secret)
        ai_settings.save('llamacpp', public['base_url'], 'new-alias')
        self.assertEqual(ai_settings.public()['startup'], self.config)

    def test_port_change_rotates_token_and_cloud_save_consent_preserves_launch_config(self):
        self.save()
        previous = ai_settings.current()['api_key']
        moved = {**self.config, 'port': 18989}
        self.save(moved)
        self.assertNotEqual(ai_settings.current()['api_key'], previous)
        ai_settings.save('custom', 'https://fixture.invalid/v1', 'cloud', 'fixture-cloud-token')
        self.assertEqual(ai_settings.public()['startup'], moved)
        ai_settings.remember_consent()
        self.assertEqual(ai_settings.public()['startup'], moved)
        self.assertEqual(ai_settings.current()['api_key'], 'fixture-cloud-token')

    def test_invalid_config_is_rejected_before_settings_are_written(self):
        self.save()
        before = ai_settings.SETTINGS_PATH.read_bytes()
        for patch_value in [{'port': True}, {'port': 80}, {'port': 65536}, {'threads': 0.5},
                            {'flash_attention': 'yes'}, {'show_console': 1}, {'show_console': 'false'}, {'context_size': 512},
                            {'server_path': 'bad.exe\ncommand'}, {'model_path': 'https://site.invalid/model.gguf'},
                            {'vision_path': '\\\\server\\share\\model.gguf'}, {'command': 'echo unsafe'}]:
            with self.subTest(patch_value=patch_value), self.assertRaises(ValueError):
                self.save({**self.config, **patch_value})
            self.assertEqual(ai_settings.SETTINGS_PATH.read_bytes(), before)
        with self.assertRaises(ValueError):
            ai_settings.save('llamacpp', 'http://127.0.0.1:8888/v1', 'fixture', startup=self.config)
        with self.assertRaises(ValueError):
            ai_settings.save('custom', 'https://fixture.invalid/v1', 'fixture', startup=self.config)
        self.assertEqual(ai_settings.SETTINGS_PATH.read_bytes(), before)

    def test_check_is_read_only_handles_missing_vision_and_quotes_preview(self):
        with patch.object(ai_startup.subprocess, 'run') as spawn:
            report = ai_startup.inspect(self.config, 'fixture-vl')
            self.assertTrue(report['ok'])
            self.assertIn("模型 '' one.gguf", report['command'])
            self.assertNotIn('--api-key', report['command'])
            self.assertFalse(ai_settings.SETTINGS_PATH.exists())
            text_only = ai_startup.inspect({**self.config, 'vision_path': ''}, 'fixture-vl')
            self.assertTrue(text_only['ok'])
            self.assertTrue(text_only['warnings'])
            self.assertNotIn('--mmproj', text_only['command'])
            (self.root / self.config['model_path']).unlink()
            self.assertFalse(ai_startup.inspect(self.config, 'fixture-vl')['ok'])
            spawn.assert_not_called()

    def test_pinned_size_and_hash_validation_are_not_removed_for_default_files(self):
        for field in ('server_path', 'model_path', 'vision_path'):
            p = self.root / ai_startup.DEFAULTS[field]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'bad-default-file')
        self.assertFalse(ai_startup.inspect(ai_startup.DEFAULTS, 'fixture-vl')['ok'])
        good = b'pinned-fixture'
        import hashlib
        for field in ai_startup.PINNED:
            (self.root / ai_startup.DEFAULTS[field]).write_bytes(good)
        pins = {field: (len(good), hashlib.sha256(good).hexdigest()) for field in ai_startup.PINNED}
        with patch.object(ai_startup, 'PINNED', pins):
            self.assertTrue(ai_startup.inspect(ai_startup.DEFAULTS, 'fixture-vl', True)['ok'])
            wrong = {**pins, 'model_path': (len(good), '0' * 64)}
            with patch.object(ai_startup, 'PINNED', wrong):
                self.assertFalse(ai_startup.inspect(ai_startup.DEFAULTS, 'fixture-vl', True)['ok'])

    def test_launcher_uses_argv_without_shell_and_key_only_in_child_environment(self):
        self.save()
        settings = ai_settings.current()
        config = {**self.config, 'threads': 8, 'parallel': 2, 'flash_attention': False}
        settings['startup'] = config
        before = os.environ.get('LLAMA_API_KEY')
        with patch.object(ai_startup.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as spawn:
            ai_startup.run(settings)
            args, kwargs = spawn.call_args
            argv = args[0]
            self.assertEqual(argv[0], str(self.root / config['server_path']))
            self.assertIn(str(self.root / config['model_path']), argv)
            self.assertIn('--threads', argv)
            self.assertEqual(argv[argv.index('--flash-attn') + 1], 'off')
            self.assertIn('--no-webui', argv)
            self.assertEqual(argv[argv.index('--host') + 1], '127.0.0.1')
            self.assertNotIn(settings['api_key'], ' '.join(argv))
            self.assertEqual(kwargs['env']['LLAMA_API_KEY'], settings['api_key'])
            self.assertFalse(kwargs['shell'])
        self.assertEqual(os.environ.get('LLAMA_API_KEY'), before)
        with patch.object(ai_startup.subprocess, 'run') as spawn:
            ai_startup.run(settings, check_only=True)
            spawn.assert_not_called()

    def test_occupied_port_reuses_matching_service_or_refuses_without_killing(self):
        self.save()
        with patch.object(ai_startup, 'occupied', return_value=True), patch.object(ai_startup, 'same_running_model', return_value=True):
            with patch.object(ai_startup.subprocess, 'run') as spawn:
                self.assertEqual(ai_startup.run(ai_settings.current()), 0)
                spawn.assert_not_called()
        with patch.object(ai_startup, 'occupied', return_value=True), patch.object(ai_startup, 'same_running_model', return_value=False):
            with self.assertRaisesRegex(ValueError, '未停止任何进程'):
                ai_startup.run(ai_settings.current())

    def test_http_contract_save_check_errors_and_local_origin_boundary(self):
        body = {'provider': 'llamacpp', 'base_url': ai_startup.endpoint(self.config), 'model': 'fixture-vl', 'startup': self.config}
        response = self.client.post('/api/workspace/ai/settings', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        secret = ai_settings.current()['api_key']
        self.assertNotIn(secret, response.text)
        before = ai_settings.SETTINGS_PATH.read_bytes()
        response = self.client.post('/api/workspace/ai/startup/check', json={'startup': self.config, 'model': 'fixture-vl'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['ok'])
        self.assertNotIn(secret, response.text)
        self.assertEqual(ai_settings.SETTINGS_PATH.read_bytes(), before)
        bad = self.client.post('/api/workspace/ai/settings', json={**body, 'startup': {**self.config, 'port': True}})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(ai_settings.SETTINGS_PATH.read_bytes(), before)
        remote = self.client.post('/api/workspace/ai/startup/check', headers={'Origin': 'https://outside.invalid'}, json={'startup': self.config, 'model': 'fixture-vl'})
        self.assertEqual(remote.status_code, 403)

    @unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell required')
    def test_powershell_wrapper_parses_and_checkonly_reads_saved_configuration(self):
        # Launch the real wrapper with fixture settings, but never start a model.
        self.save()
        environment = {**os.environ, 'VIDEO_PARSER_AI_SETTINGS': str(ai_settings.SETTINGS_PATH)}
        # Absolute fixture paths keep this separate process independent of the patched ROOT.
        config = {**self.config, **{field: str(self.root / self.config[field]) for field in ('server_path', 'model_path', 'vision_path')}}
        self.save(config)
        result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(ROOT / 'scripts/start-ai.ps1'), '-CheckOnly'],
                                env=environment, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        self.assertIn(b'Preflight OK', result.stdout)
        self.assertNotIn(ai_settings.current()['api_key'].encode(), result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
