"""Exercise the REAL local Qwen model with synthetic video and subtitles.
Only library paths and progress reporting are isolated; the model client is not mocked.
No personal videos are read and no external model endpoint is allowed.
"""
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont
from video_parser.services import ai_analysis, ai_settings, docx_export, library, task_runtime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from video_parser.core.paths import CACHE_DIR, LOG_DIR
MODEL = 'Qwen3-VL-8B-Instruct-Q4_K_M'
BASE = 'http://127.0.0.1:8888/v1'
HTTP = build_opener(ProxyHandler({}))


def request_json(url, data=None, key=None, timeout=120):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    request = Request(url, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with HTTP.open(request, timeout=timeout) as response:
        return json.load(response)


def main():
    settings = ai_settings.current()
    if settings['provider'] != 'llamacpp' or settings['base_url'] != BASE or settings['model'] != MODEL:
        raise RuntimeError('Refusing to test any endpoint except the intended local Qwen deployment.')
    key = settings['api_key']
    if not key:
        raise RuntimeError('The local model must require an API token.')
    health = request_json('http://127.0.0.1:8888/health', timeout=10)
    assert health.get('status') == 'ok', health
    models = request_json(BASE + '/models', key=key, timeout=10)
    ids = [model.get('id') for model in models.get('data', [])]
    assert MODEL in ids, ids
    print('MODEL_READY:', MODEL, flush=True)
    try:
        request_json(BASE + '/models', timeout=10)
    except HTTPError as error:
        assert error.code == 401, error.code
    else:
        raise AssertionError('Unauthenticated model request was accepted.')
    print('LOCAL_AUTH_REQUIRED: PASS', flush=True)
    connection = request_json('http://127.0.0.1:15001/api/workspace/ai/settings/test', data={})
    assert connection.get('ok') is True, connection
    print('PROJECT_CONNECTION_TEST:', json.dumps(connection, ensure_ascii=False), flush=True)

    parent = CACHE_DIR / 'local-ai-verification'
    parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='qwen-', dir=parent) as temporary:
        work = Path(temporary)
        font = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 90)
        for index, number in enumerate(('7429', '6183'), 1):
            image = Image.new('RGB', (768, 512), 'white')
            draw = ImageDraw.Draw(image)
            draw.text((240, 35), number, fill='black', font=font)
            if index == 1:
                draw.ellipse((100, 210, 320, 430), fill=(230, 30, 30))
                draw.rectangle((445, 210, 665, 430), fill=(20, 80, 235))
            else:
                draw.polygon(((380, 200), (240, 435), (520, 435)), fill=(20, 165, 60))
            image.save(work / f'slide-{index}.jpg', quality=95)
        video = work / 'fixture.mp4'
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-loop', '1', '-framerate', '2', '-t', '2', '-i', str(work / 'slide-1.jpg'),
            '-loop', '1', '-framerate', '2', '-t', '2', '-i', str(work / 'slide-2.jpg'),
            '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video),
        ], check=True, timeout=30)
        subtitle = work / 'fixture.srt'
        subtitle.write_text('1\n00:00:00,000 --> 00:00:04,000\n字幕中的暗号是橙子。\n', encoding='utf-8')
        with patch.object(library, 'LIBRARY_ROOT', work / 'library'), \
             patch.object(ai_analysis, 'PREVIEW_ROOT', work / 'previews'), \
             patch.object(task_runtime, 'progress', side_effect=lambda phase, message: print('PHASE:', phase, flush=True)):
            project = library.ensure({'platform': 'local', 'video_id': 'qwen-local-acceptance', 'title': '本地视觉模型验收'})
            pid = project['id']
            resource = library.import_file(pid, video, 'videos/fixture.mp4', 'video')
            transcript = library.import_file(pid, subtitle, 'subtitles/fixture.平台字幕.srt', 'subtitle')
            task = work / 'task'
            task.mkdir()
            result = ai_analysis.run(pid, {
                'resource': resource, 'quality_id': 'local-test', 'template': 'custom',
                'source': 'both', 'transcript_resource': transcript, 'count': 2, 'frame_mode': 'uniform',
                'prompt': '逐张描述提供的两张画面：写出每张图中的四位数字、图形及颜色。最后写出字幕中给出的暗号。简短回答，不要猜测。',
            }, task)
            text = result['text']
            print('REAL_MULTIMODAL_REPLY:', text, flush=True)
            assert '7429' in text and '6183' in text and '橙子' in text, 'Visual OCR or subtitle evidence missing'
            assert '红' in text and '蓝' in text and '绿' in text, 'Visual color evidence missing'
            assert result['frame_count'] == 2 and result['source'] == 'both'
            assert result['model'] == MODEL
            assert result['usage'].get('prompt_tokens', 0) > 0
            assert ai_analysis.records(pid)[0]['id'] == result['id']
            followup = ai_analysis.ask(pid, result['id'], '只回复字幕里的暗号。', task)
            answer = followup['followups'][-1]['answer']
            assert '橙子' in answer, answer
            print('REAL_FOLLOWUP_REPLY:', answer, flush=True)
            markdown, filename = ai_analysis.export_markdown(pid, result['id'])
            document = docx_export.build(markdown, filename)
            with ZipFile(io.BytesIO(document)) as package:
                assert '橙子' in package.read('word/document.xml').decode('utf-8')
            summary = {
                'model': MODEL, 'endpoint': BASE, 'real_model': True, 'synthetic_media': True,
                'connection_test': True, 'unauthorized_rejected': True, 'visual_ocr': True,
                'colors': True, 'subtitles_and_frames': True, 'followup': True,
                'record_saved': True, 'markdown_docx_export': True,
                'frame_count': result['frame_count'], 'usage': result['usage'],
                'elapsed_seconds': round(time.monotonic() - started, 2), 'reply': text, 'followup_reply': answer,
            }
    logs = LOG_DIR
    logs.mkdir(parents=True, exist_ok=True)
    (logs / 'local-qwen-verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('REAL_LOCAL_AI_VERIFICATION_PASSED', json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
