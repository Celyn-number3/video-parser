"""Offline checks for the desktop launcher's single-instance rule."""
from pathlib import Path
import re
import tomllib
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from video_parser import desktop
from video_parser.core import paths
from video_parser.web import app as api


class DesktopLauncherTests(unittest.TestCase):
    def test_instance_id_is_per_install_folder(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assertEqual(paths.instance_id(Path(first)), paths.instance_id(Path(first)))
            self.assertNotEqual(paths.instance_id(Path(first)), paths.instance_id(Path(second)))
        self.assertEqual(paths.instance_id(), paths.instance_id(paths.ROOT))

    def test_health_reports_instance(self):
        client = TestClient(api.app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 12345))
        self.assertEqual(client.get('/health').json()['instance'], paths.instance_id())

    def test_other_install_on_default_port_is_not_reused(self):
        replies = {'/health': {'status': 'healthy', 'instance': 'another-copy'},
                   '/api/workspace/config': {'transcription_ready': False}}
        fetch = lambda url, timeout=2.0: replies['/' + url.split('/', 3)[3]]
        busy = {desktop.PORTS[0]}
        with patch.object(desktop, 'get_json', fetch), patch.object(desktop, 'port_free', lambda port: port not in busy):
            self.assertEqual(desktop.choose_port(), (desktop.PORTS[1], False))
            replies['/health']['instance'] = paths.instance_id()
            self.assertEqual(desktop.choose_port(), (desktop.PORTS[0], True))


    def test_main_lock_covers_declared_dependencies(self):
        project = tomllib.loads((paths.ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        lock = (paths.ROOT / 'configs/requirements/windows-main.lock.txt').read_text(encoding='utf-8')
        normalise = lambda name: re.sub(r'[-_.]+', '-', name).lower()
        locked = {normalise(line.split('==')[0]) for line in lock.splitlines() if '==' in line and not line.startswith('#')}
        for requirement in project['project']['dependencies']:
            name = re.match(r'[\w.-]+', requirement).group()
            self.assertIn(normalise(name), locked, f'{name} is missing from the Windows runtime lock')

    def test_installer_matches_launcher(self):
        script = (paths.ROOT / 'scripts/installer/VideoParser.iss').read_text(encoding='utf-8-sig')
        self.assertIn(f'#define AppUserModelID "{desktop.APP_ID}"', script)
        self.assertIn(f'#define AppMutexName "{desktop.MUTEX}"', script)
        self.assertTrue(desktop.ICON.is_file())
        icon = desktop.ICON.relative_to(paths.ROOT).as_posix().replace('/', '\\')
        self.assertIn(f'#define AppIcon "{icon}"', script)
        # Upgrades wipe the program folders, never the user's data.
        upgrade = script.split('[InstallDelete]')[1].split('[Files]')[0]
        for kept in ('outputs', '.local', '.env'):
            self.assertNotIn('{app}\\' + kept + '"', upgrade)


if __name__ == '__main__':
    unittest.main()
