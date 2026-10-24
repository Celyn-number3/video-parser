"""Read-only live verification. Browser mutations and external requests are intercepted."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--base', default='http://127.0.0.1:15001')
    args = parser.parse_args()
    assert len(args.project) == 32 and all(c in '0123456789abcdef' for c in args.project)
    base = args.base.rstrip('/')
    assert urlsplit(base).hostname in ('localhost', '127.0.0.1')
    def get(path):
        with urlopen(base + path, timeout=20) as response: return json.load(response)
    assert get('/health')['status'] == 'healthy'
    with urlopen(base + '/', timeout=10) as response:
        assert response.read() == (ROOT / 'frontend/dist/index.html').read_bytes()
    archived = get(f'/api/workspace/projects/{args.project}/subtitles')
    assert archived['translations'] and any(row['language'] == 'zh' for row in archived['translations'])
    cues = get(f'/api/workspace/projects/{args.project}/subtitle-cues')
    selected = next(row for row in cues['sources'] if row['resource'] == cues['resource'])
    assert selected['kind'] == 'translation' and selected['language'] == 'zh' and cues['cues']
    print('LIVE_ARCHIVE_TRANSLATIONS', len(archived['translations']))
    print('LIVE_LEARNING_DEFAULT', selected['label'], 'CUES', len(cues['cues']))
    print('LIVE_DIST_MATCH', True)
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / 'runtimes/browsers'))
    artifacts = ROOT / '.local/work/artifacts/subtitle-results'; artifacts.mkdir(parents=True, exist_ok=True)
    blocked = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        def readonly(route):
            request = route.request
            if urlsplit(request.url).netloc != urlsplit(base).netloc:
                return route.abort()
            inventory_read = request.method == 'POST' and urlsplit(request.url).path == '/api/workspace/subtitles/inventory'
            if request.method not in ('GET', 'HEAD') and not inventory_read:
                blocked.append(urlsplit(request.url).path)
                print('BLOCKED_WRITE', urlsplit(request.url).path)
                return route.fulfill(status=409, json={'detail': '只读验收：此写入请求已拦截。'})
            route.continue_()
        context.route('**/*', readonly)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack))
        page.goto(base + f'/?project={args.project}&page=learning')
        page.get_by_role('tab', name='字幕', exact=True).click()
        panel = page.get_by_role('region', name='滚动字幕', exact=True)
        expect(panel.get_by_role('combobox', name='字幕版本')).to_have_value(cues['resource'])
        expect(panel).to_contain_text(cues['cues'][0]['text'])
        page.evaluate('document.documentElement.setAttribute("data-theme", "dark")')
        page.screenshot(path=str(artifacts / 'live-p8-learning.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='视频工作台', exact=True).click()
        page.get_by_role('tab', name='字幕与转写', exact=True).click()
        page.get_by_role('button', name=__import__('re').compile('^已归档视频')).click()
        target = next(row for row in get('/api/workspace/transcriptions/sources')['sources'] if row['project_id'] == args.project)
        page.locator('.source-option').filter(has_text=target['title']).first.get_by_role('radio').check()
        expect(page.get_by_label('译文', exact=True)).not_to_have_value('')
        page.screenshot(path=str(artifacts / 'live-p8-translation.png'), full_page=True, animations='disabled')
        assert not errors, errors
        print('LIVE_BROWSER_CHINESE_RESULT', True, 'INTERCEPTED_MUTATIONS', len(blocked))
        context.close(); browser.close()


if __name__ == '__main__': main()
