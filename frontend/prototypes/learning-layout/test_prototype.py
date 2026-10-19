"""Prototype-only Chromium regression: 视频工作台「AI 分析」里的视频和笔记并排、分集列表与「已学完」。

不测试正式前端或后端。
"""
from datetime import date
from pathlib import Path
import json
import os
import re

ROOT = Path(__file__).resolve().parent
REPO = next(path for path in ROOT.parents if (path / 'pyproject.toml').is_file())
if (REPO / 'runtimes' / 'browsers').is_dir():
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(REPO / 'runtimes' / 'browsers'))

from playwright.sync_api import expect, sync_playwright  # noqa: E402

URL = os.environ.get('PROTOTYPE_URL', 'http://127.0.0.1:8080/')
# Screenshots are local verification artifacts: inside the repo they go to the git-ignored outputs/ folder.
DEFAULT_SHOTS = REPO / 'outputs' / 'learning-layout-prototype' if (REPO / 'outputs').is_dir() else ROOT / 'screenshots'
SHOTS = Path(os.environ.get('SCREENSHOT_DIR', str(DEFAULT_SHOTS)))
WIDTHS = [1440, 1360, 1280, 1024, 860, 768, 390, 320]
expect.set_options(timeout=10000)
checks, errors, requests, downloads = [], [], [], []


def check(name, condition=True):
    assert condition, name
    checks.append(name)
    print('PASS', name, flush=True)


def no_overflow(page):
    return page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


def box(page, selector):
    return page.locator(selector).first.bounding_box()


def visible_in_viewport(page, selector):
    b = box(page, selector)
    return b is not None and b['y'] >= 0 and b['y'] < page.viewport_size['height'] and b['height'] > 0


def side_by_side(page, left, right):
    a, b = box(page, left), box(page, right)
    return a['x'] + a['width'] <= b['x'] and a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height']


def active_id(page):
    return page.evaluate('document.activeElement ? document.activeElement.id : ""')


def clear_toasts(page):
    page.evaluate("document.querySelectorAll('#toast-region .toast').forEach(t => t.remove())")


