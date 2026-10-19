"""Synthetic NTFS-safe naming/rollback regressions. Never uses real courses or models."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from video_parser.services import ai_analysis, ai_settings, conversations, library, model_calls, naming, resource_renames as names, study, task_runtime, videos
from video_parser.web import naming_routes, routes

VIDEO_ID = 'BV1TaqYBcEJc'
MEDIA = {'format': {'duration': '20', 'format_name': 'mov,mp4,m4a,3gp,3g2,mj2'},
         'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1280, 'height': 720},
                     {'codec_type': 'audio', 'codec_name': 'aac', 'channels': 2}]}


class SubtitleNamingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vp-naming-synthetic-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch_root = patch.object(library, 'LIBRARY_ROOT', self.root / 'library')
        self.patch_root.start(); self.addCleanup(self.patch_root.stop)
        self.projects, self.resources, self.sources = [], [], []
        episodes = [{'part': index, 'title': f'合成第{index}讲', 'duration': 20} for index in (1, 2, 3)]
        for part in (1, 2, 3):
            project = library.ensure({'platform': 'bilibili', 'video_id': VIDEO_ID, 'source_url': f'https://www.bilibili.com/video/{VIDEO_ID}?p={part}',
                                      'title': '完全虚构的测试课程', 'episodes': episodes})
            self.projects.append(project)
            source = self.root / f'fixture-{part}.mp4'; source.write_bytes((f'fake-video-{part}-'.encode()) * 12)
            self.sources.append(source)
            if part < 3:
                self.resources.append(library.import_file(project['id'], source, 'videos/original.mp4', 'video', {'media': MEDIA, 'selected_quality': {'id': '720p', 'label': '720p', 'width': 1280, 'height': 720}}))
            subtitle = self.root / f'subtitle-{part}.srt'
            subtitle.write_text(f'1\n00:00:00,000 --> 00:00:03,000\n本集是第{part}讲的合成字幕，介绍变量与控制流程。\n\n2\n00:00:05,000 --> 00:00:08,000\n合成总结：学习类型与条件。\n', encoding='utf-8')
            library.import_file(project['id'], subtitle, 'subtitles/fixture.srt', 'subtitle')
        self.pid = self.projects[0]['id']; self.resource = self.resources[0]
        for template, text in [('chapters', '## 00:00 合成开场\n解释\n## 00:05 合成概念\n说明'), ('summary', '合成内容摘要')]:
            library.save_text(self.pid, 'analysis', text, {'template': template, 'video_resource': self.resource, 'source': 'transcript'})
        study.progress(self.pid, self.resource, 7, 20, 0)
        study.save_note(self.pid, self.resource, uuid4().hex, 5, '不应发送的合成个人笔记', 0)
        self.conversation = conversations.create(self.pid, self.resource)
        self.progress_before = study.load(self.pid, self.resource)
        self.notes_before = study.notes(self.pid, self.resource)

    def plan(self):
        inventory = names.inventory(self.pid)
        plan = {'version': 1, 'id': uuid4().hex, 'project_id': self.pid, 'title': inventory['title'], 'created_at': names.now(),
                'state': 'proposed', 'fingerprint': inventory['fingerprint'],
                'entries': [item for item in inventory['entries'] if item['files'] and item['transcript']],
                'context': [item for item in inventory['entries'] if item['transcript']], 'agent': {'engine': 'api', 'model': '', 'effort': ''},
                'rows': [{'project_id': self.projects[index]['id'], 'number': f'1.{index+1}', 'title': title}
                         for index, title in enumerate(['变量基础', '条件与类型'])], 'last_error': ''}
        names.save_plan(plan)
        return plan

    def confirmed(self):
        plan = self.plan(); preview = names.validate(plan['id'], plan['rows'])
        return plan, preview

    def reuse(self, filename='P01_1.1.01方程组的几何解释.srt'):
        library.update_details(self.pid, 'subtitles/fixture.srt', {'download_name': filename})
        result = names.reuse_subtitles(self.pid, [self.pid])
        plan = names.load_plan(result['plan_id'])
        return plan, names.validate(plan['id'], plan['rows'])

    def test_reuse_subtitle_name_without_any_model_and_restore_associations(self):
        subtitle = library.resource(self.pid, 'subtitles/fixture.srt')
        original = subtitle.read_bytes()
        with patch.object(model_calls, 'require', side_effect=AssertionError('No model selection')), \
             patch.object(model_calls, 'call', side_effect=AssertionError('No model calls')):
            plan, preview = self.reuse()
            self.assertEqual(preview['moves'][0]['target'], 'videos/P01_1.1.01方程组的几何解释.mp4')
            self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')
            names.apply(plan['id'], preview['preview_token'])
            self.assertEqual(library.resource(self.pid, self.resource).stem, 'P01_1.1.01方程组的几何解释')
            self.assertEqual(library.get(self.pid)['episode_title'], 'P01_1.1.01方程组的几何解释')
            self.assertEqual(library.public(library.get(self.pid))['resources'][0]['filename'], 'P01_1.1.01方程组的几何解释.mp4')
            self.assertEqual(study.load(self.pid, self.resource), self.progress_before)
            self.assertEqual(study.notes(self.pid, self.resource), self.notes_before)
            self.assertEqual(conversations.get(self.pid, self.conversation['id'])['video_resource'], self.resource)
            self.assertEqual(library.resource(self.pid, 'subtitles/fixture.srt'), subtitle)
            self.assertEqual(subtitle.read_bytes(), original)
            names.restore(plan['id'])
            self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')
            self.assertNotIn('episode_title', library.get(self.pid))

    def test_reuse_plain_filename_fallback_preserves_extension_and_rejects_edits(self):
        result = names.reuse_subtitles(self.pid, [self.pid])
        plan = names.load_plan(result['plan_id'])
        self.assertEqual(plan['rows'][0]['title'], 'fixture')
        preview = names.validate(plan['id'], plan['rows'])
        self.assertEqual(preview['moves'][0]['target'], 'videos/fixture.mp4')
        for row in ({**plan['rows'][0], 'title': 'not-the-subtitle'}, {**plan['rows'][0], 'number': '1'}):
            with self.assertRaises(names.NamingError): names.validate(plan['id'], [row])

    def test_reuse_changed_subtitle_download_name_invalidates_preview(self):
        plan, preview = self.reuse()
        library.update_details(self.pid, 'subtitles/fixture.srt', {'download_name': '新字幕名.srt'})
        with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')

    def test_reuse_unsafe_filename_and_collision_never_modify_video(self):
        for filename in ('../导论.srt', 'folder\\导论.srt', 'CON.srt', '标题?.srt', '标题 .srt', '标题.txt', '标\u202e题.srt'):
            with self.subTest(filename=filename):
                library.update_details(self.pid, 'subtitles/fixture.srt', {'download_name': filename})
                with self.assertRaises(names.NamingError): names.reuse_subtitles(self.pid, [self.pid])
        occupied = library.get(self.pid)['directory'] / 'videos/导论.mp4'
        occupied.write_bytes(b'preserve unrelated destination')
        with self.assertRaises(names.NamingError): self.reuse('导论.srt')
        self.assertEqual(occupied.read_bytes(), b'preserve unrelated destination')
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')

    def test_reuse_multiple_qualities_remain_distinct(self):
        library.import_file(self.pid, self.sources[0], 'videos/second.mp4', 'video', {'selected_quality': {'label': '1080p'}})
        plan, preview = self.reuse('方程组.srt')
        targets = [move['target'] for move in preview['moves']]
        self.assertEqual(len(set(targets)), 2)
        self.assertTrue(all(Path(name).stem.startswith('方程组 [') and name.endswith('.mp4') for name in targets))
        names.apply(plan['id'], preview['preview_token'])
        names.restore(plan['id'])
        self.assertTrue((library.get(self.pid)['directory'] / 'videos/second.mp4').is_file())

    def test_reuse_http_requires_preview_confirm_and_no_ai_consent(self):
        from fastapi.testclient import TestClient
        from video_parser.web.app import app
        client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))
        self.addCleanup(client.close)
        with patch.object(model_calls, 'call', side_effect=AssertionError('No model calls')):
            endpoint = f'/api/workspace/projects/{self.pid}/naming/reuse'
            self.assertEqual(client.post(endpoint, json={'selected_ids': []}).status_code, 422)
            self.assertEqual(client.post(endpoint, headers={'Origin': 'https://foreign.invalid'}, json={}).status_code, 403)
            self.assertEqual(client.post(endpoint, json={'selected_ids': [self.projects[2]['id']]}).status_code, 400)
            response = client.post(endpoint, json={'selected_ids': [self.pid]})
            self.assertEqual(response.status_code, 201, response.text)
            path = '/api/workspace/naming/plans/' + response.json()['plan_id']
            plan = client.get(path).json()
            self.assertEqual(plan['source'], 'subtitle')
            response = client.post(path + '/preview', json={'rows': plan['rows']})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['moves'][0]['target'], 'videos/fixture.mp4')
            self.assertEqual(client.post(path + '/apply', json={'confirm': False, 'preview_token': response.json()['preview_token']}).status_code, 422)
            self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')

    def test_adjust_forks_only_applied_rows_without_models_or_inherited_authority(self):
        original = self.plan()
        edited = [dict(original['rows'][0], number='2.1', title='已经确认的修订标题')]
        preview = names.validate(original['id'], edited)
        names.apply(original['id'], preview['preview_token'])
        old_record = names.plan_path(original['id']).read_bytes()
        manifests = {project['id']: (project['directory'] / 'project.json').read_bytes() for project in self.projects}
        fingerprint = names.inventory(self.pid)['fingerprint']
        with patch.object(model_calls, 'require', side_effect=AssertionError('No model selection')), \
             patch.object(model_calls, 'call', side_effect=AssertionError('No model calls')):
            result = names.adjust_plan(self.pid, original['id'])
        draft = names.load_plan(result['plan_id'])
        self.assertNotEqual(draft['id'], original['id'])
        self.assertEqual(draft['adjusted_from'], original['id'])
        self.assertEqual(draft['state'], 'proposed')
        self.assertEqual(draft['source'], 'manual')
        self.assertEqual(draft['rows'], edited)
        self.assertEqual([entry['project_id'] for entry in draft['entries']], [self.pid])
        self.assertEqual(draft['entries'][0]['files'][0]['source'], preview['moves'][0]['target'])
        self.assertEqual(draft['fingerprint'], fingerprint)
        for key in ('preview', 'preview_token', 'transaction', 'agent', 'context', 'job_id', 'active_job_id'):
            self.assertNotIn(key, draft)
        with self.assertRaises(names.NamingError): names.apply(draft['id'], preview['preview_token'])
        self.assertEqual(names.plan_path(original['id']).read_bytes(), old_record)
        self.assertEqual(names.inventory(self.pid)['fingerprint'], fingerprint)
        for project in self.projects:
            self.assertEqual((project['directory'] / 'project.json').read_bytes(), manifests[project['id']])

    def test_adjust_apply_restore_preserves_the_prior_result_and_undo_chain(self):
        original, first = self.confirmed(); names.apply(original['id'], first['preview_token'])
        draft = names.load_plan(names.adjust_plan(self.pid, original['id'])['plan_id'])
        edited = [dict(draft['rows'][0], number='2.1', title='二次修订'), draft['rows'][1]]
        second = names.validate(draft['id'], edited)
        self.assertNotEqual(second['preview_token'], first['preview_token'])
        with self.assertRaises(names.NamingError): naming.start_apply(draft['id'], second['preview_token'], False)
        with self.assertRaises(names.NamingError): names.apply(draft['id'], first['preview_token'])
        names.apply(draft['id'], second['preview_token'])
        self.assertEqual(library.resource(self.pid, self.resource).name, '2.1 二次修订.mp4')
        self.assertEqual(study.load(self.pid, self.resource), self.progress_before)
        self.assertEqual(study.notes(self.pid, self.resource), self.notes_before)
        self.assertEqual(conversations.get(self.pid, self.conversation['id'])['video_resource'], self.resource)
        names.restore(draft['id'])
        self.assertEqual(library.resource(self.pid, self.resource).name, '1.1 变量基础.mp4')
        self.assertEqual(names.load_plan(original['id'])['state'], 'applied')
        names.restore(original['id'])
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')
        self.assertNotIn('episode_title', library.get(self.pid))

    def test_adjust_subtitle_result_supports_safe_manual_titles_without_a_number(self):
        original, first = self.reuse(); names.apply(original['id'], first['preview_token'])
        draft = names.load_plan(names.adjust_plan(self.pid, original['id'])['plan_id'])
        for title in ('CON', 'nul.txt', '../越界', '含?问号', 'x' * 101, '隐藏\u202e字符'):
            with self.subTest(title=title), self.assertRaises(names.NamingError):
                names.validate(draft['id'], [dict(draft['rows'][0], title=title)])
        edited = [dict(draft['rows'][0], number='', title='字幕名的手动修订')]
        second = names.validate(draft['id'], edited)
        self.assertEqual(second['moves'][0]['target'], 'videos/字幕名的手动修订.mp4')
        names.apply(draft['id'], second['preview_token'])
        self.assertNotIn('hierarchical_name', library.get(self.pid))
        names.restore(draft['id'])
        self.assertEqual(library.resource(self.pid, self.resource).stem, 'P01_1.1.01方程组的几何解释')
        names.restore(original['id'])
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')

    def test_adjust_rejects_noncompleted_foreign_and_pending_recovery_plans(self):
        original, preview = self.confirmed(); names.apply(original['id'], preview['preview_token'])
        foreign = library.ensure({'platform': 'bilibili', 'video_id': 'BV1TaqYBcEJa', 'title': '另一组合成课程',
                                  'source_url': 'https://www.bilibili.com/video/BV1TaqYBcEJa?p=1'})
        with self.assertRaises(names.NamingError): names.adjust_plan(foreign['id'], original['id'])
        applied = names.load_plan(original['id'])
        for state in ('proposed', 'validated', 'analyzing', 'applying', 'recovery_required', 'rolled_back', 'failed'):
            changed = dict(applied, state=state); names.save_plan(changed)
            with self.subTest(state=state), self.assertRaises(names.NamingError): names.adjust_plan(self.pid, original['id'])
        names.save_plan(applied)
        pending = self.plan(); pending['state'] = 'recovery_required'; names.save_plan(pending)
        with self.assertRaises(names.NamingError): names.adjust_plan(self.pid, original['id'])
        self.assertEqual(library.resource(self.pid, self.resource).name, '1.1 变量基础.mp4')

    def test_adjust_rejects_superseded_results_and_changed_media(self):
        original, first = self.confirmed(); names.apply(original['id'], first['preview_token'])
        draft = names.load_plan(names.adjust_plan(self.pid, original['id'])['plan_id'])
        rows = [dict(draft['rows'][0], title='最新命名'), draft['rows'][1]]
        second = names.validate(draft['id'], rows); names.apply(draft['id'], second['preview_token'])
        with self.assertRaises(names.NamingError): names.adjust_plan(self.pid, original['id'])
        source = library.resource(self.pid, self.resource)
        stat = source.stat(); os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
        with self.assertRaises(names.NamingError): names.adjust_plan(self.pid, draft['id'])
        self.assertEqual(source.read_bytes(), self.sources[0].read_bytes())

    def test_adjust_draft_invalidates_if_the_parent_is_restored(self):
        original, first = self.confirmed(); names.apply(original['id'], first['preview_token'])
        draft = names.load_plan(names.adjust_plan(self.pid, original['id'])['plan_id'])
        names.restore(original['id'])
        with self.assertRaises(names.NamingError): names.validate(draft['id'], draft['rows'])
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')

    def test_adjust_http_requires_strict_body_local_origin_and_fresh_confirmation(self):
        from fastapi.testclient import TestClient
        from video_parser.web.app import app
        original, first = self.confirmed(); names.apply(original['id'], first['preview_token'])
        client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))
        self.addCleanup(client.close)
        endpoint = f'/api/workspace/projects/{self.pid}/naming/adjust'
        with patch.object(model_calls, 'require', side_effect=AssertionError('No model selection')), \
             patch.object(model_calls, 'call', side_effect=AssertionError('No model calls')):
            self.assertEqual(client.post(endpoint, json={}).status_code, 422)
            self.assertEqual(client.post(endpoint, json={'plan_id': '../escape'}).status_code, 422)
            self.assertEqual(client.post(endpoint, json={'plan_id': original['id'], 'source': 'manual'}).status_code, 422)
            self.assertEqual(client.post(endpoint, headers={'Origin': 'https://foreign.invalid'}, json={'plan_id': original['id']}).status_code, 403)
            response = client.post(endpoint, json={'plan_id': original['id']})
            self.assertEqual(response.status_code, 201, response.text)
            path = '/api/workspace/naming/plans/' + response.json()['plan_id']
            draft = client.get(path).json()
            self.assertEqual(draft['adjusted_from'], original['id'])
            self.assertEqual(draft['source'], 'manual')
            self.assertIsNone(draft['preview_token']); self.assertIsNone(draft['job_id'])
            preview = client.post(path + '/preview', json={'rows': draft['rows']})
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(client.post(path + '/apply', json={'confirm': False, 'preview_token': preview.json()['preview_token']}).status_code, 422)
            self.assertEqual(client.post(path + '/apply', json={'confirm': True, 'preview_token': first['preview_token']}).status_code, 400)
        self.assertEqual(library.resource(self.pid, self.resource).name, '1.1 变量基础.mp4')

    def test_adjust_does_not_interleave_with_an_exclusive_operation(self):
        original, first = self.confirmed(); names.apply(original['id'], first['preview_token'])
        with task_runtime.exclusive_operation(), self.assertRaises(BlockingIOError):
            names.adjust_plan(self.pid, original['id'])

    def test_preview_does_not_rename_or_change_associations(self):
        plan, preview = self.confirmed()
        self.assertEqual(len(preview['moves']), 2)
        self.assertTrue(library.resource(self.pid, self.resource).name == 'original.mp4')
        self.assertNotIn('episode_title', library.get(self.pid))
        self.assertEqual(study.load(self.pid, self.resource), self.progress_before)
        self.assertEqual(len(names.inventory(self.pid)['entries']), 3)
        self.assertEqual(names.inventory(self.pid)['ready_count'], 2)

    def test_apply_preserves_ids_subtitles_chapters_chat_notes_progress_and_quality(self):
        plan, preview = self.confirmed(); before = library.get(self.pid)
        quality = videos.archived_videos(self.pid)[0]['id']
        names.apply(plan['id'], preview['preview_token'])
        current = library.get(self.pid)
        self.assertEqual(current['id'], before['id'])
        self.assertEqual(set(current['resources']), set(before['resources']))
        self.assertEqual(current['episode_title'], '1.1 变量基础')
        self.assertEqual(library.resource(self.pid, self.resource).name, '1.1 变量基础.mp4')
        self.assertFalse((current['directory'] / self.resource).exists())
        self.assertEqual(study.load(self.pid, self.resource), self.progress_before)
        self.assertEqual(study.notes(self.pid, self.resource), self.notes_before)
        self.assertEqual(conversations.get(self.pid, self.conversation['id'])['video_resource'], self.resource)
        self.assertTrue(conversations.availability(self.pid, self.resource)['available'])
        self.assertTrue(all(record['video_resource'] == self.resource for record in ai_analysis.records(self.pid)))
        self.assertEqual(videos.archived_videos(self.pid)[0]['id'], quality)
        self.assertTrue(library.learning_episodes(self.pid)[0]['archived'])
        self.assertEqual(library.learning_episodes(self.pid)[0]['title'], '1.1 变量基础')
        self.assertEqual(routes.media_response(self.pid, self.resource)['filename'], '1.1 变量基础.mp4')
        self.assertTrue(any(item['resource'] == self.resource for item in routes.transcription_sources()['sources']))
        self.assertEqual(library.logical_resource(current, library.resource(self.pid, self.resource)), self.resource)

    def test_old_session_download_uses_the_current_physical_filename(self):
        plan, preview = self.confirmed(); names.apply(plan['id'], preview['preview_token'])
        entry = SimpleNamespace(project_id=self.pid, media={'resource': self.resource, 'filename': 'old-title.mp4'})
        with patch.object(routes, 'get_entry', return_value=entry):
            response = routes.file('synthetic-session', 'video', True)
        self.assertEqual(response.filename, '1.1 变量基础.mp4')

    def test_export_contains_physical_names_and_a_consistent_manifest(self):
        plan, preview = self.confirmed(); names.apply(plan['id'], preview['preview_token'])
        with ZipFile(library.archive(self.pid)) as archive:
            manifest = json.loads(archive.read('project.json'))
            storage = manifest['resources'][self.resource]['storage_path']
            self.assertIn(storage, archive.namelist())
            self.assertNotIn(self.resource, archive.namelist())
            self.assertEqual(archive.read(storage), self.sources[0].read_bytes())
            self.assertTrue(any(name.startswith('personal-learning/') for name in archive.namelist()))

    def test_undo_keeps_materials_and_user_metadata_added_after_rename(self):
        plan, preview = self.confirmed(); names.apply(plan['id'], preview['preview_token'])
        report = library.save_text(self.pid, 'analysis', '改名后新增的合成材料', {'template': 'notes', 'video_resource': self.resource})
        library.rename(self.pid, '用户后来编辑的课程标题')
        names.restore(plan['id'])
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')
        self.assertIsNone(library.get(self.pid).get('episode_title'))
        self.assertEqual(library.get(self.pid)['title'], '用户后来编辑的课程标题')
        self.assertIn(report, library.get(self.pid)['resources'])
        self.assertEqual(study.notes(self.pid, self.resource), self.notes_before)
        self.assertEqual(conversations.get(self.pid, self.conversation['id'])['video_resource'], self.resource)
        self.assertEqual(names.load_plan(plan['id'])['state'], 'rolled_back')

    def test_existing_destination_is_never_overwritten(self):
        plan = self.plan(); project = library.get(self.pid)
        occupied = project['directory'] / 'videos/1.1 变量基础.mp4'; occupied.write_bytes(b'keep-this-unregistered-file')
        with self.assertRaises(names.NamingError): names.validate(plan['id'], plan['rows'])
        self.assertEqual(occupied.read_bytes(), b'keep-this-unregistered-file')
        self.assertTrue(library.resource(self.pid, self.resource).exists())

    def test_unsafe_names_duplicates_unknown_ids_and_path_lengths_are_rejected(self):
        plan = self.plan()
        for number, title in [('0.1', '标题'), ('01.2', '标题'), ('1.0', '标题'), ('1.1', '../越界'), ('1.1', '含/路径'), ('1.1', '含?问号'), ('1.1', '结尾.'), ('1.1', ' 空格'), ('1.1', '隐藏\u202e字符'), ('1.1', 'x' * 101)]:
            with self.subTest(number=number, title=title):
                rows = [dict(plan['rows'][0], number=number, title=title), plan['rows'][1]]
                with self.assertRaises(names.NamingError): names.validate(plan['id'], rows)
        for rows in [[plan['rows'][0], plan['rows'][0]], [plan['rows'][0], dict(plan['rows'][1], number='1.1')], [dict(plan['rows'][0], project_id='f' * 32)]]:
            with self.assertRaises(names.NamingError): names.validate(plan['id'], rows)
        self.assertIsNone(library.get(self.pid).get('episode_title'))

    def test_changed_subtitle_invalidates_the_plan_before_any_file_moves(self):
        plan, preview = self.confirmed()
        subtitle = library.resource(self.pid, 'subtitles/fixture.srt')
        subtitle.write_text(subtitle.read_text(encoding='utf-8') + '\n新的合成内容', encoding='utf-8')
        with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')

    def test_wrong_or_missing_preview_token_cannot_apply(self):
        plan, preview = self.confirmed()
        for token in ('', '0' * 32):
            with self.assertRaises(names.NamingError): names.apply(plan['id'], token)
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')

    def test_partial_manifest_failure_rolls_back_files_and_metadata(self):
        plan, preview = self.confirmed()
        before = {project['id']: (project['directory'] / 'project.json').read_bytes() for project in self.projects}
        atomic = library.atomic_json; failed = False
        second = self.projects[1]['directory'] / 'project.json'
        def fail_once(path, data):
            nonlocal failed
            if Path(path) == second and data.get('episode_title') and not failed:
                failed = True; raise PermissionError('synthetic write failure')
            return atomic(path, data)
        with patch.object(library, 'atomic_json', side_effect=fail_once):
            with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        self.assertTrue(failed)
        self.assertEqual(names.load_plan(plan['id'])['state'], 'proposed')
        for project in self.projects:
            self.assertEqual((project['directory'] / 'project.json').read_bytes(), before[project['id']])
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')

    def test_crash_journal_can_explicitly_restore_a_partially_removed_source(self):
        plan, preview = self.confirmed()
        unlink = Path.unlink; second = self.projects[1]['directory'] / self.resources[1]
        def interrupted(path, *args, **kwargs):
            if path == second: raise OSError('synthetic power-loss boundary')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', interrupted), patch.object(names, '_restore', side_effect=OSError('synthetic shutdown')):
            with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        self.assertEqual(names.load_plan(plan['id'])['state'], 'recovery_required')
        self.assertFalse((self.projects[0]['directory'] / self.resource).exists())
        extra = library.save_text(self.pid, 'analysis', '重启后新增的合成结果', {'video_resource': self.resource})
        names.restore(plan['id'])
        self.assertTrue((self.projects[0]['directory'] / self.resource).is_file())
        self.assertIn(extra, library.get(self.pid)['resources'])
        self.assertEqual(study.load(self.pid, self.resource), self.progress_before)

    @unittest.skipUnless(os.name == 'nt', 'Windows handle/share-mode regression')
    def test_windows_file_in_use_never_loses_the_original(self):
        plan, preview = self.confirmed()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(library.resource(self.pid, self.resource)), 0x80000000, 1, None, 3, 128, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
            self.assertTrue((self.projects[0]['directory'] / self.resource).is_file())
        finally: kernel.CloseHandle(wintypes.HANDLE(handle))
        if names.load_plan(plan['id'])['state'] == 'recovery_required': names.restore(plan['id'])
        self.assertEqual(library.resource(self.pid, self.resource).read_bytes(), self.sources[0].read_bytes())

    def test_reimport_same_video_preserves_its_logical_alias(self):
        plan, preview = self.confirmed(); names.apply(plan['id'], preview['preview_token'])
        logical = library.import_file(self.pid, self.sources[0], self.resource, 'video', {'media': MEDIA})
        self.assertEqual(logical, self.resource)
        self.assertEqual(library.resource(self.pid, self.resource).name, '1.1 变量基础.mp4')
        self.assertFalse((self.projects[0]['directory'] / self.resource).exists())

    def test_unsafe_storage_aliases_are_rejected_by_the_shared_resolver(self):
        for alias in ('../escape.mp4', 'elsewhere/escape.mp4', 'videos/secret.json', 'videos\\escape.mp4'):
            with self.subTest(alias=alias):
                library.update_details(self.pid, self.resource, {'storage_path': alias})
                with self.assertRaises(ValueError): library.resource(self.pid, self.resource)
                with self.assertRaises(ValueError): study.load(self.pid, self.resource)
        library.update_details(self.pid, self.resource, {'storage_path': self.resource})

    def test_model_consent_is_strict_and_checked_before_reading_materials(self):
        with patch.object(names, 'inventory') as inventory, patch.object(model_calls, 'require') as require:
            for consent in (False, 1, 'true', None):
                with self.assertRaises(names.NamingError): naming.start_plan(self.pid, consent)
            inventory.assert_not_called(); require.assert_not_called()
        for value in (False, 1, 'true'):
            with self.assertRaises(ValueError): naming_routes.SuggestBody(consent=value)
            with self.assertRaises(ValueError): naming_routes.ConfirmBody(confirm=value)

    def test_proposals_use_all_series_subtitles_but_exclude_notes_paths_and_chat(self):
        for engine in ('api', 'codex'):
            with self.subTest(engine=engine):
                plan = self.plan(); plan['agent'] = {'engine': engine, 'model': '' if engine == 'api' else 'fixture', 'effort': ''}; names.save_plan(plan)
                response = SimpleNamespace(text=json.dumps({'items': [{'index': 1, 'number': '1.1', 'title': '变量基础'}, {'index': 2, 'number': '1.2', 'title': '条件与类型'}]}), model='fixture')
                workspace = self.root / 'empty-native-workspace'
                with patch.object(ai_settings, 'current', return_value={'model': 'fixture', 'provider': 'custom'}), patch.object(model_calls, 'call', return_value=response) as call, patch.object(model_calls, 'workspace', return_value=workspace) as cwd:
                    result = naming.propose(plan, self.root / 'scratch')
                self.assertEqual(result['state'], 'proposed'); call.assert_called_once()
                messages = call.call_args.args[0]; serialized = json.dumps(messages, ensure_ascii=False)
                self.assertIn('第3讲的合成字幕', serialized)
                self.assertNotIn('不应发送的合成个人笔记', serialized)
                self.assertNotIn(str(self.projects[0]['directory']), serialized)
                self.assertEqual(call.call_args.kwargs['purpose'], 'naming')
                if engine == 'codex': cwd.assert_called_once(); self.assertEqual(call.call_args.kwargs['workspace'], workspace)
                else: cwd.assert_not_called()
                self.assertTrue((self.projects[0]['directory'] / self.resource).exists())
                self.assertIsNone(library.get(self.pid).get('episode_title'))

    def test_model_cannot_return_unknown_or_duplicate_episode_indexes(self):
        entries = self.plan()['entries']
        for items in [[{'index': 9, 'number': '1', 'title': '标题'}, {'index': 2, 'number': '2', 'title': '标题'}],
                      [{'index': 1, 'number': '1', 'title': '标题'}, {'index': 1, 'number': '2', 'title': '标题'}]]:
            with self.assertRaises(names.NamingError): naming.parse_proposals(json.dumps({'items': items}), entries)

    def test_external_source_replacement_during_link_preserves_both_files(self):
        plan, preview = self.confirmed()
        source = library.resource(self.pid, self.resource)
        target = self.projects[0]['directory'] / preview['moves'][0]['target']
        original = source.read_bytes(); external = b'new external synthetic content'
        link = os.link; changed = False
        def replace_after_link(old, new):
            nonlocal changed
            link(old, new)
            if Path(old) == source and not changed:
                changed = True; source.unlink(); source.write_bytes(external)
        with patch.object(os, 'link', side_effect=replace_after_link):
            with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        self.assertTrue(changed)
        self.assertEqual(source.read_bytes(), external)
        self.assertEqual(target.read_bytes(), original)
        self.assertNotIn('episode_title', library.get(self.pid))
        self.assertEqual(names.load_plan(plan['id'])['state'], 'recovery_required')
        # Simulate the user preserving/removing the interfering file, then explicit recovery.
        (self.root / 'preserved-external.mp4').write_bytes(source.read_bytes()); source.unlink()
        names.restore(plan['id'])
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(target.exists())

    def test_external_replacement_during_restore_is_not_deleted(self):
        plan, preview = self.confirmed(); names.apply(plan['id'], preview['preview_token'])
        renamed = library.resource(self.pid, self.resource)
        original_path = self.projects[0]['directory'] / self.resource
        original = renamed.read_bytes(); external = b'new external synthetic restoration content'
        link = os.link; changed = False
        def replace_after_link(old, new):
            nonlocal changed
            link(old, new)
            if Path(old) == renamed and not changed:
                changed = True; renamed.unlink(); renamed.write_bytes(external)
        with patch.object(os, 'link', side_effect=replace_after_link):
            with self.assertRaises(names.NamingError): names.restore(plan['id'])
        self.assertEqual(renamed.read_bytes(), external)
        self.assertEqual(original_path.read_bytes(), original)
        self.assertEqual(names.load_plan(plan['id'])['state'], 'recovery_required')
        (self.root / 'preserved-external-restore.mp4').write_bytes(renamed.read_bytes()); renamed.unlink()
        names.restore(plan['id'])
        self.assertEqual(library.resource(self.pid, self.resource).read_bytes(), original)

    def test_unsupported_hard_links_fail_without_moving_originals(self):
        import errno
        plan, preview = self.confirmed()
        with patch.object(os, 'link', side_effect=OSError(errno.EOPNOTSUPP, 'synthetic unsupported filesystem')):
            with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        self.assertEqual(names.load_plan(plan['id'])['state'], 'proposed')
        for project, resource in zip(self.projects, self.resources):
            self.assertTrue((project['directory'] / resource).is_file())
            self.assertNotIn('episode_title', library.get(project['id']))

    def test_cancel_during_commit_finishes_apply_and_restore_without_hidden_checkpoints(self):
        from threading import Event
        import time
        plan, preview = self.confirmed(); link = os.link
        for operation in ('apply', 'restore'):
            event = Event()
            payload = {'mode': operation, 'plan_id': plan['id'], 'token': preview['preview_token']}
            job = naming.Job(uuid4().hex, self.pid, 'synthetic', payload=payload, operation=operation)
            control = {'job': job, 'cancel': event, 'persist': lambda: None, 'phase_start': time.monotonic()}
            token = task_runtime._context.set(control)
            def late_cancel(source, target):
                link(source, target); event.set()
            try:
                with patch.object(os, 'link', side_effect=late_cancel): naming.worker(job)
            finally: task_runtime._context.reset(token)
            self.assertTrue(event.is_set())
            self.assertEqual(job.state, 'completed')
            self.assertEqual(job.phase, 'archiving')
        self.assertEqual(names.load_plan(plan['id'])['state'], 'rolled_back')
        self.assertEqual(study.load(self.pid, self.resource), self.progress_before)

    def test_cancel_before_commit_keeps_validated_plan_and_originals(self):
        from threading import Event
        plan, preview = self.confirmed(); event = Event(); event.set()
        job = naming.Job(uuid4().hex, self.pid, 'synthetic')
        token = task_runtime._context.set({'job': job, 'cancel': event})
        try:
            with self.assertRaises(task_runtime.Cancelled): names.apply(plan['id'], preview['preview_token'])
        finally: task_runtime._context.reset(token)
        self.assertEqual(names.load_plan(plan['id'])['state'], 'validated')
        self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')
        self.assertFalse(task_runtime.any_active())

    def test_http_preview_apply_restore_requires_explicit_consent_and_confirmation(self):
        import time
        from fastapi.testclient import TestClient
        from video_parser.web.app import app
        client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))
        prefix = '/api/workspace'
        response = SimpleNamespace(text=json.dumps({'items': [
            {'index': 1, 'number': '1.1', 'title': '变量基础'},
            {'index': 2, 'number': '1.2', 'title': '条件与类型'}]}), model='fixture')
        identifiers = []
        def completed(initial):
            self.assertEqual(initial.status_code, 202, initial.text)
            identifier = initial.json()['id']; identifiers.append(identifier)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                current = client.get(prefix + '/naming/tasks/' + identifier)
                self.assertEqual(current.status_code, 200)
                if current.json()['state'] not in task_runtime.ACTIVE:
                    self.assertEqual(current.json()['state'], 'completed', current.text)
                    return current.json()
                time.sleep(.02)
            self.fail('Synthetic naming HTTP task did not finish')
        try:
            with patch.object(naming, 'RECORD_ROOT', self.root / 'http-tasks'), patch.object(naming, 'CACHE_ROOT', self.root / 'http-cache'), \
                 patch.object(ai_settings, 'current', return_value={'model': 'fixture', 'provider': 'custom'}), \
                 patch.object(model_calls, 'require', return_value={'engine': 'api', 'model': '', 'effort': ''}) as require, \
                 patch.object(model_calls, 'call', return_value=response) as model:
                inventory = client.get(prefix + f'/projects/{self.pid}/naming')
                self.assertEqual(inventory.status_code, 200)
                self.assertEqual(inventory.json()['ready_count'], 2)
                start = prefix + f'/projects/{self.pid}/naming/plan'
                self.assertEqual(client.post(start, json={'consent': False}).status_code, 422)
                self.assertEqual(client.post(start, json={'consent': 1}).status_code, 422)
                self.assertEqual(client.post(start, headers={'Origin': 'https://foreign.invalid'}, json={'consent': True}).status_code, 403)
                require.assert_not_called(); model.assert_not_called()
                planned = completed(client.post(start, json={'consent': True, 'agent': {'engine': 'api'}}))
                self.assertEqual(planned['operation'], 'plan')
                plan_id = planned['result']['plan_id']
                path = prefix + '/naming/plans/' + plan_id
                plan = client.get(path).json()
                preview = client.post(path + '/preview', json={'rows': plan['rows']})
                self.assertEqual(preview.status_code, 200)
                self.assertNotIn('episode_title', library.get(self.pid))
                token = preview.json()['preview_token']
                self.assertEqual(client.post(path + '/apply', json={'confirm': 1, 'preview_token': token}).status_code, 422)
                self.assertEqual(client.post(path + '/apply', json={'confirm': True, 'preview_token': '0' * 32}).status_code, 400)
                applied = completed(client.post(path + '/apply', json={'confirm': True, 'preview_token': token}))
                self.assertEqual(applied['operation'], 'apply')
                self.assertEqual(library.resource(self.pid, self.resource).name, '1.1 变量基础.mp4')
                restored = completed(client.post(path + '/restore', json={'confirm': True}))
                self.assertEqual(restored['operation'], 'restore')
                self.assertEqual(restored['result']['state'], 'rolled_back')
                self.assertEqual(library.resource(self.pid, self.resource).name, 'original.mp4')
                self.assertEqual(study.load(self.pid, self.resource), self.progress_before)
                model.assert_called_once(); require.assert_called_once()
        finally:
            client.close()
            for identifier in identifiers: naming.jobs.pop(identifier, None)

    def test_job_operation_and_plan_link_survive_journal_restore(self):
        plan = self.plan(); record_root = self.root / 'synthetic-task-records'
        job = None
        try:
            with patch.object(naming, 'RECORD_ROOT', record_root), patch.object(task_runtime, 'submit', side_effect=lambda lane, job, worker, persist: persist()):
                job = naming._start(self.pid, {'mode': 'apply', 'plan_id': plan['id']}, plan['id'])
                self.assertEqual(naming.view(job)['operation'], 'apply')
                self.assertEqual(naming_routes.read_plan(plan['id'])['job_id'], job.id)
                naming.jobs.pop(job.id)
                restored = naming.get(job.id)
                self.assertEqual(naming.view(restored)['operation'], 'apply')
                self.assertEqual(restored.state, 'interrupted')
                self.assertEqual(restored.result['plan_id'], plan['id'])
        finally:
            if job: naming.jobs.pop(job.id, None)

    def test_exclusive_file_operation_blocks_other_jobs_without_blocking_polling(self):
        with task_runtime.exclusive_operation():
            self.assertTrue(task_runtime.any_active())
            with self.assertRaises(BlockingIOError): task_runtime.exclusive_operation().__enter__()
            fake = naming.Job(uuid4().hex, self.pid, 'synthetic')
            with self.assertRaises(BlockingIOError): task_runtime.submit('naming-test', fake, lambda _: None, lambda: None)
            self.assertEqual(task_runtime.metadata(fake)['phase'], 'queued')
        self.assertFalse(task_runtime.any_active())


if __name__ == '__main__':
    unittest.main(verbosity=2)
