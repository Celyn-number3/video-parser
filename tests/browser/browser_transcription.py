"""Real browser -> HTTP -> mocked GPU -> validated files; no external websites."""
import json
from pathlib import Path
import socket
import sys
import threading
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright, expect
import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.offline.test_transcription import TranscriptionTests
from video_parser.services import videos as cli
from video_parser.services import library as library
from video_parser.web import routes as workspace
def main():
    fixture = TranscriptionTests()
    fixture.setUp()
    app = FastAPI()
    app.include_router(workspace.router)
    from video_parser.web.task_routes import router as task_router
    app.include_router(task_router)
    app.mount('/', StaticFiles(directory=ROOT / 'frontend/dist', html=True), name='frontend')
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    output = ROOT / 'outputs/verification-transcription'
    output.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'gpu': 'mocked'}
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline: raise RuntimeError('Fixture server did not start')
            time.sleep(.02)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(accept_downloads=True)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                base = f'http://127.0.0.1:{port}'
                page.goto(base)
                page.wait_for_load_state('networkidle')
                # 2026-10-14 UI: page renamed 字幕与转写; source tabs 上传文件 / 已归档视频; language auto-detected.
                page.locator('nav').get_by_role('button', name='字幕与转写').click()
                panel = page.locator('section.transcription-panel')
                expect(panel.get_by_role('button', name='开始转写')).to_be_disabled()
                panel.locator('#transcription-file').set_input_files(str(fixture.source))
                panel.get_by_role('button', name='开始转写').click()
                expect(panel.get_by_label('识别文字')).to_have_value('你好，世界。', timeout=10000)
                for fmt in ('TXT', 'SRT'):
                    with page.expect_download() as downloaded:
                        panel.get_by_role('button', name='下载 ' + fmt, exact=True).click()
                    download = downloaded.value
                    assert download.suggested_filename.endswith('.' + fmt.lower())
                    assert '你好' in Path(download.path()).read_text(encoding='utf-8')
                report['checks'].append('local upload, polling, text display, TXT/SRT browser downloads')
                for width in (1280, 390):
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                    panel.scroll_into_view_if_needed()
                    page.screenshot(path=str(output / f'transcription-{width}.png'))
                report['checks'].append('desktop/mobile layout without horizontal overflow')
                page.set_viewport_size({'width': 1280, 'height': 900})
                bad = fixture.root / 'bad.exe'
                bad.write_bytes(b'bad')
                panel.locator('#transcription-file').set_input_files(str(bad))
                # Non-media files are filtered in the browser before any upload.
                expect(panel.get_by_role('button', name='开始转写')).to_be_disabled()
                report['checks'].append('invalid local file is not submitted')
                project = library.ensure({'platform': '抖音', 'video_id': 'browser', 'title': '浏览器视频'})
                media = {'format': {'duration': '2'}, 'streams': [
                    {'codec_type': 'video', 'width': 640, 'height': 360, 'codec_name': 'h264'}, {'codec_type': 'audio'}]}
                resource = library.import_file(project['id'], fixture.source, 'videos/720p.mp4', 'video', {'media': media})
                page.goto(base + '?project=' + project['id'])
                expect(page.locator('.info-title')).to_contain_text('浏览器视频', timeout=10000)
                page.locator('.subtitle-entry').click()  # 生成字幕 → 字幕与转写 with this video preselected.
                panel = page.locator('section.transcription-panel')
                expect(panel.locator('.source-option.checked')).to_contain_text('浏览器视频')
                panel.get_by_role('button', name='开始转写').click()
                expect(panel.get_by_label('识别文字')).to_have_value('你好，世界。', timeout=10000)
                items = library.get(project['id'])['resources']
                saved = [item for item in items.values() if item['kind'] == 'transcription']
                assert len(saved) == 2 and all(item['video_resource'] == resource for item in saved)
                assert all(path.startswith('subtitles/') and '.本地转写.' in path for path, item in items.items() if item['kind'] == 'transcription')
                report['checks'].append('生成字幕 -> archived video preselected -> transcription saved to project subtitles/')
                assert not errors, errors
                report['checks'].append('no browser runtime errors')
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        fixture.doCleanups()
    (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
