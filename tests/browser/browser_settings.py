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
            'src/features/settings/settings.ts', '--ignoreConfig', '--target', 'es2022', '--module', 'esnext', '--outDir', output,
            '--skipLibCheck'], cwd=ROOT / 'frontend', check=True)
        module = Path(output) / 'features/settings/settings.js'
        script = r"""import fs from 'node:fs'; import assert from 'node:assert/strict';
const source = fs.readFileSync(process.argv[1], 'utf8');
const { preferredQualityId, normalizeSettings } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const q = (id, height) => ({ id, label: id, height, width: null, codec: null, media: null });
for (const preference of ['best','1080p','720p','480p','360p']) {
  assert.equal(normalizeSettings({qualityPreference: preference}).qualityPreference, preference);
}
for (const invalid of ['240p','480P',480,null,{},[]]) {
  assert.equal(normalizeSettings({qualityPreference: invalid}).qualityPreference, 'best');
}
const all = [q('1080',1080),q('720',720),q('480',480),q('360',360)];
assert.equal(preferredQualityId(all, '1080', '480p'), '480');
assert.equal(preferredQualityId(all, '1080', '360p'), '360');
assert.equal(preferredQualityId([q('720',720),q('360',360)], '720', '480p'), '360');
assert.equal(preferredQualityId([q('720',720),q('480',480)], '720', '360p'), '480');
assert.equal(preferredQualityId([q('unknown',null)], 'unknown', '360p'), 'unknown');
assert.equal(preferredQualityId([], null, '480p'), '');
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
                settings_page = page.get_by_test_id('page-settings')
                expect(settings_page).to_be_visible()
                expect(page.get_by_role('dialog', name='设置', exact=True)).to_have_count(0)
                expect(page.locator('.sidebar-settings button')).to_have_attribute('aria-current', 'page')
                expect(page.get_by_label('默认画质', exact=True)).to_have_value('best')
                page.get_by_label('默认画质', exact=True).select_option('720p')
                page.get_by_label('归档完成提醒', exact=True).check()
                page.locator('.app-sidebar').get_by_role('button', name='视频工作台', exact=True).click()
                expect(settings_page).to_be_hidden()
                expect(page.locator('.app-sidebar').get_by_role('button', name='视频工作台', exact=True)).to_be_focused()
                page.reload()
                button = page.get_by_role('button', name='设置', exact=True)
                button.click()
                expect(page.get_by_label('默认画质', exact=True)).to_have_value('720p')
                expect(page.get_by_label('归档完成提醒', exact=True)).to_be_checked()
                page.get_by_role('button', name='恢复常用默认', exact=True).click()
                expect(page.get_by_label('默认画质', exact=True)).to_have_value('best')
                expect(page.get_by_label('归档完成提醒', exact=True)).not_to_be_checked()
                assert page.evaluate("localStorage.getItem('video-parser:last-project')") == 'keep-project'
                assert page.evaluate("localStorage.getItem('video-parser:last-quality')") == 'keep-quality'
                page.get_by_role('button', name='存储与维护', exact=True).click()
                expect(page.locator('.archive-root')).to_contain_text(str(Path(directory) / 'library'))
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Settings overflow at 390px'
                page.set_viewport_size({'width': 1280, 'height': 900})
                page.get_by_role('button', name='常用设置', exact=True).click()
                page.locator('.language-switch label', has_text='English').click()
                expect(page.get_by_role('radio', name='English', exact=True)).to_be_checked()
                expect(page.locator('html')).to_have_attribute('lang', 'en')
                expect(page.get_by_role('heading', name='Interface language', exact=True)).to_be_visible()
                expect(page.get_by_label('Default quality', exact=True)).to_have_value('best')
                expect(page.locator('.app-sidebar').get_by_role('button', name='Video workbench', exact=True)).to_be_visible()
                assert page.evaluate("localStorage.getItem('vp-language')") == 'en'
                page.reload()
                page.get_by_role('button', name='Settings', exact=True).click()
                expect(page.get_by_role('radio', name='English', exact=True)).to_be_checked()
                expect(page.get_by_role('button', name='Restore general defaults', exact=True)).to_be_visible()
                assert page.title() == 'Video Parser · Video workbench', page.title()
                leftover = page.evaluate(r"""() => [...document.querySelectorAll('.app-sidebar *, .settings-page *')]
                    .filter(node => node.offsetParent && !node.closest('[translate="no"]')
                        && [...node.childNodes].some(child => child.nodeType === 3 && /[\u3400-\u9fff]/.test(child.data)))
                    .map(node => node.textContent.trim())""")
                assert leftover == [], leftover
                page.locator('.language-switch label', has_text='中文').click()
                expect(page.locator('html')).to_have_attribute('lang', 'zh-CN')
                expect(page.get_by_label('默认画质', exact=True)).to_have_value('best')
                assert page.evaluate("localStorage.getItem('vp-language')") == 'zh'
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
    print('Settings browser checks passed: malformed preference fallback, save/reload/reset isolation, sidebar/page keyboard focus and grouped maintenance, archive path, 390px layout, and the English/Chinese interface switch.')


if __name__ == '__main__':
    main()
