"""Isolated regressions for the six audit findings. No real model or user-resource writes."""
from contextlib import ExitStack
import json
import io
import os
from pathlib import Path
import tempfile
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from video_parser.services import library, media_validation, model_calls, ai_analysis, ai_settings, workflows, transcription, translations, task_runtime, naming
from video_parser.web import task_routes, routes
from tests.offline import test_translation_status as translation_fixture


class ModelBindingTests(unittest.TestCase):
    def test_api_guard_blocks_endpoint_model_provider_and_budget_changes(self):
        config = {'base_url': 'https://a.invalid/v1', 'model': 'a', 'provider': 'custom', 'startup': {'context_size': 8192}, 'api_key': 'not-persisted'}
        signature = model_calls.api_binding(config)
        self.assertNotIn('not-persisted', signature)
        for field, value in [('base_url', 'https://b.invalid/v1'), ('model', 'b'), ('provider', 'other'), ('startup', {'context_size': 4096})]:
            with self.subTest(field=field), patch.object(ai_analysis, 'call_model') as call:
                with model_calls.bound_api(signature), self.assertRaises(model_calls.ConfigurationChanged):
                    model_calls.call([], {**config, field: value}, {'engine': 'api'}, Path('.'))
                call.assert_not_called()
        with model_calls.bound_api(signature), patch.object(ai_analysis, 'call_model', return_value=('ok', {})) as call:
            self.assertEqual(model_calls.call([], config, {'engine': 'api'}, Path('.')).text, 'ok')
            call.assert_called_once()

    def test_queued_translation_fails_before_sending_to_changed_service(self):
        fixture = translation_fixture.TranslationStatusTests('test_archive_restores_translation_without_task_and_learning_lists_chinese')
        fixture.setUp()
        try:
            config = {'provider': 'custom', 'base_url': 'https://a.invalid/v1', 'model': 'a'}
            with patch.object(ai_settings, 'current', return_value=config), patch.object(task_runtime, 'submit'):
                initial = translations.start(fixture.reference, 'zh', True)
            fixture.ids.append(initial['id']); job = transcription.get(initial['id'])
            with patch.object(ai_settings, 'current', return_value={**config, 'model': 'b', 'base_url': 'https://b.invalid/v1'}):
                translations.worker(job)
            fixture.model.assert_not_called()
            self.assertEqual((job.state, job.error_code), ('failed', 'model_config_changed'))
            self.assertIn('重新提交', job.message)
            self.assertEqual(job.files, {})
        finally: fixture.doCleanups()

    def test_queued_naming_plan_binds_before_proposal(self):
        config = {'provider': 'custom', 'model': 'a', 'base_url': 'https://a.invalid'}
        inventory = {'title': 'fixture', 'fingerprint': 'unchanged', 'entries': [{'project_id': 'p', 'files': ['video'], 'transcript': 'fixture.srt'}]}
        plans = {}
        with patch.object(naming.names, 'inventory', return_value=inventory), patch.object(naming.names, 'history', return_value=[]), patch.object(model_calls, 'require', return_value={'engine': 'api'}), patch.object(ai_settings, 'current', return_value=config), patch.object(naming.names, 'save_plan', side_effect=lambda p: plans.update({p['id']: p})), patch.object(naming, 'jobs', {}), patch.object(naming.library, 'get', return_value={'platform': 'local', 'title': 'fixture'}), patch.object(naming.names, 'load_plan', side_effect=plans.__getitem__), patch.object(task_runtime, 'submit'):
            naming.start_plan('p', True)
        plan = next(iter(plans.values()))
        self.assertEqual(plan['api_binding'], model_calls.api_binding(config))
        with patch.object(naming.names, 'inventory', return_value=inventory), patch.object(ai_settings, 'current', return_value={**config, 'model': 'b'}), patch.object(model_calls, 'call') as call:
            with self.assertRaises(model_calls.ConfigurationChanged): naming.propose(plan, Path('.'))
            call.assert_not_called()

    def test_child_entrypoint_enforces_binding_and_returns_actionable_error(self):
        from video_parser.integrations import workflow_worker
        config = {'provider': 'custom', 'model': 'a', 'base_url': 'https://a.invalid'}
        with tempfile.TemporaryDirectory(prefix='vp-bound-worker-') as root:
            directory = Path(root) / 'task'; directory.mkdir(); (directory / '.task-owner.json').write_text('{}')
            payload = {'directory': str(directory), 'api_binding': model_calls.api_binding(config)}
            with patch.object(workflows, 'CACHE_ROOT', Path(root)), patch.object(workflow_worker.videos, 'load_environment'), patch('sys.stdin', io.StringIO(json.dumps(payload))), patch.object(workflow_worker, 'execute', side_effect=lambda p: model_calls.call([], {**config, 'model': 'b'}, {'engine': 'api'}, directory)), patch.object(ai_analysis, 'call_model') as call:
                self.assertEqual(workflow_worker.main(), 1)
                call.assert_not_called()
            result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
            self.assertFalse(result['ok']); self.assertEqual(result['error_code'], 'model_config_changed')
            self.assertIn('重新提交', result['message'])
        self.assertIsNone(model_calls._api_binding.get())

    def test_workflow_binds_api_without_mutating_input_or_persisting_keys(self):
        data = {'model': 'a', 'provider': 'custom', 'base_url': 'https://a.invalid', 'api_key': 'private-key'}
        payload = {'agent': {'engine': 'api'}, 'resource': 'videos/test.mp4'}
        with patch.object(workflows, 'jobs', {}), patch.object(task_runtime, 'submit') as submit, patch.object(ai_settings, 'current', return_value=data):
            row = workflows.start('analysis', 'p', 'fixture', payload)
            job = workflows.jobs[row['id']]
            self.assertEqual(job.payload['api_binding'], model_calls.api_binding(data))
            self.assertNotIn('api_binding', payload)
            self.assertNotIn('private-key', json.dumps(job.payload))
            submit.assert_called_once()


