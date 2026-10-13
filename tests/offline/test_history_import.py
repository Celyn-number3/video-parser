"""History import is read-only in preview and copy-only, verifiable and idempotent on apply."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_parser.services import history_import as history
from video_parser.services import library as library
class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'legacy';self.source.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(library,'LIBRARY_ROOT',self.root/'library').start()
        patch.object(history.subtitles,'CHECKER_PATH',Path(__file__).resolve().parents[1]/'fixtures'/'subtitle_checker.py').start()
        patch.object(history.videos,'probe',return_value={'streams':[{'codec_type':'video'},{'codec_type':'audio'}],'format':{'duration':'2'}}).start()

    def test_preview_copy_dedup_and_source_preservation(self):
        first=self.source/'标题_BV16NG96QEmA.mp4';first.write_bytes(b'one video')
        duplicate=self.source/'no-id.mp4';duplicate.write_bytes(first.read_bytes())
        pending=self.source/'unknown.mp4';pending.write_bytes(b'other video')
        before={str(p):library.digest(p) for p in self.source.rglob('*') if p.is_file()}
        preview=history.run([self.source],apply=False)
        self.assertFalse(library.LIBRARY_ROOT.exists())
        self.assertEqual(len(preview['items']),3)
        applied=history.run([self.source],apply=True)
        self.assertEqual(applied['failed'],0)
        self.assertTrue(applied['sources_unchanged'])
        self.assertEqual(len(library.manifests()),2)
        self.assertEqual({str(p):library.digest(p) for p in self.source.rglob('*') if p.is_file()},before)
        again=history.run([self.source],apply=True)
        self.assertEqual(again['new_resources'],0)
        self.assertEqual(len(library.manifests()),2)

    def test_subtitle_triplet_unknown_and_incomplete(self):
        for folder,ext in [('_json','json'),('_srt','srt'),('_md','md')]:
            path=self.source/'课程'/folder/f'P01_标题.{ext}';path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps({'body':[{'from':0,'to':1,'content':'字幕'}]}) if ext=='json' else '字幕',encoding='utf-8')
        result=history.run([self.source],apply=True)
        self.assertEqual(result['failed'],0)
        self.assertEqual(len(library.manifests()),1)
        self.assertEqual(library.load(library.manifests()[0])['identity_status'],'pending')
        (self.source/'课程/_md/P01_标题.md').unlink()
        result=history.run([self.source],apply=True)
        self.assertGreater(result['failed'],0)


if __name__ == '__main__':unittest.main()
