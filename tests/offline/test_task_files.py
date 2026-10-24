"""Filename labels must never substitute a course title or guess another quality's video."""
from pathlib import Path
from types import SimpleNamespace as Job
import unittest
from unittest.mock import patch
from video_parser.services import task_files


class TaskFileTests(unittest.TestCase):
    def setUp(self):
        self.project = {'title': '课程不是文件名', 'resources': {
            'videos/old.mp4': {'kind': 'video', 'storage_path': 'videos/1.2 本集主题.mp4'},
            'subtitles/source.srt': {'kind': 'subtitle', 'storage_path': 'subtitles/1.2-B站平台字幕.srt'},
            'subtitles/zh.srt': {'kind': 'translation', 'storage_path': 'subtitles/1.2-中文.srt'}}}
        self.patcher = patch.object(task_files.library, 'get', return_value=self.project)
        self.get = self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.resolve = task_files.filename_labels()

    def test_video_uses_current_physical_filename_not_download_or_project_title(self):
        job = Job(kind='video', project_id='p', title='旧课程', result={'resource': 'videos/old.mp4', 'filename': '旧下载标题.mp4'})
        self.assertEqual(self.resolve(job), ['1.2 本集主题.mp4'])
        self.resolve(job); self.get.assert_called_once_with('p')

    def test_completed_translation_tracks_archived_output_resource(self):
        job = Job(operation='translation', project_id='p', files={'txt': {'path': Path('/output/中文.txt')}, 'srt': {'path': Path('/old/zh.srt'), 'relative': 'subtitles/zh.srt', 'project_id': 'p'}})
        self.assertEqual(self.resolve(job), ['1.2-中文.srt', '中文.txt'])

    def test_failed_translation_uses_input_subtitle(self):
        job = Job(operation='translation', project_id='p', source=Path('/old/source.srt'), translation={'reference': {'resource': 'subtitles/source.srt'}})
        self.assertEqual(self.resolve(job), ['1.2-B站平台字幕.srt'])

    def test_running_transcription_and_uploaded_file(self):
        self.assertEqual(self.resolve(Job(operation='transcription', project_id='p', resource='videos/old.mp4')), ['1.2 本集主题.mp4'])
        self.assertEqual(self.resolve(Job(operation='transcription', owned_input=True, title='上传录音.wav', source=Path('/temp/input.wav'))), ['上传录音.wav'])

    def test_analysis_uses_exact_input_even_with_multiple_videos(self):
        self.project['resources']['videos/other.mp4'] = {'kind': 'video'}
        self.assertEqual(self.resolve(Job(kind='analysis', project_id='p', payload={'resource': 'videos/old.mp4'})), ['1.2 本集主题.mp4'])
        self.assertEqual(self.resolve(Job(kind='video', project_id='p', title='课程')), [])

    def test_legacy_single_video_and_missing_project(self):
        self.assertEqual(self.resolve(Job(kind='video', project_id='p', title='课程')), ['1.2 本集主题.mp4'])
        self.get.side_effect = KeyError('gone')
        resolve = task_files.filename_labels()
        self.assertEqual(resolve(Job(kind='video', project_id='deleted', title='课程')), [])
        self.assertEqual(resolve(Job(kind='video', project_id='deleted', result={'resource': 'videos/历史.mp4'})), ['历史.mp4'])

    def test_naming_selected_files_and_applied_preview(self):
        entry = {'project_id': 'p', 'files': [{'resource': 'videos/old.mp4', 'filename': 'old.mp4'}]}
        with patch.object(task_files.resource_renames, 'load_plan', return_value={'entries': [entry]}) as load:
            job = Job(kind='naming', project_id='p', result={'plan_id': 'plan'})
            self.assertEqual(self.resolve(job), ['1.2 本集主题.mp4']); self.resolve(job)
            load.assert_called_once_with('plan')
        with patch.object(task_files.resource_renames, 'load_plan', return_value={'preview': {'moves': [{'project_id': 'p', 'resource': 'videos/old.mp4', 'source': 'videos/old.mp4'}]}}):
            self.assertEqual(task_files.filename_labels()(job), ['1.2 本集主题.mp4'])

    def test_naming_missing_plan_does_not_guess_anchor_episode(self):
        with patch.object(task_files.resource_renames, 'load_plan', side_effect=FileNotFoundError):
            self.assertEqual(self.resolve(Job(kind='naming', project_id='p', result={'plan_id': 'gone'}, title='课程')), [])

    def test_subtitle_category_with_empty_job_kind(self):
        files = [{'name': 'old.srt', 'url': '/api/workspace/projects/p/files/subtitles/source.srt?download=true'}]
        job = Job(kind='', results=[{'project': {'id': 'p'}, 'files': files}], title='课程')
        self.assertEqual(self.resolve(job, 'subtitles'), ['1.2-B站平台字幕.srt'])

    def test_legacy_subtitle_paths_and_windows_basename(self):
        job = Job(kind='', files={'srt': r'D:\中文目录\字幕.srt', 'md': Path('/output/字幕.md')}, title='课程')
        self.assertEqual(self.resolve(job, 'subtitles'), ['字幕.srt', '字幕.md'])

    def test_identical_filenames_in_distinct_episode_folders_are_counted(self):
        job = Job(operation='transcription', files={'a': {'path': '/P1/课.srt'}, 'b': {'path': '/P2/课.srt'}})
        self.assertEqual(self.resolve(job), ['课.srt', '课.srt'])

    def test_translation_states_use_video_but_keep_output_inventory(self):
        for state in ('queued', 'running', 'failed', 'completed'):
            job = Job(kind='transcriptions', operation='translation', state=state, project_id='p', resource='videos/old.mp4',
                      files={'srt': {'relative': 'subtitles/zh.srt', 'project_id': 'p'}})
            self.assertEqual(self.resolve(job, video_only=True), ['1.2 本集主题.mp4'])
            self.assertEqual(self.resolve(job), ['1.2-中文.srt'])

    def test_transcription_source_wins_over_course_named_output(self):
        job = Job(operation='transcription', project_id='p', resource='videos/old.mp4', title='课程不是视频名',
                  files={'srt': {'path': '/output/课程不是视频名.srt'}})
        self.assertEqual(self.resolve(job, video_only=True), ['1.2 本集主题.mp4'])
        self.assertEqual(self.resolve(job), ['课程不是视频名.srt'])

    def test_legacy_translation_infers_only_unique_video(self):
        job = Job(operation='translation', project_id='p', translation={'reference': {'resource': 'subtitles/source.srt'}})
        self.assertEqual(self.resolve(job, video_only=True), ['1.2 本集主题.mp4'])
        self.project['resources']['videos/second.mp4'] = {'kind': 'video'}
        self.assertEqual(self.resolve(job, video_only=True), [])
        self.project['resources']['subtitles/source.srt']['video_resource'] = 'videos/old.mp4'
        self.assertEqual(self.resolve(job, video_only=True), ['1.2 本集主题.mp4'])

    def test_joint_naming_headline_deduplicates_sources_not_distinct_episode_names(self):
        moves = [{'project_id': pid, 'resource': key} for pid, key in [('p', 'videos/old.mp4'), ('q', 'videos/old.mp4'), ('p', 'subtitles/zh.srt')]]
        with patch.object(task_files.resource_renames, 'load_plan', return_value={'preview': {'moves': moves}}):
            job = Job(kind='naming', result={'plan_id': 'joint'})
            self.assertEqual(self.resolve(job, video_only=True), ['1.2 本集主题.mp4', '1.2 本集主题.mp4'])

    def test_uploaded_translation_follows_parent_without_inventing_video(self):
        from video_parser.services import transcription
        parent = Job(id='parent', operation='transcription', owned_input=True, title='现场录音.wav', source=Path('/cache/input.wav'))
        job = Job(id='child', operation='translation', translation={'reference': {'job_id': 'parent'}}, source=Path('/cache/out.srt'))
        with patch.object(transcription, 'get', return_value=parent):
            self.assertEqual(self.resolve(job, video_only=True), ['现场录音.wav'])
        with patch.object(transcription, 'get', return_value=job):
            self.assertEqual(self.resolve(job, video_only=True), [])
        self.assertEqual(self.resolve(Job(operation='translation', source=Path('/output/字幕.srt')), video_only=True), [])

    def test_platform_subtitles_use_unique_linked_episode_video(self):
        job = Job(kind='', results=[{'project': {'id': 'p'}, 'files': []}])
        self.assertEqual(self.resolve(job, 'subtitles', video_only=True), ['1.2 本集主题.mp4'])
        self.project['resources']['videos/second.mp4'] = {'kind': 'video'}
        self.assertEqual(self.resolve(job, 'subtitles', video_only=True), [])

    def test_missing_naming_plan_does_not_use_anchor_video(self):
        with patch.object(task_files.resource_renames, 'load_plan', side_effect=FileNotFoundError):
            self.assertEqual(self.resolve(Job(kind='naming', project_id='p', result={'plan_id': 'gone'}), video_only=True), [])

    def test_presentation_uses_confirmed_then_original_episode_title(self):
        self.project.update(platform='bilibili', part=7, episode_title='2.3 已确认的标题', episodes=[{'part': 7, 'title': '原始分集标题'}])
        job = Job(kind='transcriptions', operation='translation', project_id='p', resource='videos/old.mp4', files={},
                  translation={'reference': {'project_id': 'p', 'resource': 'subtitles/source.srt'}})
        value = self.resolve(job, with_presentation=True)
        self.assertEqual(value['subjects'], [{'project_id': 'p', 'part': 7, 'title': '2.3 已确认的标题'}])
        self.assertEqual({item['role'] for item in value['file_details']}, {'video', 'source_subtitle'})
        del self.project['episode_title']
        self.assertEqual(self.resolve(job, with_presentation=True)['subjects'][0]['title'], '原始分集标题')
        self.project['episodes'] = []
        self.assertEqual(self.resolve(job, with_presentation=True)['subjects'][0]['title'], '')

    def test_presentation_translation_keeps_input_and_output_roles(self):
        job = Job(operation='translation', project_id='p', resource='videos/old.mp4',
                  translation={'reference': {'project_id': 'p', 'resource': 'subtitles/source.srt'}},
                  files={'srt': {'project_id': 'p', 'relative': 'subtitles/zh.srt'}})
        files = self.resolve(job, with_presentation=True)['file_details']
        self.assertEqual([item['role'] for item in files], ['video', 'source_subtitle', 'translation'])
        self.assertEqual(files[-1]['name'], '1.2-中文.srt')

    def test_presentation_batch_uses_preview_scope_not_anchor_or_draft_titles(self):
        records = {'p': {**self.project, 'part': 7, 'episode_title': '第七集'}, 'q': {**self.project, 'part': 9, 'episode_title': '第九集'}}
        self.get.side_effect = lambda pid: records[pid]
        record = {'entries': [{'project_id': pid, 'part': records[pid]['part'], 'files': [{'resource': 'videos/old.mp4'}]} for pid in ('p', 'q')],
                  'rows': [{'project_id': 'p', 'title': '未确认建议'}]}
        job = Job(kind='naming', project_id='q', result={'plan_id': 'batch'})
        with patch.object(task_files.resource_renames, 'load_plan', return_value=record):
            value = self.resolve(job, with_presentation=True)
            self.assertEqual([x['part'] for x in value['subjects']], [7, 9])
            self.assertEqual([x['title'] for x in value['subjects']], ['第七集', '第九集'])
            record['preview'] = {'rows': [{'project_id': 'q'}], 'moves': [{'project_id': 'q', 'resource': 'videos/old.mp4'}]}
            self.assertEqual(self.resolve(job, with_presentation=True)['subjects'], [{'project_id': 'q', 'part': 9, 'title': '第九集'}])

    def test_presentation_standalone_and_missing_plan_are_not_course_names(self):
        job = Job(operation='transcription', owned_input=True, title='现场采访.wav', source=Path('/cache/input.wav'), files={})
        value = self.resolve(job, with_presentation=True)
        self.assertEqual(value['subjects'][0]['title'], '现场采访.wav')
        self.assertEqual(value['file_details'][0]['role'], 'audio')
        with patch.object(task_files.resource_renames, 'load_plan', side_effect=FileNotFoundError):
            self.assertEqual(self.resolve(Job(kind='naming', project_id='p', result={'plan_id': 'gone'}), with_presentation=True)['subjects'], [])

    def test_presentation_subtitle_batch_keeps_noncontiguous_episodes_and_same_names(self):
        job = Job(kind='subtitles', episodes=[2, 4], results=[{'episode': part, 'files': [{'name': '相同.srt'}]} for part in (2, 4)])
        value = self.resolve(job, with_presentation=True)
        self.assertEqual([x['part'] for x in value['subjects']], [2, 4])
        self.assertEqual(len(value['file_details']), 2)


if __name__ == '__main__': unittest.main()
