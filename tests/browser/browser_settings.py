"""Focused browser checks for settings accessibility, persistence, and mobile fit."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

from playwright.sync_api import sync_playwright, expect
import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def check_quality_selection():
    with tempfile.TemporaryDirectory(prefix='settings-ts-') as output:
        subprocess.run(['node', str(ROOT / 'frontend/node_modules/typescript/bin/tsc'),
            'src/settings.ts', '--ignoreConfig', '--target', 'es2022', '--module', 'esnext', '--outDir', output,
            '--skipLibCheck'], cwd=ROOT / 'frontend', check=True)
        module = Path(output) / 'settings.js'
        script = r"""import fs from 'node:fs'; import assert from 'node:assert/strict';
const source = fs.readFileSync(process.argv[1], 'utf8');
const { preferredQualityId } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const q = (id, height) => ({ id, label: id, height, width: null, codec: null, media: null });
assert.equal(preferredQualityId([q('720',720)], '720', '1080p'), '720');
assert.equal(preferredQualityId([q('1080',1080)], '1080', '720p'), '1080');
assert.equal(preferredQualityId([q('unknown',null)], 'unknown', '720p'), 'unknown');
assert.equal(preferredQualityId([], 'missing', 'best'), '');
assert.equal(preferredQualityId([q('first',720),q('second',720)], 'second', '720p'), 'first');"""
        subprocess.run(['node', '--input-type=module', '-e', script, str(module)], cwd=ROOT, check=True)


def main():
    check_quality_selection()
    with tempfile.TemporaryDirectory(prefix='workspace-settings-') as directory:
        os.environ['VIDEO_LIBRARY_ROOT'] = str(Path(directory) / 'library')
        from video_parser.web import app as api
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api.app, host='127.0.0.1', port=port, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started, 'FastAPI failed to start'
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                page.add_init_script("localStorage.setItem('video-parser:last-project','keep-project'); localStorage.setItem('video-parser:last-quality','keep-quality'); if (!sessionStorage.getItem('settings-corrupt-tested')) { localStorage.setItem('video-parser:settings','{bad json'); sessionStorage.setItem('settings-corrupt-tested','1'); }")
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{port}')
                button = page.get_by_role('button', name='设置', exact=True)
                button.click()
                dialog = page.get_by_role('dialog', name='设置', exact=True)
                expect(dialog).to_be_visible()
                expect(page.get_by_label('默认画质', exact=True)).to_have_value('best')
                page.get_by_label('默认画质', exact=True).select_option('720p')
                page.get_by_label('归档完成提醒', exact=True).check()
                page.keyboard.press('Escape')
                expect(dialog).not_to_be_visible()
                expect(button).to_be_focused()
                page.reload()
                button = page.get_by_role('button', name='设置', exact=True)
                button.click()
                expect(page.get_by_label('默认画质', exact=True)).to_have_value('720p')
                expect(page.get_by_label('归档完成提醒', exact=True)).to_be_checked()
                page.get_by_role('button', name='恢复默认', exact=True).click()
                expect(page.get_by_label('默认画质', exact=True)).to_have_value('best')
                expect(page.get_by_label('归档完成提醒', exact=True)).not_to_be_checked()
                assert page.evaluate("localStorage.getItem('video-parser:last-project')") == 'keep-project'
                assert page.evaluate("localStorage.getItem('video-parser:last-quality')") == 'keep-quality'
                expect(page.locator('.archive-root')).to_contain_text(str(Path(directory) / 'library'))
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Settings overflow at 390px'
                assert not errors, errors
                blocked = browser.new_page()
                blocked.add_init_script("const original=Storage.prototype.setItem; Storage.prototype.setItem=function(key,...args){if(key==='video-parser:settings') throw new DOMException('blocked','QuotaExceededError'); return original.call(this,key,...args)}")
                blocked.goto(f'http://127.0.0.1:{port}')
                blocked.get_by_role('button', name='设置', exact=True).click()
                blocked.get_by_label('默认画质', exact=True).select_option('1080p')
                expect(blocked.locator('.settings-save-status')).to_contain_text('当前页已生效，关闭或刷新后可能丢失')
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
    print('Settings browser checks passed: malformed preference fallback, save/reload/reset isolation, dialog keyboard focus, archive path, and 390px layout.')


if __name__ == '__main__':
    main()
