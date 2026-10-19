"""React E2E: built UI -> real FastAPI -> real CLI/ffmpeg -> playable/downloadable files.
Only platform parsing and the remote model are replaced by local fixtures.
Run from the project root after npm --prefix frontend run build.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import sync_playwright, expect
import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from video_parser.services import videos as cli
from video_parser.web import routes as workspace
from video_parser.services import subtitles
from video_parser.services import library as library
def check_layout(page, width):
    page.set_viewport_size({'width': width, 'height': 1000 if width > 900 else 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}'
    preview = page.locator('.preview-panel').bounding_box()
    details = page.locator('.details-panel').bounding_box()
    if width > 900:
        assert details['x'] >= preview['x'] + preview['width']
    else:
        assert details['y'] >= preview['y'] + preview['height']
    title = page.locator('.info-title p').bounding_box()
    platform_label = page.locator('.info-title + .info-field .field-label').bounding_box()
    gap = platform_label['y'] - title['y'] - title['height']
    assert 18 <= gap <= 22, f'Title spacing must follow content, got {gap}px at {width}px'
    hint = page.locator('.quality-field .notice')
    if hint.count():
        select_box = page.locator('#video-quality').bounding_box()
        hint_box = hint.bounding_box()
        gap = hint_box['y'] - select_box['y'] - select_box['height']
        assert gap >= 12, f'Quality hint must clear the focus outline, got {gap}px at {width}px'
    box = page.locator('.media-stage:visible').bounding_box()
    assert abs(box['width'] / box['height'] - 16 / 9) < .02, box
    for control in (page.get_by_role('button', name='解析视频', exact=True), page.locator('.download-button'), page.get_by_role('button', name='清空内容', exact=True)):
        bounds = control.bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width + 1
    return {'width': width, 'preview_width': round(preview['width']), 'stacked': width <= 900}


def check_shadows(page):
    missing = page.locator('body *:visible').evaluate_all("""elements => elements.filter(el => {
      const s = getComputedStyle(el);
      return (el.tagName === 'BUTTON' || ['Top', 'Right', 'Bottom', 'Left'].some(side =>
        parseFloat(s['border' + side + 'Width']) > 0 && !['none', 'hidden'].includes(s['border' + side + 'Style'])))
        && s.boxShadow === 'none';
    }).map(el => el.id || el.className || el.tagName)""")
    assert not missing, f'Missing shadows: {missing}'


def subtitle_downloads(page, panel, expected, message):
    received = []
    def collect(download):
        received.append(download)
    page.on('download', collect)
    try:
        panel.get_by_role('button', name='下载字幕', exact=True).click()
        expect(panel.get_by_role('status')).to_have_text(message, timeout=15000)
        deadline = time.monotonic() + 8
        while len(received) < expected and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        page.wait_for_timeout(200)
        assert len(received) == expected, f'Expected {expected} automatic files, got {[item.suggested_filename for item in received]}'
        assert all(download.failure() is None for download in received)
        for suffix in ('.json', '.srt', '.md'):
            assert sum(Path(item.suggested_filename).suffix == suffix for item in received) == expected // 3
        assert panel.locator('a[download]:not(.project-panel a)').count() == 0, 'Keep automatic subtitle delivery; only project export is a separate action'
        assert panel.locator('button:not(.project-panel button)').count() == 1, 'Only one subtitle action in the normal state'
        return received
    finally:
        page.remove_listener('download', collect)


def check_icons(page):
    approved = {
        '.brand-mark': 'clapperboard', '.parse-button': 'link-2',
        '#tab-0': 'image', '#tab-1': 'circle-play', '#tab-2': 'scan-eye',
        '.clear-button': 'eraser', '.download-button': 'download',
        '.workspace-help summary': 'chevron-down',
    }
    for selector, name in approved.items():
        icon = page.locator(f'{selector} svg[data-icon="lucide:{name}"]')
        assert icon.count() == 1, f'Missing approved icon: {selector} / {name}'
        assert icon.get_attribute('aria-hidden') == 'true'
        assert icon.get_attribute('focusable') == 'false'
    assert page.locator('.film-icon[data-icon="lucide:circle-play"]').count() == 1
    assert page.locator('svg[data-icon]:visible').evaluate_all("elements => elements.every(el => el.getBoundingClientRect().width > 0)")


def main():
    assert (ROOT / 'frontend/dist/index.html').is_file(), 'Build the React frontend first'
    output = ROOT / '.local/work/artifacts/react-preview'
    output.mkdir(parents=True, exist_ok=True)
    report = {'platform_requests': 0, 'paid_model_requests': 0, 'checks': []}
    with tempfile.TemporaryDirectory(prefix='react-e2e-') as directory:
        root = Path(directory)
        media = root / 'fixture.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=12',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '2', '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(media)], check=True)
        for name, args in [('video-only.mp4', ['-an', '-c:v', 'copy']), ('audio.m4a', ['-vn', '-c:a', 'copy'])]:
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(media), *args, str(root / name)], check=True)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(media),'-an','-vf','scale=320:180','-c:v','libx264','-pix_fmt','yuv420p',str(root/'low.mp4')],check=True)
        Image.new('RGB', (640, 360), '#75ae92').save(root / 'cover.png')
        subtitle_tool = root / 'subtitle-tool'
        subtitle_tool.mkdir()
        (subtitle_tool / 'b站.py').write_text("""import json,sys,time
