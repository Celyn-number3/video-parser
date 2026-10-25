"""Naming only: synthetic files, no model generation or real archive mutations."""
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from video_parser.services import subtitle_names as labels, transcription, library, resource_renames as names, study
from tests.offline import test_subtitle_naming as oldtests

class ReadableSubtitleNamesTests(unittest.TestCase):
    def test_current_episode_overrides_stale_job_title_and_preserves_number(self):
        job=SimpleNamespace(project_id='p',title='课程长名.本地转写.en',owned_input=False,detected_language='en')
        with patch.object(library,'get',return_value={'episode_title':'1.1 线性方程组的几何解释'}):
            self.assertEqual(transcription.output_name(job,'srt'),'1.1 线性方程组的几何解释-英文-本地转写.srt')
        job.project_id=None;job.owned_input=True;job.title='1.1 课程.wav'
        self.assertEqual(transcription.output_name(job,'srt'),'1.1 课程-英文-本地转写.srt')
    def test_languages_and_typed_provenance_without_filename_guessing(self):
        self.assertEqual(labels.suffix('translation','zh','transcription'),' -中文-AI译文-本地转写'.strip())
        self.assertEqual(labels.suffix('translation','en',None),'-英文-AI译文-来源未确认')
        self.assertEqual(labels.suffix('subtitle','',platform='bilibili'),'-B站平台字幕')
        self.assertEqual(labels.language_label('../../unsafe'),'')
        self.assertEqual(labels.language_label('zh-TW'),'繁体中文')
        self.assertEqual(names._subtitle_suffix({'resources':{},'platform':'bilibili'},'课程.平台字幕.en.srt',{'kind':'translation','language':'en'}),'-英文-AI译文-来源未确认')
    def test_joint_rename_duplicate_tracks_aliases_content_and_restore(self):
        h=oldtests.SubtitleNamingTests('test_reuse_subtitle_name_without_any_model_and_restore_associations');h.setUp();self.addCleanup(h.doCleanups)
        raw=h.root/'local.srt';raw.write_text('1\n00:00:00,000 --> 00:00:02,000\nSynthetic.\n',encoding='utf-8')
        local=library.import_file(h.pid,raw,'subtitles/旧课程.本地转写.en.srt','transcription',{'language':'en','video_resource':h.resource})
        other=library.import_file(h.pid,raw,'subtitles/另一版本.en.srt','transcription',{'language':'en','video_resource':h.resource})
        translated=library.import_file(h.pid,raw,'subtitles/旧课程.en.AI翻译.zh.srt','translation',{'language':'zh','source_resource':local,'source_sha256':library.digest(raw),'video_resource':h.resource})
        before=library.get(h.pid);keys=set(before['resources']);hashes={k:library.digest(library.resource(h.pid,k)) for k in keys}
        plan=h.plan();plan.update(rename_scope=names.JOINT_SCOPE,source='manual');names.save_plan(plan)
        preview=names.validate(plan['id'],plan['rows'])
        targets=[m['target'] for m in preview['moves'] if m['project_id']==h.pid]
        self.assertEqual(len(targets),len(set(targets)))
        self.assertEqual(len([t for t in targets if t.endswith('-英文-本地转写.srt')]),2)
        self.assertIn('subtitles/1.1 变量基础-中文-AI译文-本地转写.srt',targets)
        names.apply(plan['id'],preview['preview_token']);after=library.get(h.pid)
        self.assertEqual(set(after['resources']),keys)
        self.assertEqual(after['resources'][translated]['source_resource'],local)
        self.assertEqual(study.notes(h.pid,h.resource),h.notes_before)
        self.assertEqual({k:library.digest(library.resource(h.pid,k)) for k in keys},hashes)
        job=SimpleNamespace(project_id=h.pid)
        self.assertEqual(transcription.output_filename(job,{'project_id':h.pid,'relative':translated,'path':'stale/path.srt'}),'1.1 变量基础-中文-AI译文-本地转写.srt')
        # Reimport through the renamed path reuses the existing logical key.
        self.assertEqual(library.import_file(h.pid,raw,after['resources'][local]['storage_path'],'transcription',{'language':'en'}),local)
        names.restore(plan['id'])
        self.assertEqual(library.resource(h.pid,local).name,'旧课程.本地转写.en.srt')

if __name__=='__main__':unittest.main()
