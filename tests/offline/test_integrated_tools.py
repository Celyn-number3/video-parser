import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from video_parser.core.paths import ROOT
from video_parser.platforms import bilibili_session
from video_parser.services import subtitles, transcription, bili_auth
from video_parser.integrations.whisper import runtime
from video_parser.integrations.bilibili import checker
worker = importlib.import_module('video_parser.integrations.bilibili.b站')


class IntegratedToolsTests(unittest.TestCase):
    def test_whisper_default_paths_inside_project(self):
        with patch.object(transcription,'TOOL_ROOT',transcription.BUNDLED_ROOT):
            self.assertTrue(transcription.runtime_python().is_relative_to(ROOT))
            self.assertEqual(transcription.model_directory(),runtime.MODEL_DIR)
            self.assertEqual(runtime.ROOT,ROOT)

    def test_bili_paths_match_worker_and_main_interpreter(self):
        with patch.object(subtitles,'TOOL_ROOT',subtitles.BUNDLED_ROOT):
            self.assertEqual(subtitles.download_root(),worker.DOWNLOAD_DIR)
            self.assertEqual(bili_auth.cookie_path(),worker.COOKIE_FILE)
            self.assertEqual(subtitles.resolve_checker_path(subtitles.BUNDLED_ROOT),subtitles.BUNDLED_ROOT/'checker.py')
            self.assertEqual(Path(subtitles.command('fixture',[1])[0]),ROOT/'.venv/Scripts/python.exe')

    def test_video_parser_reuses_integrated_login(self):
        with patch.dict(os.environ, {'BILI_SUBTITLE_ROOT':''}):
            self.assertEqual(bilibili_session.cookie_path(),worker.COOKIE_FILE)

    def test_worker_missing_login_is_headless_and_never_visits_login_page(self):
        p=Mock();browser=p.chromium.launch.return_value
        with patch.object(worker,'sync_playwright') as factory,patch.object(worker,'load_cookies',return_value=False):
            factory.return_value.__enter__.return_value=p
            worker.run()
        p.chromium.launch.assert_called_once_with(headless=True)
        browser.new_context.return_value.new_page.return_value.goto.assert_not_called()
        browser.close.assert_called_once()

    def test_episode_selection(self):
        with patch.object(sys,'argv',['b站.py','https://www.bilibili.com/video/BV1TaqYBcEJc','--ep','1-3,5']):
            self.assertEqual(worker.parse_episode_selection(4),[1,2,3])

    def test_worker_outputs_match_integrated_checker(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            worker.save_subtitle_files({'body':[{'from':0,'to':1,'content':'fixture'}]},'P01_fixture',root)
            self.assertTrue(checker.check(root/'_json/P01_fixture.json')['ok'])
            (root/'_srt/P01_fixture.srt').unlink()
            self.assertFalse(checker.check(root/'_json/P01_fixture.json')['ok'])

    def test_runtime_never_falls_back_to_cpu_or_cloud(self):
        with tempfile.TemporaryDirectory() as d:
            model=Path(d);(model/'model.bin').touch();fake=Mock()
            with patch.object(runtime,'MODEL_DIR',model),patch.object(runtime,'configure_runtime'),patch.dict(sys.modules,{'faster_whisper':fake}):
                runtime.load_model()
            fake.WhisperModel.assert_called_once_with(str(model),device='cuda',compute_type='int8_float16',cpu_threads=8,num_workers=1,local_files_only=True)

    def test_fixed_manifest_revision_and_filenames(self):
        data=json.loads((transcription.BUNDLED_ROOT/'model-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(data['revision'],'0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf')
        self.assertEqual({f['path'] for f in data['files']},{'config.json','model.bin','preprocessor_config.json','tokenizer.json','vocabulary.json'})
