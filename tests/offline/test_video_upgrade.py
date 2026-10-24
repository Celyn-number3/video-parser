"""Regression coverage for agent controls, strict material selection, planning and vector search."""
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from video_parser.services import agent_controls, local_agents, ai_analysis, ai_settings, library, embedding_search, frame_planning, workflows
from video_parser.web.app import app
from video_parser.web import analysis_routes

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        self.root = Path(self.temp.name)
        patch.object(agent_controls, 'PATH', self.root / 'agents.json').start()
        patch.object(embedding_search, 'SETTINGS_PATH', self.root / 'embeddings.json').start()
        patch.object(embedding_search, 'INDEX_ROOT', self.root / 'indexes').start()
        patch.object(library, 'LIBRARY_ROOT', self.root / 'library').start()
        self.project = library.ensure({'platform': '哔哩哔哩', 'video_id': 'BV1Fixture00', 'title': '升级验证'})
        self.pid = self.project['id']
        self.client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))

    def subtitle(self):
        path = self.root / 'fixture.srt'
        path.write_text('1\n00:00:02,000 --> 00:00:10,000\n项目排期与任务分工\n\n2\n00:01:00,000 --> 00:01:05,000\n财务报销和预算\n', encoding='utf-8')
        return library.import_file(self.pid, path, 'subtitles/fixture.srt', 'subtitle')

    def test_agent_switch_persists_and_blocks_dispatch(self):
        self.assertTrue(agent_controls.enabled('codex'))
        response = self.client.post('/api/workspace/ai/agents/enabled', json={'engine': 'codex', 'enabled': False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(next(row for row in response.json()['engines'] if row['id'] == 'codex')['enabled'])
        self.assertTrue(agent_controls.enabled('claude'))
        with patch.object(local_agents, '_runtime') as runtime, patch.object(local_agents, 'available', return_value=True):
            with self.assertRaises(local_agents.AgentError):
                local_agents.require({'engine': 'codex'})
            with self.assertRaises(local_agents.AgentError):
                local_agents.complete([], {'engine': 'codex'}, self.root)
            with self.assertRaises(local_agents.AgentError):
                local_agents.discover('codex')
            runtime.assert_not_called()
        agent_controls.save('codex', True)
        self.assertTrue(agent_controls.enabled('codex'))

    def test_agent_switch_requires_boolean_and_same_origin(self):
        for value in (1, 'true', None):
            self.assertEqual(self.client.post('/api/workspace/ai/agents/enabled', json={'engine': 'codex', 'enabled': value}).status_code, 422)
        self.assertEqual(self.client.post('/api/workspace/ai/agents/enabled', json={'engine': 'codex', 'enabled': False}, headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_invalid_agent_control_file_fails_closed(self):
        agent_controls.PATH.write_text('not json', encoding='utf-8')
        self.assertFalse(agent_controls.enabled('codex'))
        self.assertTrue(agent_controls.enabled('api'))

    def test_material_missing_rejected_before_task(self):
        entry = SimpleNamespace(project_id=self.pid)
        body = analysis_routes.AnalysisTaskBody(consent=True)
        with patch.object(workflows, 'start') as start:
            with self.assertRaises(Exception) as error:
                analysis_routes.start_analysis(entry, {}, body)
            self.assertEqual(error.exception.status_code, 400)
            self.assertIn('字幕', error.exception.detail)
            start.assert_not_called()
        ai_analysis.validate_material(self.pid, 'frames')
        for source in ('both', 'transcript'):
            with self.assertRaises(ai_analysis.AnalysisError):
                ai_analysis.validate_material(self.pid, source)
        self.subtitle()
        ai_analysis.validate_material(self.pid, 'both')

    def test_subtitle_cues_and_path_isolation(self):
        self.subtitle()
        result = self.client.get(f'/api/workspace/projects/{self.pid}/subtitle-cues')
        self.assertEqual(result.status_code, 200)
        self.assertEqual([cue['time'] for cue in result.json()['cues']], [2, 60])
        self.assertEqual(self.client.get(f'/api/workspace/projects/{self.pid}/subtitle-cues', params={'resource': '../../secret'}).status_code, 404)

    def test_ai_plan_validation(self):
        self.assertEqual(frame_planning.validate_times('[19.9999]', 20), [19.999])
        self.assertEqual(frame_planning.validate_times('[0.1008]', 0.1009), [0.100])
        self.assertEqual(frame_planning.validate_times('```json\n{"times":[12,2,12]}\n```', 20), [2, 12])
        for text in ('{}', '[]', '{"times":[true]}', '{"times":[-1]}', '{"times":[20]}', '{"times":[NaN]}', '{"times":["2"]}', json.dumps(list(range(17)))):
            with self.assertRaises(ValueError, msg=text):
                frame_planning.validate_times(text, 20)

    def test_planning_uses_subtitles_and_returns_usage(self):
        with patch.object(frame_planning.model_calls, 'call', return_value=SimpleNamespace(text='{"times":[3,9]}', usage={'prompt_tokens': 20})) as call:
            times, usage = frame_planning.plan({'body': '[00:03] 演示操作'}, 20, {}, {'engine': 'api'}, self.root)
        self.assertEqual(times, [3, 9])
        self.assertEqual(usage['prompt_tokens'], 20)
        self.assertIn('演示操作', str(call.call_args))

    def test_embedding_config_preserves_secret_and_resets_on_endpoint_change(self):
        data = embedding_search.save('https://example.test/v1', 'embed', 'private-secret')
        self.assertTrue(data['key_saved'])
        self.assertNotIn('private-secret', json.dumps(data))
        embedding_search.save('https://other.test/v1', 'embed')
        self.assertFalse(embedding_search.public()['key_saved'])
        with self.assertRaises(ValueError): embedding_search.save('http://remote.test/v1', 'embed')

    def test_embedding_rank_invalidation_and_no_stale_deleted_content(self):
        source = self.subtitle()
        embedding_search.save('http://127.0.0.1:12345/v1', 'embed')
        def fake(texts, config):
            return [[1.0, 0.0] if '排期' in text else [0.0, 1.0] for text in texts]
        with patch.object(embedding_search, 'embed', side_effect=fake):
            self.assertEqual(embedding_search.index(self.pid)['count'], 2)
            hit = embedding_search.search(self.pid, '排期怎么安排')['results'][0]
            self.assertEqual(hit['time'], 2)
            self.assertEqual(hit['part'], 1)
            self.assertEqual(hit['resource'], source)
            embedding_search.save('http://127.0.0.1:12345/v1', 'changed-model')
            with self.assertRaisesRegex(ValueError, '模型'): embedding_search.search(self.pid, '排期')
            embedding_search.save('http://127.0.0.1:12345/v1', 'embed')
            library.remove(self.pid, [source])
            with self.assertRaisesRegex(ValueError, '字幕'): embedding_search.search(self.pid, '排期')

    def test_embedding_consent_and_vector_validation(self):
        with patch.object(embedding_search, 'index') as index:
            for consent in (False, 1, 'true', None):
                self.assertEqual(self.client.post(f'/api/workspace/projects/{self.pid}/embedding/index', json={'consent': consent}).status_code, 422)
            index.assert_not_called()
        for values in ([], [0, 0], [float('nan')], [True], ['1']):
            with self.assertRaises(ValueError): embedding_search.vector(values)
        self.assertEqual(embedding_search.vector([3, 4]), [.6, .8])

    def test_real_embedding_http_protocol_against_local_fixture(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append((self.path, body))
                raw = json.dumps({'object': 'list', 'model': 'fixture', 'data': [{'object': 'embedding', 'index': i, 'embedding': [3.0, 4.0]} for i in range(len(body['input']))], 'usage': {'prompt_tokens': 2, 'total_tokens': 2}}).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            result = embedding_search.embed(['测试字幕', '测试查询'], {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'fixture', 'api_key': ''})
            self.assertEqual(result, [[.6, .8], [.6, .8]])
            self.assertEqual(calls[0][0], '/v1/embeddings')
            self.assertEqual(calls[0][1]['model'], 'fixture')
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_embedding_chunks_are_bounded(self):
        rows = embedding_search.chunks([(0, 'a' * 2500), (60, '尾部')], 'a.srt')
        self.assertTrue(all(len(row['text']) <= 800 for row in rows))
        self.assertEqual(rows[-1]['time'], 60)

    def test_episode_refresh_preserves_identity(self):
        project = library.get(self.pid)
        metadata = {'platform': '哔哩哔哩', 'video_id': 'BV1Fixture00', 'title': '平台标题', 'source_url': project['source_url'],
            'episodes': [{'part': 1, 'title': '第一集', 'duration': 20}, {'part': 2, 'title': '第二集', 'duration': 30}]}
        from video_parser.services import videos
        with patch.object(videos, 'parse_link', return_value=SimpleNamespace(metadata=metadata)) as parse:
            result = self.client.post(f'/api/workspace/projects/{self.pid}/episodes/refresh', json={'confirm': True})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()['episodes']), 2)
        self.assertFalse(parse.call_args.args[1])
        self.assertEqual(library.get(self.pid)['title'], '升级验证')

    def test_dependency_checker_rejects_missing_yt_dlp(self):
        import subprocess
        import sys
        root = Path(__file__).resolve().parents[2]
        sandbox = self.root / 'lock-check'
        (sandbox / 'scripts').mkdir(parents=True)
        (sandbox / 'configs/requirements').mkdir(parents=True)
        (sandbox / 'scripts/check-main-lock.py').write_text((root / 'scripts/check-main-lock.py').read_text(encoding='utf-8'), encoding='utf-8')
        (sandbox / 'pyproject.toml').write_text((root / 'pyproject.toml').read_text(encoding='utf-8'), encoding='utf-8')
        lock = (root / 'configs/requirements/windows-main.lock.txt').read_text(encoding='utf-8')
        (sandbox / 'configs/requirements/windows-main.lock.txt').write_text('\n'.join(line for line in lock.splitlines() if not line.startswith('yt-dlp==')), encoding='utf-8')
        result = subprocess.run([sys.executable, '-X', 'utf8', str(sandbox / 'scripts/check-main-lock.py')], capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('yt-dlp', result.stderr)

    def test_task_details_survive_payload_removal(self):
        with patch.object(workflows.task_runtime, 'submit'), patch.object(ai_settings, 'current', return_value={'model': 'test-model'}), patch.dict(workflows.jobs, clear=True):
            result = workflows.start('analysis', self.pid, 'fixture', {'template': 'chapters', 'source': 'both', 'frame_mode': 'ai'})
            job = workflows.jobs[result['id']]
            job.payload.clear()
            details = workflows.view(job)['details']
        self.assertEqual(details['template'], 'chapters')
        self.assertEqual(details['model'], 'test-model')
        self.assertNotIn('prompt', details)

if __name__ == '__main__': unittest.main()
