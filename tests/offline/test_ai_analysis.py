"""AI 分析：设置、素材、记录、追问和导出。模型调用全部替换为本地假实现。"""
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from video_parser.services import ai_analysis, ai_settings, docx_export, library, task_runtime, workflows
from video_parser.web.app import app

SRT = """1
00:00:00,500 --> 00:00:02,000
大家好

2
00:00:02,000 --> 00:00:04,000
今天讲<i>矩阵</i>

3
00:00:04,500 --> 00:00:05,500
谢谢观看
"""


class FakeClient:
    def __init__(self, calls, answer='## 摘要\n- [00:02] 讲矩阵'):
        self.calls, self.answer = calls, answer
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.calls.append(request)
        usage = SimpleNamespace(prompt_tokens=123, completion_tokens=45)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))], usage=usage)


class TranscriptTests(unittest.TestCase):
    def test_srt_and_vtt_become_timestamped_lines(self):
        cues = ai_analysis.parse_cues(SRT)
        self.assertEqual(cues, [(0.5, '大家好'), (2.0, '今天讲矩阵'), (4.5, '谢谢观看')])
        vtt = 'WEBVTT\n\n00:01:02.000 --> 00:01:03.000\nhello\nworld\n\n01:02:03.500 --> 01:02:04.000\nbye\n'
        self.assertEqual(ai_analysis.parse_cues(vtt), [(62.0, 'hello world'), (3723.5, 'bye')])
        text, merged = ai_analysis.compact(cues)
        self.assertEqual(text.splitlines()[1], '[00:02] 今天讲矩阵')
        self.assertFalse(merged)

    def test_long_transcripts_are_merged_to_fit(self):
        cues = [(index * 2.0, f'第{index}句话内容') for index in range(3000)]
        text, merged = ai_analysis.compact(cues, limit=20_000)
        self.assertTrue(merged)
        self.assertLessEqual(len(text), 20_000)
        self.assertTrue(text.startswith('[00:00] 第0句话内容'), text[:80])
        self.assertTrue('[1:30:00]' in text, 'still covers the end of the video')

    def test_scene_plan_keeps_opening_and_fills_evenly(self):
        with patch.object(ai_analysis, 'scene_changes', return_value=[(30.0, 0.9), (30.5, 0.8), (70.0, 0.5)]):
            times = ai_analysis.plan_times('video.mp4', 100, 'scene', 5)
        self.assertEqual(len(times), 5)
        self.assertEqual(times[0], 1.0)
        self.assertIn(30.0, times)
        self.assertNotIn(30.5, times)  # Too close to a stronger change.
        self.assertEqual(ai_analysis.plan_times('video.mp4', 60, 'uniform', 2), [20.0, 40.0])
        self.assertEqual(ai_analysis.auto_count(30), 4)
        self.assertEqual(ai_analysis.auto_count(3600), 16)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(ai_settings, 'SETTINGS_PATH', Path(self.temp.name) / 'ai' / 'settings.json').start()
        patch.dict('os.environ', {'QWEN_API_KEY': '', 'QWEN_API_BASE_URL': '', 'QWEN_MODEL_ID': ''}).start()

    def test_key_is_masked_kept_and_dropped_when_service_changes(self):
        self.assertFalse(ai_settings.public()['configured'])
        base = ai_settings.PRESETS['modelscope']['base_url']
        data = ai_settings.save('modelscope', base, 'Qwen/Qwen3-VL-8B-Instruct', 'ms-secret-value-1234')
        self.assertTrue(data['configured'])
        self.assertEqual(data['key_hint'], '••••1234')
        self.assertNotIn('ms-secret-value', json.dumps(data, ensure_ascii=False))
        ai_settings.save('modelscope', base, 'Qwen/Qwen3-VL-235B-A22B-Instruct')  # No key field: keep it.
        self.assertEqual(ai_settings.current()['api_key'], 'ms-secret-value-1234')
        ai_settings.remember_consent()
        self.assertTrue(ai_settings.public()['consented'])
        other = ai_settings.save('dashscope', ai_settings.PRESETS['dashscope']['base_url'], 'qwen3-vl-plus')
        self.assertFalse(other['key_saved'])  # A key never follows the user to a different service.
        self.assertFalse(other['consented'])
        local = ai_settings.save('ollama', 'http://127.0.0.1:11434/v1', 'qwen2.5vl:7b')
        self.assertTrue(local['configured'] and local['local'] and local['consented'])

    def test_rejects_plain_http_for_remote_services(self):
        with self.assertRaises(ValueError):
            ai_settings.save('custom', 'http://example.com/v1', 'model', 'key-123456789')
        with self.assertRaises(ValueError):
            ai_settings.save('custom', 'https://example.com/v1', 'model', 'has space')

    def test_env_fallback_and_api_never_returns_key(self):
        with patch.dict('os.environ', {'QWEN_API_KEY': 'env-secret-abcdefgh'}):
            self.assertEqual(ai_settings.public()['source'], 'env')
            client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))
            for path in ('/api/workspace/ai/settings', '/api/workspace/config'):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('env-secret', response.text)
            self.assertTrue(client.get('/api/workspace/config').json()['ai_configured'])

    def test_model_errors_are_explained_without_details(self):
        error = type('AuthenticationError', (Exception,), {'status_code': 401})('key sk-leak')
        self.assertIn('密钥无效', ai_settings.explain(error))
        self.assertNotIn('sk-leak', ai_settings.explain(error))


@unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg missing')
class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        self.root = Path(self.temp.name)
        patch.object(library, 'LIBRARY_ROOT', self.root / 'library').start()
        patch.object(ai_analysis, 'PREVIEW_ROOT', self.root / 'previews').start()
        patch.object(ai_settings, 'SETTINGS_PATH', self.root / 'settings.json').start()
        patch.object(task_runtime, 'progress').start()
        ai_settings.save('custom', 'https://model.example/v1', 'fixture-vl', 'fixture-key-123456')
        video = self.root / 'clip.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10:duration=6',
                        '-pix_fmt', 'yuv420p', str(video)], check=True)
        project = library.ensure({'platform': '哔哩哔哩', 'video_id': 'BV1Fixture00', 'title': '测试视频'})
        self.pid = project['id']
        self.video = library.import_file(self.pid, video, 'video/测试视频.mp4', 'video')
        srt = self.root / 'a.srt'
        srt.write_text(SRT, encoding='utf-8')
        self.subtitle = library.import_file(self.pid, srt, 'subtitles/测试视频.平台字幕.srt', 'subtitle')
        self.calls = []
        patch.object(ai_settings, 'client', side_effect=lambda *a, **k: FakeClient(self.calls)).start()
        self.work = self.root / 'work'
        self.work.mkdir()

    def payload(self, **extra):
        return {'resource': self.video, 'quality_id': 'q', 'template': 'summary', 'source': 'both', 'count': 3,
                'frame_mode': 'uniform', 'prompt': '', **extra}

    def test_both_sources_reach_model_and_record_is_archived(self):
        record = ai_analysis.run(self.pid, self.payload(prompt='重点看配色'), self.work)
        content = self.calls[0]['messages'][1]['content']
        texts = [part['text'] for part in content if part['type'] == 'text']
        self.assertIn('内容摘要', ai_analysis.TEMPLATES['summary']['name'])
        self.assertIn('补充要求：重点看配色', texts[0])
        self.assertIn('[00:02] 今天讲矩阵', texts[1])
        self.assertEqual(sum(part['type'] == 'image_url' for part in content), 3)
        self.assertEqual(texts[3], '画面 1（00:01）')
        self.assertEqual(record['template_name'], '内容摘要')
        self.assertEqual(record['source'], 'both')
        self.assertEqual(record['transcript_label'], '平台字幕')
        self.assertEqual([frame['label'] for frame in record['frames']], ['00:01', '00:03', '00:04'])
        self.assertEqual(record['usage']['prompt_tokens'], 123)
        self.assertEqual(ai_analysis.records(self.pid)[0]['id'], record['id'])

    def test_transcript_only_sends_no_images_and_missing_subtitles_are_explained(self):
        ai_analysis.run(self.pid, self.payload(template='script', source='transcript'), self.work)
        self.assertIsInstance(self.calls[0]['messages'][1]['content'], str)
        library.remove(self.pid, [self.subtitle])
        with self.assertRaises(ai_analysis.AnalysisError) as caught:
            ai_analysis.run(self.pid, self.payload(template='script', source='transcript'), self.root / 'work')
        self.assertIn('生成转写字幕', str(caught.exception))
        code, message = task_runtime.classify(caught.exception)
        self.assertEqual((code, message), ('invalid_input', caught.exception.user_message))
        # Combined input must never silently downgrade to frames.
        before = len(self.calls)
        with self.assertRaises(ai_analysis.AnalysisError):
            ai_analysis.run(self.pid, self.payload(), self.work)
        self.assertEqual(len(self.calls), before)
        self.assertEqual(ai_analysis.run(self.pid, self.payload(source='frames'), self.work)['source'], 'frames')

    def test_ai_selected_frames_are_extracted_and_archived(self):
        from video_parser.services import model_calls
        from video_parser.services.local_agents.types import Result
        replies = [Result('{"times":[1,4]}', usage={'prompt_tokens': 12}), Result('## 摘要\n[00:01] 说明', usage={}, model='fixture')]
        with patch.object(model_calls, 'call', side_effect=replies) as call:
            record = ai_analysis.run(self.pid, self.payload(frame_mode='ai'), self.work)
        self.assertEqual([frame['time'] for frame in record['frames']], [1, 4])
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args_list[0].kwargs['purpose'], 'frame-plan')
        self.assertEqual(record['source'], 'both')

    def test_preview_selection_is_used_and_tokens_are_not_paths(self):
        preview = ai_analysis.create_preview(self.pid, self.video, 'uniform', 4)
        self.assertEqual(len(preview['frames']), 4)
        keep = [preview['frames'][1]['name'], preview['frames'][3]['name']]
        record = ai_analysis.run(self.pid, self.payload(preview_token=preview['token'], frames=keep), self.work)
        self.assertEqual([frame['time'] for frame in record['frames']], [preview['frames'][1]['time'], preview['frames'][3]['time']])
        for token, name in (('../../x', 'frame_000.jpg'), (preview['token'], '../meta.json'), (preview['token'], 'meta.json')):
            with self.assertRaises(KeyError):
                ai_analysis.preview_file(token, name)

    def test_follow_up_resends_context_and_history_then_delete_cleans_up(self):
        record = ai_analysis.run(self.pid, self.payload(), self.work)
        ai_analysis.ask(self.pid, record['id'], '第一个问题', self.work)
        updated = ai_analysis.ask(self.pid, record['id'], '第二个问题', self.work)
        messages = self.calls[-1]['messages']
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'user', 'assistant', 'user'])
        self.assertEqual(sum(part['type'] == 'image_url' for part in messages[1]['content']), 3)
        self.assertEqual([item['question'] for item in updated['followups']], ['第一个问题', '第二个问题'])
        markdown, filename = ai_analysis.export_markdown(self.pid, record['id'])
        self.assertIn('### 问：第二个问题', markdown)
        self.assertIn('测试视频', filename)
        with ZipFile(io.BytesIO(docx_export.build(markdown, filename))) as package:
            self.assertIn('第二个问题', package.read('word/document.xml').decode('utf-8'))
        directory = library.get(self.pid)['directory']
        ai_analysis.delete(self.pid, record['id'])
        project = library.get(self.pid)
        self.assertFalse(any(item['kind'] in ('analysis', 'analysis-followup', 'frame') for item in project['resources'].values()))
        self.assertFalse((directory / 'analysis').exists())
        self.assertFalse((directory / 'frames').exists())
        self.assertTrue((directory / self.video).is_file())

    def test_clear_context_stops_resending_earlier_follow_ups(self):
        record = ai_analysis.run(self.pid, self.payload(), self.work)
        ai_analysis.ask(self.pid, record['id'], '第一个问题', self.work)
        client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))
        url = f"/api/workspace/projects/{self.pid}/analyses/{record['id']}/clear-context"
        cleared = client.post(url, json={})
        self.assertEqual(cleared.status_code, 200)
        first = cleared.json()['records'][0]
        self.assertEqual(first['context_after'], first['followups'][0]['id'])
        ai_analysis.ask(self.pid, record['id'], '第二个问题', self.work)
        updated = ai_analysis.ask(self.pid, record['id'], '第三个问题', self.work)
        messages = self.calls[-1]['messages']
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'user', 'assistant', 'user'])
        self.assertEqual([m['content'] for m in messages[3::2]], ['第二个问题', '第三个问题'])
        self.assertEqual(sum(part['type'] == 'image_url' for part in messages[1]['content']), 3)
        # Earlier Q&A stays archived and exported; only the model request leaves it out.
        self.assertEqual([item['question'] for item in updated['followups']], ['第一个问题', '第二个问题', '第三个问题'])
        self.assertIn('### 问：第一个问题', ai_analysis.export_markdown(self.pid, record['id'])[0])
        with patch('video_parser.web.analysis_routes.project_busy', return_value=True):
            self.assertEqual(client.post(url, json={}).status_code, 409)
        self.assertEqual(client.post(f'/api/workspace/projects/{self.pid}/analyses/bad-id/clear-context', json={}).status_code, 404)

    def test_api_records_export_and_validation(self):
        record = ai_analysis.run(self.pid, self.payload(), self.work)
        client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))
        base = f'/api/workspace/projects/{self.pid}/analyses'
        self.assertEqual(client.get(base).json()['records'][0]['id'], record['id'])
        docx = client.get(f"{base}/{record['id']}/export?format=docx")
        self.assertEqual(docx.status_code, 200)
        self.assertIn("filename*=UTF-8''", docx.headers['content-disposition'])
        self.assertEqual(client.get(f'{base}/../../etc/export').status_code, 404)
        self.assertEqual(client.get(f'{base}/20260101-000000-deadbeef/export').status_code, 404)
        self.assertEqual(client.post(f"{base}/{record['id']}/ask-task", json={'question': 'x', 'consent': False}).status_code, 422)
        with patch.object(workflows, 'start', return_value={'id': '1' * 32}) as start:
            self.assertEqual(client.post(f"{base}/{record['id']}/ask-task", json={'question': '再详细点', 'consent': True}).status_code, 202)
            self.assertEqual(start.call_args.args[3]['mode'], 'ask')
        self.assertEqual(client.post(f"{base}/{record['id']}/delete", json={'confirm': True}).json()['records'], [])
        context = client.get(f'/api/workspace/projects/{self.pid}/analysis/context', params={'resource': self.video}).json()
        self.assertEqual(context['transcripts'][0]['label'], '平台字幕')
        self.assertEqual(context['auto_frame_count'], 4)
        self.assertNotIn('fixture-key', json.dumps(context))

    def test_task_body_rejects_unknown_template_and_bad_frame_names(self):
        client = TestClient(app, base_url='http://127.0.0.1:15001', client=('127.0.0.1', 1234))
        with patch.object(workflows, 'start') as start:
            for body in ({'consent': True, 'template': 'evil'}, {'consent': True, 'frames': ['../x.jpg']},
                         {'consent': True, 'preview_token': '../../x'}, {'consent': True, 'frames': []}):
                self.assertEqual(client.post('/api/workspace/videos/missing/analyze-task', json=body).status_code, 422, body)
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
