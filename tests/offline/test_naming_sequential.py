"""Synthetic sequential naming and joint transactions. No user files or real models."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from video_parser.services import naming, resource_renames as names, library, ai_settings, model_calls, transcription, task_runtime, study, conversations, subtitles
from tests.offline import test_subtitle_naming as fixtures


class JointNamingTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.SubtitleNamingTests('test_preview_does_not_rename_or_change_associations')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def joint(self):
        plan = self.f.plan(); plan['rename_scope'] = names.JOINT_SCOPE
        plan['context'] = names.inventory(self.f.pid)['entries']
        names.save_plan(plan)
        return plan

    def test_joint_apply_and_undo_preserve_subtitle_bytes_and_logical_links(self):
        plan = self.joint(); key = 'subtitles/fixture.srt'
        before = library.resource(self.f.pid, key); content = before.read_bytes()
        preview = names.validate(plan['id'], plan['rows'])
        self.assertEqual(len(preview['moves']), 4)
        self.assertTrue(before.exists())
        names.apply(plan['id'], preview['preview_token'])
        after = library.resource(self.f.pid, key)
        self.assertEqual(after.name, '1.1 变量基础-B站平台字幕.srt')
        self.assertEqual(after.read_bytes(), content); self.assertFalse(before.exists())
        self.assertEqual(study.load(self.f.pid, self.f.resource), self.f.progress_before)
        self.assertTrue(conversations.availability(self.f.pid, self.f.resource)['available'])
        names.restore(plan['id'])
        self.assertEqual(library.resource(self.f.pid, key), before); self.assertEqual(before.read_bytes(), content)
        self.assertFalse(after.exists())

    def test_platform_triplet_old_downloads_and_results_use_current_names(self):
        for ext in ('json', 'md'):
            source = self.f.root / ('platform.' + ext); source.write_text('fixture', encoding='utf-8')
            library.import_file(self.f.pid, source, 'subtitles/fixture.' + ext, 'subtitle')
        plan = self.joint(); preview = names.validate(plan['id'], plan['rows'])
        job = subtitles.Job('a' * 32, 'https://www.bilibili.com/video/' + fixtures.VIDEO_ID, [1], self.f.root / 'cache')
        job.state = 'completed'
        job.files = {'1-' + ext: library.resource(self.f.pid, 'subtitles/fixture.' + ext) for ext in ('srt', 'json', 'md')}
        job.results = [{'episode': 1, 'status': 'downloaded', 'project': {'id': self.f.pid}, 'files': [
            {'name': 'fixture.' + ext, 'format': ext.upper(), 'url': f'/api/workspace/projects/{self.f.pid}/files/subtitles/fixture.{ext}?download=true'} for ext in ('srt', 'json', 'md')]}]
        names.apply(plan['id'], preview['preview_token'])
        with patch.object(subtitles, 'get', return_value=job):
            for ext in ('srt', 'json', 'md'):
                self.assertEqual(subtitles.download_file(job.id, '1-' + ext).name, '1.1 变量基础-B站平台字幕.' + ext)
        self.assertTrue(all(file['name'].startswith('1.1 变量基础') for file in subtitles.view(job)['results'][0]['files']))
        self.assertTrue(all(file['name'].startswith('fixture') for file in job.results[0]['files']))
        names.restore(plan['id'])
        self.assertTrue(all(path.exists() for path in job.files.values()))

    def test_multilingual_companions_downloads_and_reimport_follow_aliases(self):
        extra = self.f.root / 'translation.srt'; extra.write_text('1\n00:00:00,000 --> 00:00:03,000\nChinese fixture\n', encoding='utf-8')
        keys = []
        for fmt in ('srt', 'txt'):
            key = library.import_file(self.f.pid, extra, 'subtitles/translated.' + fmt, 'translation', {'language': 'zh', 'source_resource': 'subtitles/fixture.srt', 'video_resource': self.f.resource})
            keys.append(key)
        plan = self.joint(); preview = names.validate(plan['id'], plan['rows']); names.apply(plan['id'], preview['preview_token'])
        for key in keys:
            item = {'path': self.f.projects[0]['directory'] / key, 'relative': key, 'project_id': self.f.pid, 'sha256': library.digest(extra)}
            job = transcription.Job('a' * 32, extra, 'fixture', 'auto', project_id=self.f.pid); job.state = 'completed'; job.files = {'srt': item}
            with patch.object(transcription, 'get', return_value=job):
                current = transcription.download_file(job.id, 'srt')
                self.assertIn('-中文-AI译文-B站平台字幕', current.name)
                self.assertEqual(transcription.view(job)['files'][0]['name'], current.name)
            self.assertEqual(library.import_file(self.f.pid, extra, key, 'translation'), key)
            alias = library.get(self.f.pid)['resources'][key]['storage_path']
            self.assertEqual(library.import_file(self.f.pid, extra, alias, 'translation'), key)
        names.restore(plan['id'])
        for key in keys: self.assertEqual(library.resource(self.f.pid, key).name, Path(key).name)

    def test_subtitle_collision_prevents_every_video_move(self):
        plan = self.joint(); path = self.f.projects[0]['directory'] / 'subtitles/1.1 变量基础-B站平台字幕.srt'
        path.write_text('unrelated', encoding='utf-8')
        with self.assertRaises(names.NamingError): names.validate(plan['id'], plan['rows'])
        self.assertEqual(library.resource(self.f.pid, self.f.resource).name, 'original.mp4')
        self.assertEqual(path.read_text(encoding='utf-8'), 'unrelated')

    def test_subtitle_link_failure_rolls_back_all_video_links(self):
        plan = self.joint(); preview = names.validate(plan['id'], plan['rows']); original = names._checked_link
        def link(source, target, move):
            if source.suffix == '.srt': raise OSError('synthetic file busy')
            return original(source, target, move)
        with patch.object(names, '_checked_link', side_effect=link):
            with self.assertRaises(names.NamingError): names.apply(plan['id'], preview['preview_token'])
        for move in preview['moves']:
            project = library.get(move['project_id'])
            self.assertTrue((project['directory'] / move['source']).exists())
            self.assertFalse((project['directory'] / move['target']).exists())

    def test_every_previous_filename_and_generated_name_but_only_current_subtitles(self):
        plan = self.joint(); plan['entries'].reverse(); names.save_plan(plan)
        replies = [SimpleNamespace(text=json.dumps({'items': [{'index': 1, 'number': number, 'title': title}]}), model='fixture')
                   for number, title in [('1.3', '变量'), ('2.1', '条件')]]
        with patch.object(ai_settings, 'current', return_value={'provider': 'custom', 'model': 'fixture'}), patch.object(model_calls, 'call', side_effect=replies) as call:
            naming.propose(plan, self.f.root / 'scratch')
        self.assertEqual(call.call_count, 2)
        first, second = [json.loads(c.args[0][1]['content']) for c in call.call_args_list]
        self.assertEqual(first['previous_episodes'], [])
        self.assertIn('第1讲的合成字幕', first['current_episode']['subtitles'])
        self.assertNotIn('第2讲的合成字幕', json.dumps(first, ensure_ascii=False))
        self.assertIn('1.3 变量.mp4', second['previous_episodes'][0]['filenames'])
        self.assertIn('第2讲的合成字幕', second['current_episode']['subtitles'])
        for item in (first, second):
            text = json.dumps(item, ensure_ascii=False)
            self.assertNotIn('第3讲的合成字幕', text); self.assertNotIn('不应发送的合成个人笔记', text)
            self.assertNotIn(str(self.f.root), text)
        self.assertEqual([row['number'] for row in names.load_plan(plan['id'])['rows']], ['1.3', '2.1'])

    def test_prior_unselected_episode_is_included_without_reading_its_subtitles(self):
        plan = self.joint(); plan['entries'] = plan['entries'][1:]; names.save_plan(plan)
        reply = SimpleNamespace(text='{"items":[{"index":1,"number":"1.3","title":"当前主题"}]}', model='fixture')
        with patch.object(ai_settings, 'current', return_value={'model': 'fixture'}), patch.object(model_calls, 'call', return_value=reply) as call:
            naming.propose(plan, self.f.root / 'scratch')
        payload = json.loads(call.call_args.args[0][1]['content'])
        self.assertEqual(payload['previous_episodes'][0]['filenames'], ['original.mp4', 'fixture.srt'])
        self.assertNotIn('第1讲的合成字幕', json.dumps(payload, ensure_ascii=False))

    def test_later_failure_retains_first_suggestion_without_retry_or_rename(self):
        plan = self.joint()
        reply = SimpleNamespace(text='{"items":[{"index":1,"number":"1.3","title":"当前主题"}]}', model='fixture')
        with patch.object(ai_settings, 'current', return_value={'model': 'fixture'}), patch.object(model_calls, 'call', side_effect=[reply, RuntimeError('synthetic')]) as call:
            with self.assertRaises(RuntimeError): naming.propose(plan, self.f.root / 'scratch')
        self.assertEqual(call.call_count, 2)
        self.assertEqual(len(names.load_plan(plan['id'])['rows']), 1)
        self.assertEqual(library.resource(self.f.pid, self.f.resource).name, 'original.mp4')

    def test_alias_cannot_escape_subtitle_folder_or_change_type(self):
        for alias in ('../secret.srt', 'videos/other.srt', 'subtitles/other.exe', 'subtitles\\other.srt'):
            library.update_details(self.f.pid, 'subtitles/fixture.srt', {'storage_path': alias})
            with self.assertRaises(ValueError): library.resource(self.f.pid, 'subtitles/fixture.srt')


if __name__ == '__main__': unittest.main()
