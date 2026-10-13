from pathlib import Path
import unittest
import subprocess
import sys
import tempfile
import os
import json

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / 'skills' / 'vedio-download' / 'scripts' / 'video_download.py'


class SkillLauncherTests(unittest.TestCase):
    def test_launcher_runs_project_cli_from_any_directory(self):
        environment = dict(os.environ)
        environment.pop('VIDEO_PARSER_ROOT', None)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(WRAPPER), 'capabilities', '--json'],
                                    cwd=directory, env=environment, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])

    def test_skill_reference_exposes_transcribe_and_keeps_link_confirmation(self):
        skill = (ROOT / 'skills/vedio-download/SKILL.md').read_text(encoding='utf-8')
        reference = (ROOT / 'skills/vedio-download/references/cli.md').read_text(encoding='utf-8')
        self.assertIn('transcribe', skill)
        self.assertIn('transcribe', reference)
        self.assertIn('transcription_ready', reference)
        self.assertIn('先展示功能菜单', skill)
        self.assertIn('默认自动检测', reference)

    def test_missing_project_does_not_install_or_search(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, VIDEO_PARSER_ROOT=directory)
            result = subprocess.run([sys.executable, str(WRAPPER), 'download', 'https://example.com'],
                                    env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('cli.py', result.stderr)

    def test_exact_argument_transport_and_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'cli.py').write_text("import sys,json;print(json.dumps(sys.argv[1:],ensure_ascii=False));sys.exit(7)", encoding='utf-8')
            env = dict(os.environ, VIDEO_PARSER_ROOT=directory)
            args = ['download', '分享 https://b23.tv/test?p=2&x=abc', '--output', str(Path(directory) / '空 格.mp4')]
            result = subprocess.run([sys.executable, str(WRAPPER), *args], env=env,
                                    capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(result.stdout), args)


if __name__ == '__main__':
    unittest.main()