def nav(page, dest):
    if page.viewport_size['width'] <= 760:
        page.locator('#menu-button').click()
        expect(page.locator('#sidebar')).to_have_class(re.compile(r'\bopen\b'))
    page.locator(f'#nav [data-page="{dest}"]').click()
    if page.viewport_size['width'] <= 760:
        page.wait_for_timeout(260)  # let the 0.2s drawer transition finish


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    context.add_init_script("""window.__businessCalls = [];
      window.fetch = (...args) => { window.__businessCalls.push('fetch'); return Promise.reject(new Error('No network in prototype')); };
      XMLHttpRequest.prototype.open = function () { window.__businessCalls.push('xhr'); throw new Error('No network'); };""")
    page = context.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.on('request', lambda r: requests.append({'url': r.url, 'type': r.resource_type}))
    page.on('download', lambda d: downloads.append(d.suggested_filename))
    page.goto(URL)

    # 导航不变：没有新增页面
    order = page.locator('#nav [data-page]').evaluate_all('els => els.map(e => e.dataset.page)')
    check('Navigation keeps the four existing pages only', order == ['workspace', 'transcription', 'tasks', 'accounts'])
    check('Navigation labels unchanged', page.locator('#nav .nav-label').all_inner_texts() == ['视频工作台', '字幕与转写', '任务中心', '账号与登录'])
    check('No learning or approval page exists', page.locator('text=整理审批').count() == 0 and page.locator('#nav >> text=学习').count() == 0)
    check('Workspace is the current page', page.locator('#nav [data-page="workspace"]').get_attribute('aria-current') == 'page')
    check('Workspace tabs unchanged', page.locator('[role="tab"]').all_inner_texts() == ['封面图片', '视频预览', 'AI 分析'])
    check('AI 分析 tab selected for the demo', page.locator('#tab-ai').get_attribute('aria-selected') == 'true')
    expect(page.locator('#episode-title')).to_have_text('P3 · 乘法和逆矩阵')
    check('Default episode is P3', True)

    # 核心：视频和笔记并排
    check('Wide screen: video and notes side by side', side_by_side(page, '#player', '#record'))
    check('Wide screen: inspector stays on the right', box(page, '#inspector')['x'] > box(page, '#record')['x'])
    check('Both video and notes are visible at once', visible_in_viewport(page, '#player') and visible_in_viewport(page, '#record-text'))
    page.locator('#record-text [data-seek="792"]').click()
    expect(page.locator('#player-time')).to_have_text('13:12 / 46:48')
    check('Timestamp seeks the video in place', page.locator('#tab-ai').get_attribute('aria-selected') == 'true')
    check('Notes stay visible after seeking', page.locator('#record-text').is_visible() and visible_in_viewport(page, '#record-text [data-seek="792"]'))
    page.locator('.followup [data-seek="940"]').scroll_into_view_if_needed()
    page.evaluate('window.scrollBy(0, 300)')
    page.locator('.followup [data-seek="940"]').click()
    expect(page.locator('#player-time')).to_have_text('15:40 / 46:48')
    check('Video stays on screen while reading far down the notes', visible_in_viewport(page, '#player'))
    check('Slider reports the new position', page.locator('#player-track').get_attribute('aria-valuenow') == '940')
    page.locator('#player-track').focus()
    page.keyboard.press('ArrowRight')
    expect(page.locator('#player-time')).to_have_text('15:45 / 46:48')
    check('Keyboard seeks on the progress slider', True)
    page.locator('#play-button').click()
    check('Play toggles to pause', page.locator('#play-button').get_attribute('aria-label') == '暂停')
    page.wait_for_timeout(1300)
    page.locator('#play-button').click()
    check('Demo playback advances time', page.evaluate('window.__prototype.state.time') >= 946)
    page.evaluate('window.scrollTo(0, 0)')

    # 分集列表与已学完
    check('Episode list shows all 35 parts', page.locator('#episode-list .episode').count() == 35)
    expect(page.locator('#learned-count')).to_have_text('已学完 2 / 35')
    expect(page.locator('#episodes-next')).to_have_text('学到 P3 乘法和逆矩阵')
    check('Continue is hidden while already on the next lecture', page.locator('#continue-button').is_hidden())
    check('Current episode marked in the list', page.locator('[data-open="3"]').get_attribute('aria-current') == 'true')
    check('Wide screen shows the list without a toggle', page.locator('#episode-list').is_visible() and page.locator('#episodes-toggle').is_hidden())
    check('Not-yet-archived episodes are labelled', page.locator('[data-open="7"] .ep-meta').inner_text() == '未归档')
    page.locator('#learned-current').check()
    expect(page.locator('#learned-count')).to_have_text('已学完 3 / 35')
    check('Marking under the video updates the list', page.locator('#learned-3').is_checked())
    expect(page.locator('#episodes-next')).to_have_text('学到 P4 A 的 LU 分解')
    expect(page.locator('#continue-button')).to_have_text('继续学 P4')
    check('Marking keeps focus on the checkbox', active_id(page) == 'learned-current')
    check('Progress bar follows the count', abs(page.locator('#learned-bar').evaluate('e => parseFloat(e.style.width)') - 300 / 35) < 0.05)
    page.locator('#continue-button').click()
    expect(page.locator('#episode-title')).to_have_text('P4 · A 的 LU 分解')
    check('Continue opens the next lecture and focuses its title', active_id(page) == 'episode-title')
    check('Switching lecture restarts the demo video', page.locator('#player-time').inner_text() == '00:00 / 48:05')
    check('Continue hides once on the next lecture', page.locator('#continue-button').is_hidden())
    check('Lecture without records opens the analysis form', page.locator('#new-analysis').get_attribute('open') is not None and page.locator('#records-title').count() == 0)
    page.locator('#learned-5').check()
    page.locator('#learned-6').check()
    expect(page.locator('#learned-count')).to_have_text('已学完 5 / 35')
    check('Earlier lectures can be marked straight from the list', active_id(page) == 'learned-6')
    expect(page.locator('#episodes-next')).to_have_text('学到 P4 A 的 LU 分解')
    page.locator('#learned-6').uncheck()
    expect(page.locator('#learned-count')).to_have_text('已学完 4 / 35')
    check('Unmarking works', not page.locator('#learned-6').is_checked())

    # 新建分析后，笔记出现在视频旁边
    page.locator('[data-template="notes"]').click()
    check('Template choice is pressed', page.locator('[data-template="notes"]').get_attribute('aria-pressed') == 'true')
    expect(page.locator('#tpl-desc')).to_have_text('知识点、公式、易错点和自测题，适合课程')
    page.locator('#analyze-button').click()
    expect(page.locator('#analyze-button')).to_contain_text('分析中')
    expect(page.locator('#record-select')).to_contain_text('学习笔记')
    check('Generated notes collapse the form', page.locator('#new-analysis').get_attribute('open') is None)
    check('Focus moves to the new record', active_id(page) == 'records-title')
    check('New notes sit beside the video', side_by_side(page, '#player', '#record'))
    page.locator('#record-text .time-link').first.click()
    check('Generated timestamps seek too', page.locator('#player-time').inner_text().startswith('05:46'))
    clear_toasts(page)

    # 未归档的一讲：沿用现有「先归档视频」
    page.locator('[data-open="7"]').click()
    expect(page.locator('#episode-title')).to_have_text('P7 · 求解 Ax=0：主变量、特解')
    check('Unarchived lecture shows the existing empty stage', page.locator('#player').count() == 0 and page.locator('text=选择画质并下载归档后预览').is_visible())
    expect(page.locator('#analyze-button')).to_contain_text('归档并分析')
    page.locator('#archive-button').click()
    expect(page.locator('#archive-button')).to_contain_text('下载归档中')
    expect(page.locator('#player')).to_be_visible()
    check('Archived lecture gets its video and keeps focus nearby', active_id(page) == 'play-button')
    check('List shows the archived duration', page.locator('[data-open="7"] .ep-meta').inner_text() == '43:22')
    clear_toasts(page)
    page.locator('[data-open="8"]').click()
    page.locator('[data-template="chapters"]').click()
    page.locator('#analyze-button').click()
    expect(page.locator('#record-select')).to_contain_text('章节时间轴')
    check('归档并分析 archives then analyses', page.locator('#player').is_visible() and page.locator('[data-open="8"] .ep-meta').inner_text() == '47:51')
    clear_toasts(page)

    # 记录切换与追问
    page.locator('[data-open="3"]').click()
    check('P3 keeps two analysis records', page.locator('#record-select option').count() == 2)
    page.locator('#record-select').focus()
    page.locator('#record-select').select_option('r3-chapters')
    expect(page.locator('#record-text')).to_contain_text('Gauss-Jordan 求逆')
    check('Record switch keeps focus on the select', active_id(page) == 'record-select')
    page.locator('#ask-input').fill('再讲讲分块乘法')
    page.locator('#ask-form button[type="submit"]').click()
    expect(page.locator('.followup')).to_contain_text('再讲讲分块乘法')
    check('Follow-up count shows in the record list', '追问 1' in page.locator('#record-select option:checked').inner_text())

    # 标签：视频预览共用同一个播放位置；完整检查器同样有分集
    page.locator('#record-text [data-seek="1050"]').click()
    page.locator('#tab-ai').focus()
    page.keyboard.press('ArrowLeft')
    check('Arrow keys switch tabs', page.locator('#tab-video').get_attribute('aria-selected') == 'true' and active_id(page) == 'tab-video')
    check('Video tab shares the playback position', page.locator('#player-time').inner_text() == '17:30 / 46:48')
    check('Full inspector heading unchanged', page.locator('#details-heading').inner_text() == '项目与归档')
    check('Full inspector also lists episodes', page.locator('#episode-list').is_visible() and page.locator('.media-meta').is_visible())
    page.keyboard.press('Home')
    check('Home opens the cover tab', page.locator('#tab-cover').get_attribute('aria-selected') == 'true' and page.locator('.cover-art').is_visible())
    page.keyboard.press('End')
    check('End returns to AI 分析', page.locator('#tab-ai').get_attribute('aria-selected') == 'true')

    # 其他：主题、设置、解析、导航
    page.locator('#theme-button').click()
    check('Dark theme toggles', page.evaluate('document.documentElement.dataset.theme') == 'dark')
    page.locator('#theme-button').click()
    page.locator('#settings-button').click()
    check('Settings dialog opens', page.locator('#settings-dialog').is_visible())
    page.keyboard.press('Escape')
    check('Escape closes settings and restores focus', page.locator('#settings-dialog').is_hidden() and active_id(page) == 'settings-button')
    page.locator('#parse-button').click()
    expect(page.locator('#toast-region')).to_contain_text('原型不联网解析')
    clear_toasts(page)
    page.locator('#nav [data-page="tasks"]').click()
    check('Other pages stay as placeholders', page.locator('#page-title').inner_text() == '任务中心' and page.locator('#page-tasks').is_visible())
    page.locator('#page-tasks [data-go="workspace"]').click()
    check('Returning keeps the current lecture', page.locator('#episode-title').inner_text() == 'P3 · 乘法和逆矩阵')

    # 响应式
    page.set_viewport_size({'width': 1280, 'height': 800})
    check('Below 1360px the compact inspector moves above', box(page, '#inspector')['y'] < box(page, '#player')['y'])
    check('1280px keeps video and notes side by side', side_by_side(page, '#player', '#record'))
    check('Episode list collapses behind a toggle', page.locator('#episode-list').is_hidden() and page.locator('#episodes-toggle').is_visible())
    check('Progress stays visible while collapsed', page.locator('#learned-count').is_visible() and page.locator('#episodes-next').is_visible())
    page.locator('#episodes-toggle').click()
    check('Toggle expands the list', page.locator('#episode-list').is_visible() and page.locator('#episodes-toggle').get_attribute('aria-expanded') == 'true')
    page.locator('[data-open="2"]').click()
    expect(page.locator('#episode-title')).to_have_text('P2 · 矩阵消元')
    check('Picking from the expanded list collapses it and focuses the lecture', page.locator('#episode-list').is_hidden() and active_id(page) == 'episode-title')
    page.locator('#episodes-toggle').click()
    page.locator('[data-open="3"]').click()
    expect(page.locator('#episode-title')).to_have_text('P3 · 乘法和逆矩阵')
    page.set_viewport_size({'width': 1024, 'height': 768})
    check('1024px still side by side', side_by_side(page, '#player', '#record'))
    page.set_viewport_size({'width': 768, 'height': 900})
    check('Narrow screens stack notes under the video', box(page, '#record')['y'] > box(page, '#player')['y'])
    page.evaluate('window.scrollTo(0, 1200)')
    page.wait_for_timeout(100)
    check('Stacked video sticks under the top bar', visible_in_viewport(page, '#player') and box(page, '#player')['y'] <= 80)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.evaluate('window.scrollTo(0, 0)')
    check('Phone: drawer navigation', page.locator('#menu-button').is_visible() and page.evaluate("document.getElementById('sidebar').inert === true"))
    page.locator('#menu-button').click()
    page.keyboard.press('Escape')
    check('Escape closes the drawer and restores focus', active_id(page) == 'menu-button' and page.locator('#menu-button').get_attribute('aria-expanded') == 'false')
    page.locator('#menu-button').click()
    page.locator('#nav-scrim').click(position={'x': 370, 'y': 400})
    check('Scrim closes the drawer', page.locator('#menu-button').get_attribute('aria-expanded') == 'false')
    page.evaluate('window.scrollTo(0, 1500)')
    page.wait_for_timeout(100)
    check('Phone: video stays on screen while scrolling notes', visible_in_viewport(page, '#player'))
    page.locator('#record-text .time-link').nth(1).click()
    check('Phone: timestamp seeks without leaving the notes', page.locator('#player-time').inner_text().startswith('05:36'))
    page.set_viewport_size({'width': 800, 'height': 500})
    check('Very short screens drop the sticky video', page.locator('#study-media').evaluate('e => getComputedStyle(e).position') == 'static')
    for width in WIDTHS:
        page.set_viewport_size({'width': width, 'height': 900})
        for tab in ['ai', 'video']:
            page.evaluate(f"document.getElementById('tab-{tab}').click()")
            check(f'No horizontal overflow at {width}px ({tab})', no_overflow(page))
    page.evaluate("document.getElementById('tab-ai').click()")

    # 截图、刷新重置与零业务调用边界
    SHOTS.mkdir(parents=True, exist_ok=True)
    business_calls = page.evaluate('window.__businessCalls.length')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.reload()
    page.wait_for_timeout(200)
    check('Reload resets in-memory demo data', page.locator('#learned-count').inner_text() == '已学完 2 / 35' and page.locator('#episode-title').inner_text() == 'P3 · 乘法和逆矩阵')
    page.locator('#record-text [data-seek="792"]').click()
    page.screenshot(path=str(SHOTS / 'ai-1440.png'))
    page.set_viewport_size({'width': 1280, 'height': 800})
    page.locator('#episodes-toggle').click()
    page.screenshot(path=str(SHOTS / 'ai-1280-list.png'))
    page.locator('#episodes-toggle').click()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.evaluate('window.scrollTo(0, 900)')
    page.wait_for_timeout(100)
    page.screenshot(path=str(SHOTS / 'ai-390-scrolled.png'))
    business_calls += page.evaluate('window.__businessCalls.length')
    check('Zero attempted business API calls', business_calls == 0)
    check('Only the prototype document was requested', all(r['type'] == 'document' for r in requests))
    check('Zero downloads', not downloads)
    check('Zero cookies', context.cookies() == [])
    check('Runtime has zero JS or console errors', not errors)
    page.goto((ROOT / 'index.html').as_uri())
    check('Portable HTML works over a file URL', page.locator('#episode-title').inner_text() == 'P3 · 乘法和逆矩阵')
    check('CSP denies network connections', "connect-src 'none'" in page.locator('meta[http-equiv="Content-Security-Policy"]').get_attribute('content'))
    browser.close()

report = {
    'date': date.today().isoformat(),
    'scope': '独立原型 / Chromium；不代表正式业务验收',
    'url': URL,
    'passed': len(checks),
    'checks': checks,
    'runtime_errors': errors,
    'network_requests': requests,
    'downloads': downloads,
}
(ROOT / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(f'{len(checks)} checks passed.')
