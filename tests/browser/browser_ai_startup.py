"""Built UI + real isolated AI settings APIs. No downloads, inference or model launch."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DIST = Path(os.environ.get('VIDEO_PARSER_TEST_DIST', ROOT / 'frontend/dist'))


def main():
    assert (DIST / 'index.html').is_file(), 'Build the frontend first'
    with tempfile.TemporaryDirectory(prefix='ai-startup-browser-中文 空格-') as directory:
        temporary = Path(directory)
        from fastapi import FastAPI
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        import uvicorn
        from video_parser.services import ai_settings, ai_startup, ai_runtime, ai_files
        from video_parser.web.analysis_routes import router

        config = ai_startup.normalize({
            'server_path': str(temporary / 'runtime/server.exe'),
            'model_path': str(temporary / "weights/模型 ' one.gguf"),
            'vision_path': str(temporary / 'weights/vision.gguf'), 'port': 18988,
        })
        for field in ('server_path', 'model_path', 'vision_path'):
            file = Path(config[field]); file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'fixture')
        model_state = {'active': False, 'ready': False, 'spawns': 0}
        child = SimpleNamespace(poll=lambda: None if model_state['active'] else 9, returncode=9)
        def spawn(*_args, **_kwargs):
            if model_state.pop('fail_next', False):
                raise OSError('fixture-private-detail')
            model_state.update(active=True, ready=False); model_state['spawns'] += 1
            return child
        with patch.object(ai_files, 'pick', side_effect=lambda field: config[field]), patch.object(ai_runtime, 'LOG_ROOT', temporary / 'logs'), patch.object(ai_runtime, '_log_path', None), patch.object(ai_runtime, '_process', None), patch.object(ai_runtime, '_identity', None), patch.object(ai_runtime, '_started', 0), patch.object(ai_runtime, 'Popen', side_effect=spawn), patch.object(ai_startup, 'occupied', side_effect=lambda _port: model_state['active']), patch.object(ai_startup, 'same_running_model', side_effect=lambda *_args, **_kwargs: model_state['ready']), patch.object(ai_settings, 'SETTINGS_PATH', temporary / '.local/ai/settings.json'), patch.dict(os.environ, {
            'QWEN_API_KEY': '', 'QWEN_API_BASE_URL': '', 'QWEN_MODEL_ID': '',
        }), patch.object(ai_startup.subprocess, 'run') as launch:
            ai_settings.save('llamacpp', ai_startup.endpoint(config), 'fixture-vl', startup=config)
            application = FastAPI()
            application.include_router(router)
            application.mount('/assets', StaticFiles(directory=str(DIST / 'assets')), name='assets')

            @application.get('/')
            def index():
                return FileResponse(DIST / 'index.html')

            @application.get('/api/workspace/config')
            def configuration():
                value = ai_settings.public()
                return {'platforms': ['哔哩哔哩'], 'ai_configured': False, 'ai': {**value, 'configured': False},
                        'media_ready': True, 'subtitles_ready': True, 'transcription_ready': True,
                        'transcription_upload_limit': 1000000, 'archive_root': str(temporary / 'library')}

            @application.get('/api/workspace/tasks')
            def tasks(): return {'jobs': []}

            @application.get('/api/workspace/transcriptions/sources')
            def sources(): return {'sources': []}

            @application.get('/api/workspace/projects')
            def projects(): return {'projects': []}

            @application.get('/api/workspace/folders')
            def folders(): return {'folders': []}

            sock = socket.socket(); sock.bind(('127.0.0.1', 0))
            server = uvicorn.Server(uvicorn.Config(application, host='127.0.0.1', port=sock.getsockname()[1], log_level='error'))
            thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and thread.is_alive() and time.monotonic() < deadline: time.sleep(.02)
                assert server.started
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1280, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    fixture_project = {'id': 'f' * 32, 'title': '设置入口测试素材', 'platform': '哔哩哔哩', 'part': 1,
                        'location': 'mock/settings-shortcut', 'identity_status': 'verified', 'archive_url': '/mock/archive', 'resources': []}
                    fixture_video = {'id': 'e' * 32, 'title': fixture_project['title'], 'platform': '哔哩哔哩',
                        'source_url': 'https://www.bilibili.com/video/FIXTURE', 'cover_url': None, 'cover_download_url': None,
                        'warning': None, 'project': fixture_project, 'media': None,
                        'qualities': [{'id': '1080', 'label': '1080P', 'height': 1080, 'width': 1920, 'media': None}],
                        'default_quality_id': '1080', 'analysis': ''}
                    page.route('**/api/workspace/embedding/settings', lambda route: route.fulfill(json={'base_url':'','model':'','key_saved':False,'configured':False}))
                    page.route('**/api/workspace/ai/agents', lambda route: route.fulfill(json={'permission':'restricted-learning','engines':[]}))
                    page.route('**/api/workspace/parse', lambda route: route.fulfill(json=fixture_video))
                    page.route('**/api/workspace/projects/*/resume', lambda route: route.fulfill(json=fixture_video))
                    page.route('**/api/workspace/projects/*/analyses', lambda route: route.fulfill(json={'records': []}))
                    page.route('**/api/workspace/projects/*/analysis/context*', lambda route: route.fulfill(json={
                        'transcripts': [], 'duration': 120, 'auto_frame_count': 8, 'image_tokens': 800, 'prompt_tokens': 900,
                        'output_tokens': 1500, 'templates': [], 'sources': {'both': '字幕 + 画面', 'transcript': '只用字幕', 'frames': '只用画面'},
                        'ai': {**ai_settings.public(), 'configured': False}}))
                    page.goto(f'http://127.0.0.1:{sock.getsockname()[1]}', wait_until='networkidle')
                    settings = page.get_by_role('button', name='设置', exact=True)
                    page.get_by_role('textbox', name='视频链接或分享文本', exact=True).fill(fixture_video['source_url'])
                    page.get_by_role('button', name='解析视频', exact=True).click()
                    expect(page.locator('.info-title')).to_have_text(fixture_video['title'])
                    page.get_by_role('tab', name='AI 分析', exact=True).click()
                    page.get_by_role('button', name='打开设置', exact=True).click()
                    expect(page.get_by_label('服务', exact=True)).to_be_focused()
                    settings_page = page.get_by_test_id('page-settings')
                    expect(settings_page).to_be_visible()
                    expect(page.locator('.app-topbar').get_by_role('button', name='设置', exact=True)).to_have_count(0)
                    expect(page.get_by_role('dialog', name='设置', exact=True)).to_have_count(0)
                    page.get_by_role('button', name='AI 模型', exact=True).click()
                    model = page.get_by_label('模型文件路径', exact=True)
                    expect(model).to_have_value(config['model_path'])
                    before_pick = ai_settings.SETTINGS_PATH.read_bytes()
                    page.get_by_role('button', name='选择模型文件', exact=True).click()
                    expect(page.locator('.local-ai-startup')).to_contain_text('文件已选入')
                    expect(model).to_have_value(config['model_path'])
                    page.get_by_role('button', name='选择视觉文件', exact=True).click()
                    expect(page.locator('.local-ai-startup')).to_contain_text('文件已选入')
                    assert before_pick == ai_settings.SETTINGS_PATH.read_bytes()
                    switch = page.get_by_role('switch', name='启动时显示命令行窗口', exact=True)
                    expect(switch).to_be_checked()
                    switch.uncheck()

                    expect(page.get_by_label('服务端口', exact=True)).to_have_value('18988')
                    page.get_by_label('服务端口', exact=True).fill('18989')
                    expect(page.get_by_label('接口地址', exact=True)).to_have_value('http://127.0.0.1:18989/v1')
                    page.get_by_role('button', name='保存', exact=True).click()
                    expect(page.locator('.settings-ai > [role="status"]')).to_contain_text('不会自动重启')
                    stored = json.loads(ai_settings.SETTINGS_PATH.read_text(encoding='utf-8'))
                    assert stored['startup']['port'] == 18989
                    assert stored['api_key'] not in page.content()
                    page.locator('.app-sidebar').get_by_role('button', name='视频工作台', exact=True).click()
                    expect(settings_page).to_be_hidden()
                    settings.click()
                    expect(page.get_by_label('服务端口', exact=True)).to_have_value('18989')

                    # Inspect an unsaved draft; neither the saved config nor a process changes.
                    before = ai_settings.SETTINGS_PATH.read_bytes()
                    model.fill(str(temporary / 'missing.gguf'))
                    page.get_by_role('button', name='检查启动配置（不启动）', exact=True).click()
                    expect(page.locator('.local-ai-checks')).to_contain_text('未找到文件')
                    assert ai_settings.SETTINGS_PATH.read_bytes() == before
                    model.fill(config['model_path'])
                    page.get_by_role('button', name='检查启动配置（不启动）', exact=True).click()
                    expect(page.locator('.local-ai-startup > [role="status"]')).to_contain_text('检查通过')
                    assert ai_settings.SETTINGS_PATH.read_bytes() == before
                    page.get_by_text('手动启动命令（备用）', exact=True).click()
                    expect(page.get_by_label('启动命令（自动生成，PowerShell）')).to_have_attribute('readonly', '')

                    page.get_by_text('高级启动参数（通常不用改）', exact=True).click()
                    expect(page.get_by_label('运行程序路径', exact=True)).to_have_value(config['server_path'])
                    page.get_by_label('上下文长度', exact=True).fill('512')
                    expect(page.get_by_role('alert')).to_contain_text('单次回复上限不能大于上下文长度')
                    expect(page.get_by_role('button', name='保存', exact=True)).to_be_disabled()
                    page.get_by_label('上下文长度', exact=True).fill('8192')
                    page.get_by_label('单次回复上限', exact=True).fill('2048')
                    page.get_by_label('显卡使用层数', exact=True).fill('0')
                    page.get_by_label('CPU 线程数', exact=True).fill('8')
                    page.get_by_label('同时处理数', exact=True).fill('2')
                    page.get_by_label('启用 Flash Attention 显卡加速').uncheck()
                    page.get_by_role('button', name='保存', exact=True).click()
                    expect(page.locator('.settings-ai > [role="status"]')).to_contain_text('不会自动重启')
                    stored = json.loads(ai_settings.SETTINGS_PATH.read_text(encoding='utf-8'))
                    assert stored['startup']['threads'] == 8 and not stored['startup']['flash_attention']
                    page.get_by_role('button', name='恢复推荐性能参数', exact=True).click()
                    expect(page.get_by_label('上下文长度', exact=True)).to_have_value('32768')
                    expect(page.get_by_label('显卡使用层数', exact=True)).to_have_value('99')
                    expect(page.get_by_label('CPU 线程数', exact=True)).to_have_value('0')
                    expect(model).to_have_value(config['model_path'])
                    expect(page.get_by_label('服务端口', exact=True)).to_have_value('18989')
                    expect(page.get_by_label('模型 ID', exact=True)).to_have_value('fixture-vl')
                    expect(switch).not_to_be_checked()
                    page.get_by_label('视觉文件路径（看图时需要）').fill('')
                    page.get_by_role('button', name='检查启动配置（不启动）', exact=True).click()
                    expect(page.locator('.local-ai-startup')).to_contain_text('不能分析视频画面')
                    page.get_by_label('视觉文件路径（看图时需要）').fill(config['vision_path'])
                    page.get_by_role('button', name='保存', exact=True).click()
                    expect(page.locator('.settings-ai > [role="status"]')).to_contain_text('不会自动重启')

                    # Reload is backed by the real temporary JSON file, not browser storage.
                    page.reload(wait_until='networkidle')
                    settings.click()
                    page.get_by_role('button', name='配置 API 连接', exact=True).click()
                    expect(page.get_by_label('服务端口', exact=True)).to_have_value('18989')
                    expect(switch).not_to_be_checked()
                    page.get_by_text('高级启动参数（通常不用改）', exact=True).click()
                    expect(page.get_by_label('上下文长度', exact=True)).to_have_value('32768')
                    page.get_by_label('模型 ID', exact=True).fill('fixture-vl-start-button')
                    page.locator('.app-sidebar').get_by_role('button', name='视频工作台', exact=True).click()
                    settings.click()
                    expect(page.get_by_label('模型 ID', exact=True)).to_have_value('fixture-vl-start-button')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert settings_page.evaluate('(element) => element.scrollWidth <= element.clientWidth')
                    # The model can be started while disconnected, without a connection test.
                    expect(page.locator('.ai-runtime-state')).to_contain_text('未启动')
                    page.get_by_role('button', name='保存并启动模型', exact=True).click()
                    expect(page.locator('.ai-runtime-state')).to_contain_text('加载中')
                    assert json.loads(ai_settings.SETTINGS_PATH.read_text(encoding='utf-8'))['model'] == 'fixture-vl-start-button'
                    expect(page.get_by_role('button', name='正在加载模型…', exact=True)).to_be_disabled()
                    assert model_state['spawns'] == 1
                    page.get_by_role('button', name='常用设置', exact=True).click()
                    assert model_state['active'], 'Leaving settings must not stop loading'
                    model_state['ready'] = True
                    page.get_by_role('button', name='AI 模型', exact=True).click()
                    expect(page.locator('.ai-runtime-state')).to_contain_text('已就绪')
                    # Ready: the badge is the only statement; no disabled start button or repeated sentence.
                    expect(page.locator('.ai-runtime-card .settings-actions .primary')).to_have_count(0)
                    model_state.update(active=False, ready=False)
                    expect(page.locator('.ai-runtime-state')).to_contain_text('启动失败', timeout=8000)
                    model_state['fail_next'] = True
                    page.get_by_role('button', name='启动本地模型', exact=True).click()
                    expect(page.locator('.settings-ai > [role="alert"]')).to_contain_text('无法启动本机模型')
                    assert model_state['spawns'] == 1
                    page.get_by_role('button', name='启动本地模型', exact=True).click()
                    expect(page.locator('.ai-runtime-state')).to_contain_text('加载中')
                    assert model_state['spawns'] == 2
                    # Mobile navigation uses the same bottom sidebar entry, not a dialog.
                    page.get_by_role('button', name='打开导航菜单', exact=True).click()
                    page.locator('.sidebar-settings').get_by_role('button', name='设置', exact=True).click()
                    expect(page.get_by_role('heading', name='设置', exact=True)).to_be_focused()

                    page.get_by_label('服务', exact=True).select_option('modelscope')
                    expect(page.locator('.local-ai-startup')).to_have_count(0)
                    expect(page.get_by_label('API Key', exact=True)).to_be_visible()
                    expect(page.get_by_role('dialog', name='设置', exact=True)).to_have_count(0)
                    assert not errors, errors
                    launch.assert_not_called()
                    browser.close()
                print(json.dumps({'checks': [
                    'local startup form loads real saved paths and recommended defaults',
                    'port updates API address, real save/reopen/reload persists configuration without exposing the token',
                    'read-only draft checks report missing files without saving or starting any process',
                    'advanced limits, save state and recommended reset preserve file paths, port and model ID',
                    'native picker API binding without implicit save, persisted console switch and reset isolation',
                    'text-only warning, cloud-mode isolation, page navigation and 390px layout',
                    'bottom sidebar settings entry, analysis shortcut focus, page sections, reload deep-link and no settings dialog',
                    'disconnected start, loading/ready/failure states, navigation while loading and retry without duplicate launch',
                ]}, ensure_ascii=False, indent=2))
            finally:
                server.should_exit = True; thread.join(timeout=10); sock.close()


if __name__ == '__main__':
    main()
