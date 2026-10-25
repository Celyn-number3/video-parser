"""Read-only grouping/provenance regressions; synthetic files, no model/network calls."""
import json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from video_parser.services import library,transcription,subtitle_versions

class SubtitleVersionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.addCleanup(patch.stopall);patch.object(library,'LIBRARY_ROOT',self.root/'library').start();patch.object(transcription,'OUTPUT_ROOT',self.root/'transcriptions').start()
        self.project=library.ensure({'platform':'bilibili','video_id':'BV1TaqYBcEJc','title':'fixture','source_url':'https://www.bilibili.com/video/BV1TaqYBcEJc?p=1'})
        self.pid=self.project['id'];self.number=0
        self.source=self.add('original','subtitle','srt');self.source_sha=library.get(self.pid)['resources'][self.source]['sha256']
    def add(self,text,kind='translation',fmt='txt',**details):
        self.number+=1;p=self.root/f'{self.number}.{fmt}';p.write_text(text,encoding='utf-8')
        if kind=='translation':details={'language':'en','source_resource':self.source,'source_sha256':self.source_sha,**details}
        return library.import_file(self.pid,p,f'subtitles/{p.name}',kind,details)
    def rows(self):
        p=library.get(self.pid);return subtitle_versions.annotate(p,library.translation_records(p))
    def journal(self,keys,identifier='a'*32,**overrides):
        p=library.get(self.pid);job={'id':identifier,'state':'completed','project_id':self.pid,'created':1792841694.48,'files':{str(i):{'relative':k,'sha256':p['resources'][k]['sha256']} for i,k in enumerate(keys)},**overrides}
        folder=transcription.OUTPUT_ROOT/'.tasks';folder.mkdir(parents=True,exist_ok=True);(folder/f'{identifier}.json').write_text(json.dumps({'version':1,'job':job}),encoding='utf-8')
    def pair(self,body='same\nsame'):
        return [self.add('1\n00:00:01,000 --> 00:00:02,000\n'+body+'\n',fmt='srt'),self.add(body+'\n')]
    def test_srt_txt_pair_one_result_preserves_duplicates_and_actual_date(self):
        keys=self.pair();self.journal(keys);rows=self.rows();self.assertEqual(len({r['version_id'] for r in rows}),1);self.assertEqual({r['generated_at'] for r in rows},{1792841694.48});self.assertEqual({r['format'] for r in rows},{'SRT','TXT'})
        self.add('same');self.assertEqual(len({r['version_id'] for r in self.rows()}),2)
    def test_three_bodies_remain_three_results_six_files_and_no_writes(self):
        for i in range(3):self.pair('body'+str(i))
        before={str(p):(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in self.root.rglob('*') if p.is_file()}
        rows=self.rows();self.assertEqual(len(rows),6);self.assertEqual(len({r['version_id'] for r in rows}),3);self.assertTrue(all(r['generated_at'] is None for r in rows))
        self.assertEqual(before,{str(p):(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in self.root.rglob('*') if p.is_file()})
    def test_same_text_different_source_and_target_separate(self):
        self.pair();self.add('same\nsame',language='zh');other=self.add('other','subtitle');self.add('same\nsame',source_resource=other,source_sha256=library.get(self.pid)['resources'][other]['sha256'])
        self.assertEqual(len({r['version_id'] for r in self.rows()}),3)
    def test_duplicate_format_tracks_never_collapse(self):
        self.pair();self.add('1\n00:00:10,000 --> 00:00:11,000\nsame\nsame\n',fmt='srt');self.assertEqual(len({r['version_id'] for r in self.rows()}),3)
    def test_distinct_recorded_jobs_with_identical_body_stay_separate(self):
        keys=self.pair();self.journal([keys[0]]);self.journal([keys[1]],'b'*32);self.assertEqual(len({r['version_id'] for r in self.rows()}),2)
    def test_ambiguous_or_foreign_generation_does_not_invent_date(self):
        keys=self.pair();self.journal(keys,project_id='other');self.assertTrue(all(r['generated_at'] is None for r in self.rows()))
        self.journal(keys);self.journal(keys,'b'*32);self.assertTrue(all(r['generated_at'] is None for r in self.rows()))
    def test_unique_hash_recovers_only_missing_source_without_mutation(self):
        key=self.add('old',source_resource=None);row=self.rows()[0];self.assertEqual(row['source_resource'],self.source);self.assertEqual(row['source_origin'],'platform');self.assertEqual(row['source_resolution'],'verified_hash');self.assertEqual(row['source_language'],'');self.assertIsNone(library.get(self.pid)['resources'][key]['source_resource'])
    def test_conflicting_explicit_source_is_not_overridden(self):
        key=self.add('old',source_resource='subtitles/missing.srt');row=self.rows()[0];self.assertEqual(row['source_origin'],'unknown');self.assertEqual(row['source_resource'],'subtitles/missing.srt')
    def test_nonunique_hash_or_wrong_video_is_not_guessed(self):
        self.add('original','subtitle','srt');self.add('old',source_resource=None);self.assertEqual(self.rows()[0]['source_origin'],'unknown')
    def test_corrupt_journal_or_invalid_srt_kept_separate(self):
        self.add('bad\n00:00:01,000 --> 00:00:02,000\nsame',fmt='srt');self.add('same');self.journal([],created=float('nan'));self.assertEqual(len({r['version_id'] for r in self.rows()}),2)

    def test_different_video_hash_candidate_is_not_used(self):
        library.update_details(self.pid,self.source,{'video_resource':'videos/other.mp4'})
        self.add('old',source_resource=None,video_resource='videos/current.mp4')
        self.assertEqual(self.rows()[0]['source_origin'],'unknown')
    def test_wrong_output_hash_does_not_establish_generation_date(self):
        keys=self.pair();self.journal(keys,files={'srt':{'relative':keys[0],'sha256':'0'*64}})
        self.assertTrue(all(r['generated_at'] is None for r in self.rows()))
    def test_modified_source_bytes_do_not_verify_a_stale_hash(self):
        self.add('old',source_resource=None)
        library.resource(self.pid,self.source).write_text('modified',encoding='utf-8')
        self.assertEqual(self.rows()[0]['source_origin'],'unknown')
