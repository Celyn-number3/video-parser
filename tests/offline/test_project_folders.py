"""Synthetic filesystem tests; never touch real outputs, tasks, or model services."""
from dataclasses import dataclass
import hashlib
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from video_parser.services import library, library_index, library_layout as layout, library_migration as migration, task_runtime, folders


class ProjectFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vp-course-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'outputs'
        self.patcher = patch.object(library, 'LIBRARY_ROOT', self.root)
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.meta = {'platform': '哔哩哔哩', 'video_id': 'BV16NG96QEmA', 'title': '线性代数课程',
                     'source_url': 'https://www.bilibili.com/video/BV16NG96QEmA?p=1',
                     'episodes': [{'part': 1, 'title': '向量空间'}, {'part': 2, 'title': '矩阵'}]}

    def metadata(self, part, **extra):
        return {**self.meta, 'source_url': f'https://www.bilibili.com/video/BV16NG96QEmA?p={part}', **extra}

    def legacy(self, part, **extra):
        metadata = self.metadata(part, **extra)
        info = library.identity(metadata)
        identifier = hashlib.sha256(info['key'].encode()).hexdigest()[:32]
        directory = self.root / info['platform'] / (library.safe_name(metadata['title']) + f"__{info['video_id']}__P{part:03d}")
        directory.mkdir(parents=True)
        data = {'schema_version': 1, 'id': identifier, **info, 'title': metadata['title'],
                'created_at': 'fixture', 'resources': {}, 'identity_status': 'confirmed',
                'learned': part == 2, 'episodes': metadata['episodes'], 'episode_title': f'确认标题{part}'}
        library.atomic_json(directory / 'project.json', data)
        source = Path(self.temp.name) / f'input{part}.mp4'; source.write_bytes(f'video{part}'.encode())
        library.import_file(identifier, source, 'videos/原视频.mp4', 'video')
        source.write_bytes(b'caption')
        library.import_file(identifier, source, 'subtitles/原字幕.srt', 'transcription', {'video_resource': 'videos/原视频.mp4'})
        personal = directory / 'personal-learning'; personal.mkdir()
        (personal / ('a' * 64 + '.json')).write_text('{"notes": "用户笔记"}', encoding='utf-8')
        (directory / 'empty-user-folder').mkdir()
        return library.get(identifier)

    def apply(self, proposal=None):
        return migration.execute(proposal or migration.plan(), offline=True)

    def test_new_parts_share_one_parent_and_same_ids(self):
        one = library.ensure(self.metadata(1))
        two = library.ensure(self.metadata(2))
        self.assertEqual(one['directory'].parent, two['directory'].parent)
        self.assertEqual(one['directory'].name, 'P001-向量空间')
        self.assertEqual(two['directory'].name, 'P002-矩阵')
        self.assertEqual(len(one['directory'].relative_to(self.root).parts), 3)
        self.assertEqual(one['id'], hashlib.sha256(b'bilibili:BV16NG96QEmA:p1').hexdigest()[:32])
        self.assertEqual(len(library.manifests()), 2)

    def test_title_rename_and_reparse_do_not_split_course(self):
        one = library.ensure(self.metadata(1))
        library.rename(one['id'], '用户新课程名')
        two = library.ensure(self.metadata(2, title='平台再次返回的名称'))
        self.assertEqual(one['directory'].parent, two['directory'].parent)
        self.assertEqual(library.ensure(self.metadata(1))['title'], '用户新课程名')
        self.assertEqual(two['title'], '用户新课程名')

    def test_distinct_bv_same_title_and_non_bilibili_remain_separate(self):
        one = library.ensure(self.meta)
        other = library.ensure({**self.meta, 'video_id': 'BV1TaqYBcEJc', 'source_url': 'https://www.bilibili.com/video/BV1TaqYBcEJc?p=1'})
        local = library.ensure({'platform': 'local', 'video_id': 'abc', 'title': 'local'})
        self.assertNotEqual(one['directory'].parent, other['directory'].parent)
        self.assertEqual(len(local['directory'].relative_to(self.root).parts), 2)
        self.assertEqual(migration.plan()['entries'], [])

    def test_new_part_and_migration_reuse_same_existing_parent(self):
        one = self.legacy(1)
        two = library.ensure(self.metadata(2, title='不同的抓取标题'))
        record = self.apply()
        self.assertEqual(len(record['entries']), 1)
        self.assertEqual(library.get(one['id'])['directory'].parent, two['directory'].parent)

    def test_migrate_preserves_all_bytes_ids_resources_and_learning(self):
        one, two = self.legacy(1), self.legacy(2)
        before = {p['id']: migration.inventory(p['directory']) for p in (one, two)}
        for p in (one, two): library.get(p['id'])  # Warm the old persisted/in-memory index.
        record = self.apply()
        self.assertEqual(record['state'], 'completed')
        self.assertEqual(len(record['entries']), 2)
        for p in (one, two):
            new = library.get(p['id'])
            self.assertFalse(p['directory'].exists())
            self.assertEqual(migration.inventory(new['directory']), before[p['id']])
            self.assertEqual(library.resource(p['id'], 'videos/原视频.mp4').read_bytes(), f"video{p['part']}".encode())
            self.assertEqual(new['episode_title'], p['episode_title'])
            self.assertEqual(new['learned'], p['learned'])
            self.assertEqual(library.owner(new['directory'] / 'videos/原视频.mp4')['id'], p['id'])
        self.assertEqual([r['learned'] for r in library.learning_episodes(one['id'])], [False, True])
        self.assertEqual(len(library.subtitle_inventory(self.meta['video_id'])['available']), 2)
        self.assertEqual(migration.plan()['entries'], [])
        self.assertEqual(self.apply(record)['state'], 'completed')

    def test_exports_include_resources_and_personal_notes_after_moving(self):
        one = self.legacy(1); self.apply()
        archive = library.archive(one['id'])
        with ZipFile(archive) as stream:
            self.assertIn('videos/原视频.mp4', stream.namelist())
            self.assertIn('personal-learning/' + 'a' * 64 + '.json', stream.namelist())

    def test_physical_filename_alias_remains_valid(self):
        one = self.legacy(1)
        source = one['directory'] / 'videos/原视频.mp4'
        source.rename(source.with_name('1.1 已确认视频.mp4'))
        one['resources']['videos/原视频.mp4']['storage_path'] = 'videos/1.1 已确认视频.mp4'
        library.atomic_json(one['directory'] / 'project.json', {k: v for k, v in one.items() if k != 'directory'})
        self.apply()
        self.assertEqual(library.resource(one['id'], 'videos/原视频.mp4').name, '1.1 已确认视频.mp4')

    def test_plan_is_readonly_and_apply_requires_offline_acknowledgement(self):
        one = self.legacy(1)
        before = migration.inventory(one['directory'])
        proposal = migration.plan()
        self.assertEqual(migration.inventory(one['directory']), before)
        self.assertFalse((self.root / layout.ALIAS_FILE).exists())
        with self.assertRaises(ValueError): migration.execute(proposal)
        self.assertTrue(one['directory'].exists())

    def test_target_conflict_aborts_without_moving_any_part(self):
        one, two = self.legacy(1), self.legacy(2)
        proposal = migration.plan()
        target = self.root / proposal['entries'][1]['new']; target.mkdir(parents=True)
        (target / 'mine.txt').write_text('do not overwrite')
        with self.assertRaises(FileExistsError): self.apply(proposal)
        self.assertTrue(one['directory'].is_dir()); self.assertTrue(two['directory'].is_dir())
        self.assertEqual((target / 'mine.txt').read_text(), 'do not overwrite')
        self.assertFalse(migration.journal_path(proposal['id']).exists())

    def test_changed_file_aborts_entire_batch(self):
        one, two = self.legacy(1), self.legacy(2)
        proposal = migration.plan()
        (two['directory'] / 'personal-learning/new-note.json').write_text('new')
        with self.assertRaises(ValueError): self.apply(proposal)
        self.assertTrue(one['directory'].is_dir()); self.assertTrue(two['directory'].is_dir())

    def test_bad_registered_hash_and_duplicate_identity_are_refused(self):
        one = self.legacy(1)
        (one['directory'] / 'videos/原视频.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError): migration.plan()
        (one['directory'] / 'videos/原视频.mp4').write_bytes(b'video1')
        duplicate = self.root / 'bilibili/duplicate'; duplicate.mkdir()
        (duplicate / 'project.json').write_bytes((one['directory'] / 'project.json').read_bytes())
        with self.assertRaises(ValueError): migration.plan()

    def test_unsafe_plan_paths_cannot_escape_library(self):
        one = self.legacy(1); proposal = migration.plan()
        for bad in ('../escape/P001', 'bilibili/../P001', str(Path(self.temp.name) / 'outside/P001')):
            proposal['entries'][0]['new'] = bad
            with self.assertRaises(ValueError): self.apply(proposal)
        self.assertTrue(one['directory'].is_dir())

    def test_symlink_resource_is_rejected(self):
        one = self.legacy(1)
        outside = Path(self.temp.name) / 'outside'; outside.mkdir()
        try: (one['directory'] / 'link').symlink_to(outside, target_is_directory=True)
        except OSError: self.skipTest('Symlink creation unavailable')
        with self.assertRaises(ValueError): migration.plan()

    @unittest.skipUnless(os.name == 'nt', 'Windows junction safety regression')
    def test_junction_resource_is_rejected(self):
        one = self.legacy(1)
        outside = Path(self.temp.name) / 'outside'; outside.mkdir()
        junction = one['directory'] / 'junction'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)], check=True, capture_output=True)
        try:
            with self.assertRaises(ValueError): migration.plan()
        finally:
            junction.rmdir()

    def test_unknown_parent_created_after_preview_is_not_merged(self):
        one = self.legacy(1); proposal = migration.plan()
        parent = (self.root / proposal['entries'][0]['new']).parent
        parent.mkdir()
        (parent / 'user-file.txt').write_text('mine')
        with self.assertRaises(FileExistsError): self.apply(proposal)
        self.assertTrue(one['directory'].exists())

    def test_late_collision_never_overwrites_empty_target(self):
        one = self.legacy(1); proposal = migration.plan()
        original = migration._move
        def collide(source, target):
            target.mkdir()
            return original(source, target)
        with patch.object(migration, '_move', side_effect=collide):
            with self.assertRaises(FileExistsError): self.apply(proposal)
        self.assertTrue(one['directory'].is_dir())
        self.assertEqual(migration.read_journal(proposal['id'])['state'], 'interrupted')

    def test_crash_after_rename_can_resume_then_undo(self):
        one, two = self.legacy(1), self.legacy(2)
        proposal = migration.plan(); original = migration._move
        def crash(source, target):
            original(source, target)
            raise RuntimeError('simulated process interruption after rename')
        with patch.object(migration, '_move', side_effect=crash):
            with self.assertRaises(RuntimeError): self.apply(proposal)
        record = migration.read_journal(proposal['id'])
        self.assertEqual(record['state'], 'interrupted')
        self.assertEqual(len(library.manifests()), 2)  # Mixed layouts remain discoverable.
        record = self.apply(record)
        self.assertEqual(record['state'], 'completed')
        record = migration.execute(record, undo=True, offline=True)
        self.assertEqual(record['state'], 'undone')
        self.assertTrue(one['directory'].is_dir()); self.assertTrue(two['directory'].is_dir())
        self.assertEqual(migration.execute(record, undo=True, offline=True)['state'], 'undone')

    def test_rollback_refuses_modified_contents(self):
        one = self.legacy(1); record = self.apply()
        current = library.get(one['id'])
        (current['directory'] / 'new-notes.txt').write_text('new user work')
        with self.assertRaises(ValueError): migration.execute(record, undo=True, offline=True)
        self.assertEqual((current['directory'] / 'new-notes.txt').read_text(), 'new user work')
        self.assertFalse(one['directory'].exists())

    def test_path_fields_rebase_but_prose_external_paths_and_traversal_do_not(self):
        one = self.legacy(1); record = self.apply()
        current = library.get(one['id'])
        old = one['directory'] / 'videos/原视频.mp4'
        value = {'source': str(old), 'files': {'mp4': str(old)},
                 'result': {'project': {'location': one['directory'].relative_to(self.root).as_posix()}},
                 'prompt': str(old), 'title': str(old), 'text': str(old), 'message': str(old),
                 'outside': str(Path(self.temp.name) / 'elsewhere'),
                 'path': str(one['directory'] / '../private.txt')}
        updated = layout.restore_task_paths(value)
        self.assertEqual(updated['source'], str(current['directory'] / 'videos/原视频.mp4'))
        self.assertEqual(updated['files']['mp4'], updated['source'])
        self.assertEqual(updated['result']['project']['location'], library.public(current)['location'])
        for field in ('prompt', 'title', 'text', 'message', 'outside', 'path'):
            self.assertEqual(updated[field], value[field])
        migration.execute(record, undo=True, offline=True)
        self.assertEqual(layout.restore_task_paths(updated)['source'], str(old))

    def test_restored_completed_task_keeps_journal_bytes_and_state(self):
        @dataclass
        class Job:
            id: str
            source: Path
            state: str = 'completed'
            created_at: float = 0
        one = self.legacy(1)
        jobs = Path(self.temp.name) / 'jobs'
        job = Job('a' * 32, one['directory'] / 'videos/原视频.mp4')
        task_runtime.save(jobs, job)
        before = (jobs / (job.id + '.json')).read_bytes()
        self.apply()
        restored = task_runtime.restore(jobs, job.id, Job, ('source',))
        self.assertEqual(restored.source.read_bytes(), b'video1')
        self.assertEqual(restored.state, 'completed')
        self.assertEqual((jobs / (job.id + '.json')).read_bytes(), before)

    def test_remembered_folder_permissions_follow_move_without_config_rewrite(self):
        one = self.legacy(1)
        state = Path(self.temp.name) / 'saved-folders.json'
        approved = one['directory'] / 'subtitles'
        state.write_text(json.dumps({'folders': [str(approved)]}), encoding='utf-8')
        before = state.read_bytes()
        with patch.object(folders, 'STATE', state):
            record = self.apply()
            current = library.get(one['id'])['directory'] / 'subtitles'
            self.assertEqual(folders.listing(), [{'path': str(current), 'exists': True}])
            self.assertEqual(folders.check(str(approved)), current)
            self.assertEqual(folders.check(str(current)), current)
            with self.assertRaises(PermissionError): folders.check(str(current.parent / 'videos'))
            self.assertEqual(state.read_bytes(), before)
            migration.execute(record, undo=True, offline=True)
            self.assertEqual(folders.check(str(current)), approved)
            self.assertEqual(state.read_bytes(), before)

    def test_wrong_alias_identity_is_rejected(self):
        one = self.legacy(1); self.apply()
        aliases = layout.read_aliases(); aliases['moves'][0]['project_id'] = '0' * 32
        library.atomic_json(self.root / layout.ALIAS_FILE, aliases)
        with self.assertRaises(ValueError): layout.restore_task_paths({'source': str(one['directory'] / 'videos/原视频.mp4')})


if __name__ == '__main__':
    unittest.main()
