"""Offline: where subtitles/transcripts are saved (video project, another project, picked folder, outputs/)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from video_parser.services import folders, library, transcription
from video_parser.web import routes


class OutputDestinationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        patch.object(folders, 'STATE', self.root / 'state/output-folders.json').start()
        patch.object(library, 'LIBRARY_ROOT', self.root / 'library').start()
        patch.object(transcription, 'OUTPUT_ROOT', self.root / 'outputs').start()
        self.addCleanup(patch.stopall)
        transcription.jobs.clear()
        self.picked = self.root / 'picked'
        self.picked.mkdir()

    def project(self, video_id='BV1xx411c7mD', title='示例视频'):
        return library.ensure({'platform': '哔哩哔哩', 'video_id': video_id, 'title': title,
                               'source_url': f'https://www.bilibili.com/video/{video_id}?p=1'})

    def test_only_picked_folders_are_writable(self):
        with self.assertRaises(PermissionError):
            folders.check(str(self.picked))
        folders.remember(self.picked.resolve())
        self.assertEqual(folders.check(str(self.picked)), self.picked.resolve())
        with self.assertRaises(ValueError):
            folders.check('relative/path')

    def test_publish_never_overwrites(self):
        folders.remember(self.picked.resolve())
        source = self.root / 'a.srt'
        source.write_text('1', encoding='utf-8')
        first = folders.publish(str(self.picked), source, '会议.本地转写.zh.srt')
        source.write_text('2', encoding='utf-8')
        second = folders.publish(str(self.picked), source, '会议.本地转写.zh.srt')
        self.assertEqual(first.name, '会议.本地转写.zh.srt')
        self.assertEqual(second.name, '会议.本地转写.zh (2).srt')
        self.assertEqual(first.read_text(encoding='utf-8'), '1')

    def test_route_destination_validation(self):
        project = self.project()
        self.assertEqual(routes.output_destination('source', source_project=project['id']), {'type': 'project', 'project_id': project['id']})
        self.assertEqual(routes.output_destination('source'), {})
        self.assertEqual(routes.output_destination('default', source_project=project['id']), {})
        with self.assertRaises(HTTPException) as unknown:
            routes.output_destination('project', target_project_id='0' * 32)
        self.assertEqual(unknown.exception.status_code, 400)
        with self.assertRaises(HTTPException) as unpicked:
            routes.output_destination('folder', folder=str(self.picked))
        self.assertEqual(unpicked.exception.status_code, 400)

    def finished_job(self, **values):
        output = self.root / 'whisper-out'
        output.mkdir(exist_ok=True)
        files = {}
        for fmt in ('txt', 'srt'):
            files[fmt] = output / ('input.' + fmt)
            files[fmt].write_text('你好 ' + fmt, encoding='utf-8')
        job = transcription.Job('a' * 32, self.root / 'input.wav', values.pop('title', '示例视频'), 'auto', **values)
        result = {'text': '你好', 'language': 'zh', 'segments': [], 'files': {k: str(v) for k, v in files.items()}}
        with patch.object(transcription, 'transcribe', return_value=result), \
             patch.object(transcription.task_runtime, 'progress'), patch.object(transcription.task_runtime, 'checkpoint'), \
             patch.object(library, 'resource', side_effect=lambda pid, rel: library.contained(library.get(pid)['directory'], rel)):
            transcription.worker(job)
        return job

    def test_archived_video_results_go_to_its_subtitles_folder(self):
        project = self.project()
        job = self.finished_job(project_id=project['id'], resource='videos/480p.mp4')
        self.assertEqual(job.state, 'completed')
        keys = sorted(library.get(project['id'])['resources'])
        self.assertEqual(keys, ['subtitles/示例视频.本地转写.zh.srt', 'subtitles/示例视频.本地转写.zh.txt'])
        self.assertEqual(transcription.saved_to(job)['type'], 'project')

    def test_upload_into_another_project_and_folder(self):
        other = self.project('BV1yy411c7mE', '另一个项目')
        job = self.finished_job(title='会议.wav', owned_input=True, destination={'type': 'project', 'project_id': other['id']})
        self.assertIn('subtitles/会议.本地转写.zh.srt', library.get(other['id'])['resources'])
        folders.remember(self.picked.resolve())
        transcription.jobs.clear()
        job = self.finished_job(title='会议.wav', owned_input=True, destination={'type': 'folder', 'path': str(self.picked.resolve())})
        self.assertTrue((self.picked / '会议.本地转写.zh.srt').is_file())
        self.assertEqual(transcription.saved_to(job), {'type': 'folder', 'location': str(self.picked.resolve())})
        self.assertEqual(transcription.download_file.__name__, 'download_file')

    def test_default_destination_is_outputs(self):
        job = transcription.Job('b' * 32, self.root / 'x.wav', 'x.wav', 'auto', owned_input=True)
        self.assertEqual(transcription.saved_to(job)['location'], 'outputs/transcriptions/' + 'b' * 32)


if __name__ == '__main__':
    unittest.main()