from pathlib import Path
root=Path.cwd()
time.sleep(.4)
if (root/'login-required').exists():
    print('缺少登录 Cookie：无头模式无法在浏览器窗口扫码。',flush=True)
    sys.exit(1)
args=sys.argv[1:]
selected=list(range(1,5)) if '--all' in args else [int(value) for value in args[args.index('--ep')+1].split(',')]
print('series: 本地字幕验证  (BV1TaqYBcEJc)',flush=True)
valid=[value for value in selected if value<=4]
print(f'selected {len(valid)}/4 episodes: {valid}',flush=True)
for episode in valid:
    name=f'P{episode:02d}_第{episode}节'
    directory=root/'subtitle_download'/'本地字幕验证'
    if (directory/'_json'/(name+'.json')).exists():
        print(f'[P{episode}] exists, skip',flush=True)
        continue
    print(f'[P{episode}] 第{episode}节',flush=True)
    for folder,ext in [('_json','json'),('_srt','srt'),('_md','md')]:
        target=directory/folder/(name+'.'+ext)
        target.parent.mkdir(parents=True,exist_ok=True)
        text=json.dumps({'body':[{'from':0,'to':1,'content':'本地测试字幕'}]},ensure_ascii=False) if ext=='json' else '本地测试字幕'
        target.write_text(text,encoding='utf-8')
