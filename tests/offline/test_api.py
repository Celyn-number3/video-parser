"""Offline checks for the only supported HTTP entrypoint."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from video_parser.web import app as api
class APIEntrypointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.frontend = Path(temporary.name) / 'frontend'
        self.frontend.mkdir()
        patcher = patch.object(api, 'FRONTEND_DIR', self.frontend)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(api.app, base_url='http://127.0.0.1:15001',
                                 client=('127.0.0.1', 12345))

    def test_health_remains_available(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'healthy')
        self.assertIsInstance(response.json()['timestamp'], int)

    def test_workspace_routes_are_registered(self):
        paths = set(api.app.openapi()['paths'])
        self.assertIn('/api/workspace/config', paths)
        self.assertIn('/api/workspace/parse', paths)

    def test_signed_legacy_routes_are_removed(self):
        for endpoint in ('/api/parse', '/api/download', '/api/login', '/api/ranking'):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.post(endpoint, json={'text': 'invalid'}).status_code, 404)

    def test_root_reports_missing_frontend_without_starting_old_ui(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('frontend not built', response.json()['message'])

    def test_root_serves_built_frontend_with_no_cache(self):
        (self.frontend / 'index.html').write_text('<!doctype html><title>workspace</title>', encoding='utf-8')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<title>workspace</title>', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-cache')

    def test_workspace_keeps_cross_origin_rejection(self):
        response = self.client.get('/api/workspace/config', headers={'Origin': 'https://external.invalid'})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('access-control-allow-origin', response.headers)


if __name__ == '__main__':
    unittest.main()