class TaskWindowTests(unittest.TestCase):
    def test_old_active_jobs_survive_one_hundred_recent_completed_jobs(self):
        jobs = [SimpleNamespace(id=f'{n:032x}', kind='video', project_id=None, state=('running' if n == 1 else 'queued' if n == 2 else 'completed'), created=n) for n in range(1, 115)]
        indexed = {job.id: job for job in jobs}
        service = SimpleNamespace(jobs=indexed, lock=Lock(), get=indexed.__getitem__, view=lambda job: vars(job) | {'title': 'fixture'})
        with patch.object(task_routes, 'catalog', return_value={'workflows': (service, Path('unused'))}), patch.object(task_runtime, 'recent_ids', return_value=[]):
            rows = task_routes.tasks()['jobs']
        self.assertEqual(len(rows), 102)
        self.assertEqual(sum(r['state'] in task_runtime.ACTIVE for r in rows), 2)
        self.assertEqual(sum(r['state'] == 'completed' for r in rows), 100)
        self.assertEqual([r['created'] for r in rows], sorted([r['created'] for r in rows], reverse=True))


class MediaValidationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='vp-media-cache-中文-'); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.patches = ExitStack(); self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(library, 'LIBRARY_ROOT', self.root / 'library'))
        self.patches.enter_context(patch.object(media_validation, '_cache', __import__('collections').OrderedDict()))
        self.project = library.ensure({'platform': 'local', 'video_id': 'cache-fixture', 'title': 'fixture'})
        source = self.root / 'source.mp4'; source.write_bytes(b'v' * (1024 * 1024))
        self.key = library.import_file(self.project['id'], source, 'videos/fixture.mp4', 'video', {'media': {'format': {'duration': '20', 'format_name': 'mp4'}, 'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1280, 'height': 720}, {'codec_type': 'audio', 'codec_name': 'aac'}]}})
        self.project = library.get(self.project['id']); self.path = library.resource_path(self.project, self.key)

    def test_repeated_range_requests_only_hash_once(self):
        app = FastAPI(); app.include_router(routes.router)
        with TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234)) as client, patch.object(library, 'digest', wraps=library.digest) as digest:
            for _ in range(3):
                result = client.get(f'/api/workspace/projects/{self.project["id"]}/files/{self.key}', headers={'Range': 'bytes=0-15'})
                self.assertEqual(result.status_code, 206); self.assertEqual(result.content, b'v' * 16)
        self.assertEqual(digest.call_count, 1)

    def test_same_size_edit_even_with_restored_mtime_invalidates(self):
        media_validation.resource(self.project, self.key)
        before = self.path.stat()
        with self.path.open('r+b') as stream: stream.write(b'x')
        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(ValueError): media_validation.resource(self.project, self.key)

    def test_size_change_deletion_and_path_escape_rejected(self):
        media_validation.resource(self.project, self.key)
        self.path.write_bytes(b'changed')
        with self.assertRaises(ValueError): media_validation.resource(self.project, self.key)
        self.path.unlink()
        with self.assertRaises(OSError): media_validation.resource(self.project, self.key)
        with self.assertRaises(KeyError): media_validation.resource(self.project, '../../secret')

    def test_replacement_and_changed_manifest_invalidate(self):
        media_validation.resource(self.project, self.key)
        replacement = self.path.with_name('replacement.mp4'); replacement.write_bytes(b'x' * self.path.stat().st_size)
        os.replace(replacement, self.path)
        with self.assertRaises(ValueError): media_validation.resource(self.project, self.key)
        self.project['resources'][self.key]['sha256'] = library.digest(self.path)
        self.assertEqual(media_validation.resource(self.project, self.key), self.path)

    def test_ttl_and_identity_failure_fall_back_to_full_verification(self):
        with patch.object(library, 'digest', wraps=library.digest) as digest:
            media_validation.resource(self.project, self.key)
            with patch.object(media_validation, 'TTL', 0): media_validation.resource(self.project, self.key)
            with patch.object(media_validation, 'identity', return_value=None): media_validation.resource(self.project, self.key)
            self.assertEqual(digest.call_count, 3)

    def test_change_while_hashing_is_not_cached(self):
        before = media_validation.identity(self.path)
        with patch.object(media_validation, 'identity', side_effect=[before, (*before[:-1], before[-1]+1)]):
            with self.assertRaises(ValueError): media_validation.resource(self.project, self.key)
        self.assertFalse(media_validation._cache)

    def test_rename_uses_current_path_and_cache_has_bound(self):
        media_validation.resource(self.project, self.key)
        renamed = self.path.with_name('1.2 新标题.mp4'); self.path.rename(renamed)
        self.project['resources'][self.key]['storage_path'] = 'videos/' + renamed.name
        self.assertEqual(media_validation.resource(self.project, self.key), renamed)
        with patch.object(media_validation, 'MAX_ENTRIES', 1):
            for index in range(3):
                key = library.import_file(self.project['id'], self.root / 'source.mp4', f'videos/other-{index}.mp4', 'video')
                media_validation.resource(library.get(self.project['id']), key)
                self.assertEqual(len(media_validation._cache), 1)
        self.project['resources'][self.key]['storage_path'] = '../secret.mp4'
        with self.assertRaises(ValueError): media_validation.resource(self.project, self.key)


if __name__ == '__main__': unittest.main()
