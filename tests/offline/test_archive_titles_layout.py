"""Isolated title-only naming, named folders, chain aliases and flatten recovery."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from video_parser.services import library, library_index, library_layout as layout, library_migration as old_migration
from video_parser.services import archive_layout as migration, resource_renames as names, naming


class ArchiveTitlesLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vp-archive-titles-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(library, 'LIBRARY_ROOT', self.root / 'outputs')
        patcher.start(); self.addCleanup(patcher.stop)

    def project(self, part=1, count=2):
        episodes = [{'part': n, 'title': f'合成章节{n}'} for n in range(1, count + 1)]
        return library.ensure({'platform': 'bilibili', 'video_id': 'BV16NG96QEmA', 'title': '合成课程',
                               'source_url': f'https://www.bilibili.com/video/BV16NG96QEmA?p={part}', 'episodes': episodes})

    def files(self, project):
        for key, kind in [('videos/original.mp4', 'video'), ('subtitles/original.srt', 'subtitle')]:
            source = self.root / 'fixture'; source.write_bytes(b'1\n00:00:00,000 --> 00:00:02,000\nfixture')
            library.import_file(project['id'], source, key, kind)
        (project['directory'] / 'personal-learning').mkdir()
        (project['directory'] / 'personal-learning/note.json').write_text('{"note":"keep"}')
        return library.get(project['id'])

    def draft(self, project, number='1.1', title='新标题'):
        inv = names.inventory(project['id'])
        plan = {'version': 1, 'id': uuid4().hex, 'project_id': project['id'], 'state': 'proposed', 'created_at': names.now(),
                'fingerprint': inv['fingerprint'], 'rename_scope': names.JOINT_SCOPE, 'entries': inv['entries'],
                'rows': [{'project_id': project['id'], 'number': number, 'title': title}]}
        names.save_plan(plan)
        return plan

    def legacy_folder(self, project):
        # Construct the previous Pnnn layout without modifying any metadata or resources.
        old = project['directory']
        target = old.parent / f"P{project['part']:03d}"
        if len(old.relative_to(library.LIBRARY_ROOT).parts) == 2:
            target = old / 'P001'
            target.mkdir()
            for child in list(old.iterdir()):
                if child != target: child.rename(target / child.name)
        else:
            old.rename(target)
        library_index.invalidate(library.LIBRARY_ROOT)
        return library.get(project['id'])

    def test_new_multi_uses_parsed_title_even_when_only_one_part_is_downloaded(self):
        p = self.project(5, 8)
        self.assertEqual(p['directory'].name, 'P005-合成章节5')
        self.assertFalse(names.inventory(p['id'])['entries'][0]['single_episode'])
        self.assertEqual(len(library.manifests()), 1)
        self.assertEqual(library.ensure({**p, 'platform': 'bilibili'})['id'], p['id'])

    def test_new_single_has_no_part_folder_or_number_in_preview_and_apply(self):
        p = self.files(self.project(count=1))
        self.assertEqual(len(p['directory'].relative_to(library.LIBRARY_ROOT).parts), 2)
        plan = self.draft(p)
        preview = names.validate(plan['id'], plan['rows'])
        self.assertEqual(preview['rows'][0]['number'], '')
        self.assertTrue(all('1.1' not in m['target'] for m in preview['moves']))
        self.assertEqual(preview['directory_moves'], [])
        names.apply(plan['id'], preview['preview_token'])
        after = library.get(p['id'])
        self.assertEqual(after['episode_title'], '新标题')
        self.assertNotIn('hierarchical_name', after)
        self.assertEqual(library.resource(p['id'], 'videos/original.mp4').name, '新标题.mp4')

    def test_single_model_number_is_ignored_but_multiple_is_preserved(self):
        text = '{"items":[{"index":1,"number":"1.1","title":"1.1 新标题"}]}'
        single = naming.parse_proposals(text, [{'project_id': 'a' * 32, 'single_episode': True}])[0]
        self.assertEqual((single['number'], single['title']), ('', '新标题'))
        multi = naming.parse_proposals(text, [{'project_id': 'a' * 32, 'single_episode': False}])[0]
        self.assertEqual(multi['number'], '1.1')

    def test_unknown_catalog_is_not_flattened(self):
        p = self.project(count=0)
        self.assertEqual(len(p['directory'].relative_to(library.LIBRARY_ROOT).parts), 3)
        self.assertFalse(layout.single_episode(p))

    def test_multi_rename_moves_folder_joint_files_and_preserves_notes_then_undo(self):
        p = self.files(self.project())
        old = p['directory']; plan = self.draft(p, '2.1', '转置、置换与向量空间')
        preview = names.validate(plan['id'], plan['rows'])
        self.assertEqual(len(preview['directory_moves']), 1)
        names.apply(plan['id'], preview['preview_token'])
        current = library.get(p['id'])
        self.assertEqual(current['directory'].name, 'P001-2.1 转置、置换与向量空间')
        self.assertFalse(old.exists())
        self.assertEqual(library.resource(p['id'], 'subtitles/original.srt').name, '2.1 转置、置换与向量空间-B站平台字幕.srt')
        (current['directory'] / 'personal-learning/new-note.json').write_text('new note after rename')
        names.restore(plan['id'])
        self.assertEqual(library.get(p['id'])['directory'], old)
        self.assertEqual((old / 'personal-learning/new-note.json').read_text(), 'new note after rename')
        self.assertTrue((old / 'videos/original.mp4').exists())

    def test_directory_collision_rejected_before_file_changes(self):
        p = self.files(self.project()); plan = self.draft(p)
        target = p['directory'].with_name('P001-1.1 新标题'); target.mkdir()
        with self.assertRaises(FileExistsError): names.validate(plan['id'], plan['rows'])
        self.assertTrue((p['directory'] / 'videos/original.mp4').exists())
        self.assertEqual(list(target.iterdir()), [])

    def test_late_directory_failure_restores_files_and_titles(self):
        p = self.files(self.project()); plan = self.draft(p)
        preview = names.validate(plan['id'], plan['rows'])
        with patch.object(old_migration, '_move', side_effect=PermissionError('external player holds directory')):
            with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        self.assertTrue((p['directory'] / 'videos/original.mp4').exists())
        self.assertNotIn('episode_title', library.get(p['id']))
        self.assertEqual(names.load_plan(plan['id'])['state'], 'proposed')

    def test_migrate_named_folder_and_chain_alias_without_journal_rewrite(self):
        p = self.legacy_folder(self.files(self.project()))
        ancient = p['directory'].parent.with_name('旧课程__BV16NG96QEmA__P001')
        library.atomic_json(library.LIBRARY_ROOT / layout.ALIAS_FILE, {'version': 1, 'moves': [{
            'project_id': p['id'], 'old': ancient.relative_to(library.LIBRARY_ROOT).as_posix(),
            'new': p['directory'].relative_to(library.LIBRARY_ROOT).as_posix()}]})
        before = old_migration.inventory(p['directory'])
        record = migration.execute(migration.plan(), offline=True)
        current = library.get(p['id'])
        self.assertEqual(old_migration.inventory(current['directory']), before)
        text = str(ancient / 'videos/original.mp4')
        value = layout.restore_task_paths({'source': text, 'message': text})
        self.assertEqual(value['source'], str(current['directory'] / 'videos/original.mp4'))
        self.assertEqual(value['message'], text)
        migration.execute(record, offline=True, undo=True)
        self.assertEqual(layout.restore_task_paths({'source': value['source']})['source'], str(p['directory'] / 'videos/original.mp4'))

    def test_flatten_all_files_without_changes_and_undo(self):
        p = self.legacy_folder(self.files(self.project(count=1)))
        before = old_migration.inventory(p['directory'])
        record = migration.execute(migration.plan(), offline=True)
        current = library.get(p['id'])
        self.assertEqual(current['directory'], p['directory'].parent)
        self.assertFalse(p['directory'].exists())
        self.assertEqual(old_migration.inventory(current['directory']), before)
        self.assertEqual(migration.plan()['entries'], [])
        migration.execute(record, offline=True, undo=True)
        self.assertEqual(old_migration.inventory(p['directory']), before)

    def test_flatten_crash_midway_resumes_without_overwrite(self):
        p = self.legacy_folder(self.files(self.project(count=1)))
        proposal = migration.plan(); original = old_migration._move
        def crash(a, b):
            original(a, b)
            raise RuntimeError('interrupted after one atomic move')
        with patch.object(old_migration, '_move', side_effect=crash):
            with self.assertRaises(RuntimeError): migration.execute(proposal, offline=True)
        record = migration.execute(proposal, offline=True)
        self.assertEqual(record['state'], 'completed')
        self.assertEqual(library.resource(p['id'], 'videos/original.mp4').read_bytes(), b'1\n00:00:00,000 --> 00:00:02,000\nfixture')

    def test_flatten_unknown_parent_content_aborts_without_any_move(self):
        p = self.legacy_folder(self.files(self.project(count=1)))
        (p['directory'].parent / 'mine.txt').write_text('mine')
        with self.assertRaises(FileExistsError): migration.plan()
        self.assertTrue((p['directory'] / 'project.json').exists())

    def test_changed_content_and_online_mode_refused(self):
        p = self.legacy_folder(self.files(self.project()))
        proposal = migration.plan()
        with self.assertRaises(ValueError): migration.execute(proposal)
        (p['directory'] / 'personal-learning/note.json').write_text('changed')
        with self.assertRaises(ValueError): migration.execute(proposal, offline=True)
        self.assertTrue(p['directory'].exists())

    def test_identity_lock_stays_exclusive_across_directory_rename(self):
        p = self.project(); old = p['directory']; new = old.with_name('P001-稳定锁测试')
        row = migration.row_for(p, new)
        with library.file_lock(old / '.manifest.lock'):
            migration.rename_directories([row])
            with self.assertRaises(TimeoutError):
                with library.file_lock(new / '.manifest.lock', timeout=.03):
                    self.fail('Concurrent writer escaped identity lock')
        with library.file_lock(old / '.manifest.lock'):
            self.assertEqual(library._project_lock_path(old / '.manifest.lock'), library._project_lock_path(new / '.manifest.lock'))
        self.assertFalse(old.exists())

    def test_crash_after_directory_rename_remains_explicitly_recoverable(self):
        p = self.files(self.project()); plan = self.draft(p)
        preview = names.validate(plan['id'], plan['rows']); original = old_migration._move
        def crash(source, target):
            original(source, target)
            raise RuntimeError('simulated process interruption after directory rename')
        with patch.object(old_migration, '_move', side_effect=crash):
            with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        self.assertEqual(names.load_plan(plan['id'])['state'], 'recovery_required')
        names.restore(plan['id'])
        self.assertEqual(library.get(p['id'])['directory'], p['directory'])
        self.assertTrue((p['directory'] / 'videos/original.mp4').exists())
        self.assertEqual((p['directory'] / 'personal-learning/note.json').read_text(), '{"note":"keep"}')
