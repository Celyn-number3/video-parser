"""Synthetic-only compatibility checks for explicit runtime directory migration."""
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_parser.core.paths import runtime_directory, restore_runtime_paths
from video_parser.services import task_runtime


class RuntimeLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vp-layout-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_new_install_uses_local_work_without_creating_directories(self):
        self.assertEqual(runtime_directory('cache', self.root), self.root / '.local/work/cache')
        self.assertEqual(runtime_directory('logs', self.root), self.root / '.local/work/logs')
        self.assertFalse((self.root / '.local').exists())
        with self.assertRaises(ValueError):
            runtime_directory('../library', self.root)

    def test_legacy_is_kept_until_explicit_move_and_two_roots_are_rejected(self):
        old = self.root / 'cache'
        old.mkdir()
        self.assertEqual(runtime_directory('cache', self.root), old)
        target = self.root / '.local/work/cache'
        target.mkdir(parents=True)
        with self.assertRaises(RuntimeError):
            runtime_directory('cache', self.root)
        target.rmdir()
        old.rename(target)
        self.assertEqual(runtime_directory('cache', self.root), target)

    def test_only_absolute_internal_cache_references_are_rebased(self):
        (self.root / '.local/work/cache').mkdir(parents=True)
        old = self.root / 'cache'
        source = {'directory': str(old / 'subtitles/job'), 'files': {'srt': str(old / 'job/result.srt')},
                  'user_note': str(old / 'do-not-rewrite.txt'),
                  'library': str(self.root / 'library/video.mp4'), 'relative': 'cache/test',
                  'outside': str(old / '../library/private.mp4'), 'number': 7}
        result = restore_runtime_paths(source, self.root)
        self.assertEqual(result['directory'], str(self.root / '.local/work/cache/subtitles/job'))
        self.assertEqual(result['files'], {'srt': str(self.root / '.local/work/cache/job/result.srt')})
        for key in ('library', 'relative', 'outside', 'number', 'user_note'):
            self.assertEqual(result[key], source[key])
        old.mkdir()
        self.assertEqual(restore_runtime_paths(source, self.root), source)

    def test_previous_var_tree_is_supported_but_conflicts_are_rejected(self):
        old = self.root / 'var/cache'; old.mkdir(parents=True)
        self.assertEqual(runtime_directory('cache', self.root), old)
        target = self.root / '.local/work/cache'; target.mkdir(parents=True)
        with self.assertRaises(RuntimeError): runtime_directory('cache', self.root)
        old.rmdir()
        value = {'source': str(old / 'input.wav'), 'text': str(old / 'input.wav')}
        rebased = restore_runtime_paths(value, self.root)
        self.assertEqual(rebased['source'], str(target / 'input.wav'))
        self.assertEqual(rebased['text'], value['text'])

    def test_library_model_paths_rebase_but_prose_external_and_traversal_do_not(self):
        (self.root / 'outputs').mkdir()
        (self.root / 'runtimes/models').mkdir(parents=True)
        value = {'source': str(self.root / 'library/bilibili/project/video.mp4'),
                 'path': str(self.root / 'models/whisper/model.bin'),
                 'prompt': str(self.root / 'library/bilibili/project/video.mp4'),
                 'outside': str(self.root / 'library/../private.txt'),
                 'relative': 'library/bilibili/project/video.mp4'}
        result = restore_runtime_paths(value, self.root)
        self.assertEqual(result['source'], str(self.root / 'outputs/bilibili/project/video.mp4'))
        self.assertEqual(result['path'], str(self.root / 'runtimes/models/whisper/model.bin'))
        for key in ('prompt', 'outside', 'relative'): self.assertEqual(result[key], value[key])

    def test_restored_job_uses_moved_directory_without_rewriting_journal(self):
        @dataclass
        class Job:
            id: str
            directory: Path
            state: str = 'completed'
            created_at: float = 0
        target = self.root / '.local/work/cache'
        target.mkdir(parents=True)
        identifier = 'e' * 32
        journal = self.root / (identifier + '.json')
        journal.write_text(json.dumps({'version': 1, 'job': {'id': identifier,
            'directory': str(self.root / 'cache/job'), 'state': 'completed'}}), encoding='utf-8')
        before = journal.read_bytes()
        rebase = lambda value, root=self.root, _field=None: restore_runtime_paths(value, root, _field)
        with patch('video_parser.core.paths.restore_runtime_paths', side_effect=rebase):
            restored = task_runtime.restore(self.root, identifier, Job, ('directory',))
        self.assertEqual(restored.directory, target / 'job')
        self.assertEqual(journal.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
