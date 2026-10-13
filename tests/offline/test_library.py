"""Persistent project storage regressions, all resources are isolated in temporary roots."""
from video_parser import cli as cli_entry
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from video_parser.services import library as store
class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(store, 'LIBRARY_ROOT', self.root / 'library').start()
        self.meta = {'platform': '哔哩哔哩', 'video_id': 'BV16NG96QEmA', 'title': '原标题',
                     'source_url': 'https://www.bilibili.com/video/BV16NG96QEmA?p=3&token=private'}

    def test_identity_title_stability_and_parts(self):
        one = store.ensure(self.meta)
        again = store.ensure({**self.meta, 'title': '新标题', 'source_url': self.meta['source_url'] + '&other=1'})
        other = store.ensure({**self.meta, 'source_url': 'https://www.bilibili.com/video/BV16NG96QEmA?p=4'})
        self.assertEqual(one['id'], again['id'])
        self.assertEqual(one['directory'], again['directory'])
        self.assertNotEqual(one['id'], other['id'])
        self.assertIn('P003', str(one['directory']))
        text = (one['directory'] / 'project.json').read_text(encoding='utf-8')
        self.assertNotIn('private', text)
        self.assertNotIn('token=', text)

    def test_import_conflict_no_overwrite_and_export(self):
        project = store.ensure(self.meta)
        source = self.root / 'source.txt'
        source.write_text('first')
        first = store.import_file(project['id'], source, 'subtitles/subtitle.md', 'subtitle')
        self.assertEqual(store.import_file(project['id'], source, 'subtitles/subtitle.md', 'subtitle'), first)
        source.write_text('second')
        second = store.import_file(project['id'], source, 'subtitles/subtitle.md', 'subtitle')
        self.assertNotEqual(first, second)
        self.assertEqual(store.resource(project['id'], first).read_text(), 'first')
        self.assertEqual(store.resource(project['id'], second).read_text(), 'second')
        with ZipFile(store.archive(project['id'])) as zipped:
            self.assertIn('project.json', zipped.namelist())
            self.assertIn(first, zipped.namelist())
            self.assertIn(second, zipped.namelist())
            self.assertFalse(any(name.startswith('.') for name in zipped.namelist()))

    def test_reopen_and_bad_file_not_valid(self):
        p = store.ensure(self.meta)
        source = self.root / 'source'; source.write_bytes(b'content')
        name = store.import_file(p['id'], source, 'video.mp4', 'video')
        self.assertEqual(store.get(p['id'])['id'], p['id'])
        (p['directory'] / name).write_bytes(b'changed')
        with self.assertRaises(ValueError): store.resource(p['id'], name)
        with self.assertRaises(ValueError): store.import_file(p['id'], source, '../escape', 'video')
        with self.assertRaises((KeyError, ValueError)): store.resource(p['id'], '../escape')

    def test_concurrent_same_identity_and_resources(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            projects = list(pool.map(lambda _: store.ensure(self.meta), range(4)))
        self.assertEqual(len({p['id'] for p in projects}), 1)
        p=projects[0]
        source=self.root/'source';source.write_text('one')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: store.import_file(p['id'], source, f'analysis/{i}.md', 'analysis'), range(4)))
        self.assertEqual(len(store.get(p['id'])['resources']),4)

    def test_local_content_identity_and_batch_reports(self):
        source=self.root/'local.mp4';source.write_bytes(b'local content')
        one=store.local_project(source)
        copy=self.root/'renamed.mp4';copy.write_bytes(source.read_bytes())
        self.assertEqual(one['id'],store.local_project(copy)['id'])
        first=store.save_text(one['id'],'analysis','first')
        second=store.save_text(one['id'],'analysis','second')
        self.assertNotEqual(first,second)
        self.assertEqual(store.owner(store.resource(one['id'],first))['id'],one['id'])


class CLIProjectTests(unittest.TestCase):
    setUp = LibraryTests.setUp
    def test_cli_default_cover_and_download_share_project_and_explicit_directory_stays_flat(self):
        from video_parser.services import videos as cli
        parsed = cli.ParsedVideo(self.meta, {}, ['https://fixture/video'], ['https://fixture/audio'])
        media={'streams':[{'codec_type':'video'},{'codec_type':'audio'}],'format':{'duration':2}}
        def download(parsed, target):
            Path(target).write_bytes(b'media')
            return {'path':str(target),'size_bytes':5,'media':media,'title':self.meta['title']}
        def cover(parsed, target):
            from PIL import Image
            Image.new('RGB',(8,8),'green').save(target,format='PNG')
            return {'path':str(target),'size_bytes':Path(target).stat().st_size}
        with patch.object(cli,'parse_link',return_value=parsed), patch.object(cli,'download_video',side_effect=download) as dl, patch.object(cli,'save_cover',side_effect=cover), patch.object(cli,'probe',return_value=media):
            first=cli_entry.execute(cli_entry.build_parser().parse_args(['download','url']))
            second=cli_entry.execute(cli_entry.build_parser().parse_args(['download','url']))
            covered=cli_entry.execute(cli_entry.build_parser().parse_args(['cover','url']))
            self.assertEqual(first['project_id'],covered['project_id'])
            self.assertEqual(first['path'],second['path'])
            self.assertEqual(dl.call_count,1)
            explicit=self.root/'explicit';explicit.mkdir()
            flat=cli_entry.execute(cli_entry.build_parser().parse_args(['download','url','--output-dir',str(explicit)]))
            self.assertEqual(Path(flat['path']).parent,explicit)
            listed=cli_entry.execute(cli_entry.build_parser().parse_args(['list']))
            self.assertIn(first['path'],[item['path'] for item in listed['files']])


if __name__ == '__main__': unittest.main()