""", encoding='utf-8')
        state = {'retry': 0, 'video_gets': 0, 'model_calls': 0, 'fail_model': False, 'frame_count': 0, 'parse_calls': 0}
        slow_get_started = threading.Event()
        media_get_started = threading.Event()
        media_resume = threading.Event()

        class Fixture(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/slow.mp4':
                    slow_get_started.set()
                    time.sleep(.8)
                    filename = 'fixture.mp4'
                elif self.path == '/retry.mp4':
                    state['retry'] += 1
                    if state['retry'] == 1:
                        self.send_error(503)
                        return
                    filename = 'fixture.mp4'
                else:
                    filename = self.path.lstrip('/')
                if filename == 'video-only.mp4':
                    media_get_started.set()
                    assert media_resume.wait(timeout=15), 'Preview gate was not released'
                path = root / filename
                if filename not in {'fixture.mp4', 'video-only.mp4', 'low.mp4', 'audio.m4a', 'cover.png'} or not path.is_file():
                    self.send_error(404)
                    return
                if filename.endswith('.mp4'):
                    state['video_gets'] += 1
                data = path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                assert self.path == '/v1/chat/completions'
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                content = body['messages'][0]['content']
                images = [part for part in content if part['type'] == 'image_url']
                assert images and all(part['image_url']['url'].startswith('data:image/jpeg;base64,') for part in images)
                state['frame_count'] = len(images)
                state['model_calls'] += 1
                if state['fail_model']:
                    self.send_error(400)
                    return
                result = {'id': 'local-fixture', 'object': 'chat.completion', 'created': 0, 'model': 'fixture',
                    'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '本地测试画面：彩色测试图。仅分析画面。'}, 'finish_reason': 'stop'}]}
                data = json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        fixture = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
        fixture_thread.start()
        base = f'http://127.0.0.1:{fixture.server_port}'

        def parse_link(text):
            state['parse_calls'] += 1
            if 'invalid' in text:
                raise ValueError('fixture invalid URL')
            if 'slow' in text:
                time.sleep(.8)
            is_bilibili = 'bilibili' in text
            part = int(parse_qs(urlparse(text).query).get('p', ['1'])[0]) if is_bilibili else None
            video = '/video-only.mp4' if is_bilibili else '/slow.mp4' if 'slow-download' in text else '/retry.mp4' if 'retry' in text else '/fixture.mp4'
            parsed = cli.ParsedVideo({'title': '本地音视频合并验证' if is_bilibili else '本地视频验证',
                'bilibili_cookie_status': 'reused_unverified' if is_bilibili else None,
                'platform': '哔哩哔哩' if is_bilibili else '抖音', 'video_id': 'BV1TaqYBcEJc' if is_bilibili else text.rstrip('/').split('/')[-1],
                'source_url': f'https://www.bilibili.com/video/BV1TaqYBcEJc?p={part}' if is_bilibili else text,
                'episodes': [{'part': 1, 'title': '第一讲', 'duration': 75}, {'part': 2, 'title': '核心内容', 'duration': 180}, {'part': 3, 'title': '总结', 'duration': 120}] if is_bilibili else [],
                'cover_url': base + ('/missing.png' if 'no-cover' in text else '/cover.png'),
                'duration': 2, 'video_url': base + video}, {}, [base + video], [base + '/audio.m4a'] if is_bilibili else [])
            if is_bilibili:
                parsed.variants = {
                    '360p': {'id':'360p','label':'360p','width':640,'height':360,'codec':'avc1','video_urls':[base+'/video-only.mp4']},
                    '180p': {'id':'180p','label':'180p','width':320,'height':180,'codec':'avc1','video_urls':[base+'/low.mp4']},
                }
            return cli.select_quality(parsed, 'best')


        with patch.object(cli, 'parse_link', side_effect=parse_link), patch.object(workspace, 'WORKSPACE_ROOT', root / 'workspace'), \
             patch.object(library, 'LIBRARY_ROOT', root / 'library'), patch.object(subtitles, 'TOOL_ROOT', subtitle_tool), patch.object(subtitles, 'CACHE_ROOT', root / 'subtitle-cache'), \
             patch.dict(os.environ, {'QWEN_API_KEY': 'local-fixture-key', 'QWEN_API_BASE_URL': base + '/v1'}):
            from video_parser.services import analysis as qwen3vl
            with patch.object(qwen3vl, 'API_KEY', 'local-fixture-key'), patch.object(qwen3vl, 'API_BASE_URL', base + '/v1'):
                from video_parser.web import app as api
                sock = socket.socket()
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(api.app, host='127.0.0.1', port=port, log_level='error'))
                thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
                thread.start()
                deadline = time.monotonic() + 15
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.05)
                assert server.started, 'FastAPI failed to start'
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        url = f'http://127.0.0.1:{port}'
                        page.goto(url)
                        page.wait_for_load_state('networkidle')
                        source = page.get_by_role('textbox', name='视频链接或分享文本')
                        status = page.locator('.details-panel').get_by_role('status')
                        parse_button = page.get_by_role('button', name='解析视频', exact=True)
                        download_button = page.locator('.download-button')
                        assert page.get_by_role('button', name='导出视频', exact=True).count() == 0
                        assert page.locator('.download-file').count() == 0
                        expect(source).to_be_visible()
                        expect(download_button).to_be_disabled()
                        check_icons(page)
                        report['layout']=[check_layout(page,w) for w in (1440,768,390,320)]
                        check_shadows(page)
                        page.screenshot(path=str(output/'mobile.png'),full_page=True)
                        page.set_viewport_size({'width':1440,'height':1000})
                        page.screenshot(path=str(output/'desktop.png'),full_page=True)
                        page.get_by_role('tab',name='AI 分析').focus();page.keyboard.press('ArrowLeft')
                        expect(page.get_by_role('tab',name='视频')).to_be_focused()
                        page.keyboard.press('End')
                        expect(page.get_by_role('tab',name='AI 分析')).to_be_focused()
                        expect(page.get_by_role('button',name='开始分析')).to_be_disabled()
                        page.get_by_role('button',name='设置',exact=True).click()
                        page.get_by_label('归档完成提醒',exact=True).check()
                        page.locator('.app-sidebar').get_by_role('button', name='视频工作台', exact=True).click()
                        page.get_by_role('button',name='哔哩哔哩',exact=True).click()
                        before_parse=state['parse_calls']
                        parse_button.evaluate('el=>{el.click();el.click()}')
                        expect(status).to_have_text('解析完成，请选择清晰度后下载归档',timeout=15000)
                        assert state['parse_calls']==before_parse+1
                        assert state['video_gets']==0, 'Parsing must not fetch video tracks'
                        expect(page.get_by_text('已尝试复用字幕工具登录态；画质以本次返回和账号权限为准。')).to_be_visible()
                        for width in (1440,768,390,320): check_layout(page,width)
                        page.set_viewport_size({'width':1440,'height':1000})
                        expect(page.get_by_role('img')).to_be_visible()
                        quality=page.get_by_label('视频清晰度',exact=True)
                        expect(quality).to_have_value('360p')
                        assert quality.locator('option').all_text_contents()==['360p','180p']
                        page.screenshot(path=str(output/'quality-parsed.png'),full_page=True)
                        quality.select_option('180p')
                        with page.expect_download() as cover_download:
                            page.get_by_role('link',name='保存封面').click()
                        with Image.open(cover_download.value.path()) as cover: assert cover.size==(640,360)
                        accidental=[]
                        def delivery(item):accidental.append(item)
                        page.on('download',delivery)
                        download_button.click()
                        expect(status).to_have_text('所选视频已归档',timeout=20000)
                        expect(page.locator('.archive-reminder')).to_have_text('视频已归档×')
                        page.get_by_role('button',name='关闭归档提醒').click()
                        assert not accidental,'Archive download must not automatically export'
                        page.remove_listener('download',delivery)
                        page.get_by_role('tab',name='视频').click()
                        page.wait_for_function("document.querySelector('video')?.readyState>=2")
                        low_url=page.locator('video').get_attribute('src')
                        assert page.locator('video').evaluate('el=>el.videoHeight')==180
                        assert state['video_gets']==1
                        quality.select_option('360p')
                        assert page.locator('video').count()==0
                        download_button.click()
                        assert media_get_started.wait(timeout=3)
                        quality.select_option('180p')
                        expect(status).to_have_text('已选择归档视频')
                        media_resume.set()
                        page.wait_for_timeout(1200)
                        assert page.locator('.archive-reminder').count()==0, 'Stale prepare response must not show completion reminder'
                        assert page.locator('video').get_attribute('src')==low_url, 'Late high-quality download must not replace current low selection'
                        quality.select_option('360p')
                        download_button.click()
                        expect(status).to_have_text('所选视频已归档',timeout=20000)
                        page.wait_for_function("document.querySelector('video')?.readyState>=2")
                        high_url=page.locator('video').get_attribute('src')
                        assert high_url!=low_url
                        assert page.locator('video').evaluate('el=>el.videoHeight')==360
                        assert state['video_gets']==2
                        quality.select_option('180p')
                        expect(status).to_have_text('已选择归档视频')
                        assert page.locator('video').get_attribute('src')==low_url
                        assert state['video_gets']==2
                        check_layout(page,1440);check_shadows(page)
                        page.screenshot(path=str(output/'quality-loaded.png'),full_page=True)
                        page.get_by_role('tab',name='AI 分析').click()
                        expect(page.get_by_role('button',name='开始分析')).to_be_disabled()
                        page.get_by_label('同意将抽样画面发送给模型服务，并了解可能产生费用').check()
                        page.get_by_label('抽样帧数').select_option('4')
                        state['fail_model']=True
                        page.get_by_role('button',name='开始分析').click()
                        expect(status).to_contain_text('分析失败',timeout=20000)
                        state['fail_model']=False
                        page.get_by_role('button',name='开始分析').click()
                        expect(page.get_by_label('分析结果')).to_have_value('本地测试画面：彩色测试图。仅分析画面。',timeout=20000)
                        assert state['frame_count']==4
                        project_id=low_url.split('/projects/')[1].split('/')[0]
                        pinfo=library.get(project_id)
                        report_name=next(name for name,item in pinfo['resources'].items() if item['kind']=='analysis')
                        assert pinfo['resources'][report_name]['video_resource']==low_url.split('/files/')[1]
                        page.reload();page.wait_for_load_state('networkidle')
                        expect(status).to_have_text('已恢复视频项目')
                        page.get_by_role('tab',name='视频').click()
                        assert page.locator('video').get_attribute('src')==low_url
                        quality=page.get_by_label('视频清晰度',exact=True)
                        assert len(quality.locator('option').all_text_contents())==2
                        from zipfile import ZipFile
                        assert page.get_by_role('link',name='导出项目 ZIP').count() == 0
                        report['checks'].append('parse-only no video fetch; real 180p/360p selection, merge, removed export controls, reuse, exact AI version and reload')
                        page.get_by_role('button',name='清空内容').click()
                        source.fill('https://www.douyin.com/video/slow')
                        parse_button.click();expect(status).to_contain_text('正在解析')
                        page.get_by_role('button',name='清空内容').click()
                        page.wait_for_timeout(1200);expect(status).to_have_text('等待解析')
                        source.fill('https://www.douyin.com/video/slow-download')
                        parse_button.click()
                        expect(status).to_have_text('解析完成，请选择清晰度后下载归档',timeout=15000)
                        expect(page.get_by_label('视频清晰度').locator('option')).to_have_text('平台提供的默认画质')
                        download_button.click()
                        assert slow_get_started.wait(timeout=3)
                        source.fill('https://www.douyin.com/video/new')
                        page.wait_for_timeout(1200)
                        expect(status).to_have_text('等待解析')
                        assert page.locator('video').count()==0
                        source.fill('invalid');parse_button.click()
                        expect(status).to_contain_text('链接无效')
                        source.fill('https://www.douyin.com/video/retry');parse_button.click()
                        expect(status).to_have_text('解析完成，请选择清晰度后下载归档')
                        download_button.click();expect(status).to_contain_text('视频准备失败',timeout=15000)
                        download_button.click();expect(status).to_have_text('所选视频已归档',timeout=15000)
                        source.fill('https://www.douyin.com/video/no-cover');parse_button.click()
                        expect(status).to_contain_text('封面暂时无法加载',timeout=15000)
                        expect(page.get_by_text('暂无可用封面')).to_be_visible()
                        with patch.dict(os.environ,{'QWEN_API_KEY':''}):
                            page.reload();page.wait_for_load_state('networkidle')
                            page.get_by_role('tab',name='AI 分析').click()
                            expect(page.get_by_text('请先在本机 .env 配置 QWEN_API_KEY 并重启服务。')).to_be_visible()
                        page.route('**/api/workspace/parse',lambda route:route.abort())
                        source.fill('https://www.douyin.com/video/disconnect');parse_button.click()
                        expect(status).to_have_text('无法连接工作台服务，请确认本地后端正在运行。')
                        page.unroute('**/api/workspace/parse')
                        page.emulate_media(reduced_motion='reduce')
                        assert parse_button.evaluate('el=>getComputedStyle(el).transitionDuration')=='0s'
                        assert page.request.get(url+'/health').status==200
                        assert page.request.post(url+'/api/parse',data={'text':'invalid'}).status==404
                        assert page.request.post(url+'/api/download',data={}).status==404
                        assert not errors,errors
                        report['checks'].append('approved icons/shadows, keyboard tabs, 4-width compact layout, failed download retry, default platform, clear/edit stale guard, config/network errors')
                        # One action: real API -> CLI subprocess -> checker -> JSON/SRT/MD downloads, no ZIP.
                        subtitle_panel = page.locator('.subtitle-panel')
                        subtitle_status = subtitle_panel.get_by_role('status')
                        page.get_by_role('textbox', name='视频链接或分享文本').fill('https://www.bilibili.com/video/BV1TaqYBcEJc?p=3')
                        files = subtitle_downloads(page, subtitle_panel, 3, '本次下载 1 集，已有可用 0 集，未完成 0 集。')
                        expect(subtitle_panel.get_by_text('P3', exact=True)).to_be_visible()
                        assert all(item.suggested_filename.startswith('P03_') for item in files)
                        srt = next(item for item in files if item.suggested_filename.endswith('.srt'))
                        assert '本地测试字幕' in Path(srt.path()).read_text(encoding='utf-8')
                        subtitle_downloads(page, subtitle_panel, 3, '本次下载 0 集，已有可用 1 集，未完成 0 集。')
                        subtitle_panel.get_by_label('下载范围').select_option('custom')
                        subtitle_panel.get_by_label('指定集数').fill('2,8')
                        subtitle_downloads(page, subtitle_panel, 3, '本次下载 1 集，已有可用 0 集，未完成 1 集。')
                        expect(subtitle_panel.get_by_text('超出视频总集数（共 4 集），原 CLI 会过滤此分集。')).to_be_visible()
                        check_shadows(page)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        page.set_viewport_size({'width':1440,'height':1000})
                        page.screenshot(path=str(output/'video_parser.services.subtitles.png'), full_page=True)
                        subtitle_panel.get_by_label('下载范围').select_option('all')
                        subtitle_downloads(page, subtitle_panel, 12, '本次下载 2 集，已有可用 2 集，未完成 0 集。')
                        (subtitle_tool/'login-required').touch()
                        subtitle_panel.get_by_role('button', name='下载字幕', exact=True).click()
                        expect(subtitle_status).to_contain_text('请先在原字幕工具扫码登录', timeout=15000)
                        (subtitle_tool/'login-required').unlink()
                        stale_subtitles = []
                        def collect_stale(item):
                            stale_subtitles.append(item)
                        page.on('download', collect_stale)
                        subtitle_panel.get_by_role('button', name='下载字幕', exact=True).click()
                        page.get_by_role('button', name='清空内容').click()
                        page.wait_for_timeout(1600)
                        expect(subtitle_status).to_have_text('等待下载字幕')
                        assert not stale_subtitles, 'Cleared subtitle result must not download files'
                        page.remove_listener('download', collect_stale)
                        expect(subtitle_panel.get_by_role('button', name='下载字幕', exact=True)).to_be_disabled()
                        assert subtitle_panel.locator('.subtitle-results').count() == 0
                        page.get_by_role('textbox', name='视频链接或分享文本').fill('https://www.douyin.com/video/1')
                        subtitle_panel.get_by_role('button', name='下载字幕', exact=True).click()
                        expect(subtitle_status).to_have_text('字幕下载目前只支持 B站 BV 视频链接。')
                        report['checks'].append('subtitle real subprocess, current/custom/all selection, reused files, automatic JSON/SRT/MD triplets (no ZIP), partial range, login error and stale-result isolation')
                        complete = [library.load(path) for path in library.manifests() if library.load(path)['key'] == 'bilibili:BV1TaqYBcEJc:p1'][0]
                        with ZipFile(library.archive(complete['id'])) as zipped:
                            names = zipped.namelist()
                            assert len([name for name in names if name.startswith('videos/')])==2 and any(name.startswith('cover.') for name in names)
                            assert all('subtitles/subtitle.' + ext in names for ext in ('json','srt','md'))
                            assert any(name.startswith('analysis/') for name in names)
                            assert sum(name.startswith('frames/') for name in names) == 4
                        assert len([library.load(path) for path in library.manifests() if library.load(path)['platform']=='bilibili']) == 4
                        report['checks'].append('same video unifies cover/video/subtitles/frames/analysis, all-P subtitle outputs in four distinct projects')
                        assert not errors, errors
                        cli_env = dict(os.environ, VIDEO_LIBRARY_ROOT=str(root/'library'), QWEN_API_KEY='local-fixture-key', QWEN_API_BASE_URL=base+'/v1')
                        frames_run=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'cli.py'),'frames',str(media),'--count','2','--json'],env=cli_env,capture_output=True,text=True,encoding='utf-8',timeout=30)
                        assert frames_run.returncode == 0,frames_run.stderr
                        frames_result=json.loads(frames_run.stdout)
                        assert len(frames_result['frames'])==2
                        assert all(Path(path).is_file() for path in frames_result['frames'])
                        local=library.get(frames_result['project_id'])
                        analysis_run=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'cli.py'),'analyze',str(local['directory']/'video.mp4'),'--frames','2','--json'],env=cli_env,capture_output=True,text=True,encoding='utf-8',timeout=30)
                        assert analysis_run.returncode == 0,analysis_run.stderr
                        analysis_result=json.loads(analysis_run.stdout)
                        assert analysis_result['project_id']==local['id']
                        assert Path(analysis_result['report_path']).is_file()
                        assert Path(analysis_result['report_path']).is_relative_to(local['directory'])
                        report['checks'].append('standalone CLI subprocess default frames/video/analysis share one project, real ffmpeg and local model')
                        report['fixture_model_calls'] = state['model_calls']
                        browser.close()
                finally:
                    server.should_exit = True
                    thread.join(timeout=10)
                    sock.close()
        fixture.shutdown()
        fixture.server_close()
    (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
