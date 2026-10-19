"""Prototype-only Chromium regression. No production/backend testing."""
from pathlib import Path
import json, os
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parent
URL=os.environ.get('PROTOTYPE_URL','http://127.0.0.1:8080/')
expect.set_options(timeout=10000)
checks=[]; errors=[]; requests=[]; downloads=[]
def check(name,condition=True):
    assert condition,name
    checks.append(name)
    print('PASS',name,flush=True)
with sync_playwright() as pw:
    browser=pw.chromium.launch()
    context=browser.new_context(viewport={'width':1440,'height':1000})
    context.add_init_script("""window.__businessCalls=[];window.__fileReads=[];
    window.fetch=(...args)=>{window.__businessCalls.push('fetch');return Promise.reject(new Error('No network in prototype'))};
    XMLHttpRequest.prototype.open=function(){window.__businessCalls.push('xhr');throw new Error('No network')};
    for(const name of ['text','arrayBuffer','stream']){File.prototype[name]=function(){window.__fileReads.push(name);throw new Error('No file reads')}};
    for(const name of ['readAsText','readAsArrayBuffer','readAsDataURL']){FileReader.prototype[name]=function(){window.__fileReads.push(name);throw new Error('No file reads')}};
    """)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append({'url':r.url,'type':r.resource_type}));page.on('download',lambda d:downloads.append(d.suggested_filename))
    page.set_default_timeout(10000)
    page.goto(URL)
    expect(page.locator('#project-title')).to_have_text('沿着海岸，向山海之间');check('Default parsed sample A')
    check('Default buttons require no API',page.locator('#archive-button').is_enabled())
    check('Analysis gated by archive and consent',page.locator('#analysis-start').is_disabled())
    for width in [1440,768,390]:
        page.set_viewport_size({'width':width,'height':1000})
        page.locator('#tab-video').click();check(f'Full archive tools only in video {width}px',page.locator('#inspector-data-grid').is_visible() and page.locator('#video-quality').is_visible() and page.locator('#open-project').is_visible())
        for tab in ['cover','subtitles','analysis']:
            page.locator('#tab-'+tab).click()
            check(f'Compact context hides technical metadata {tab} {width}px',not page.locator('#inspector-data-grid').is_visible())
            check(f'No quality or folder tools in {tab} {width}px',not page.locator('#video-quality').is_visible() and not page.locator('#open-project').is_visible())
            check(f'Project identity retained {tab} {width}px',page.locator('#inspector-title').inner_text()=='沿着海岸，向山海之间')
            if tab!='analysis':
                check(f'No video archive action in {tab} {width}px',not page.locator('#archive-button').is_visible())
            else:
                check(f'AI exposes compact archive prerequisite {width}px',page.locator('#archive-button').is_visible() and page.locator('#archive-button').inner_text()=='先归档视频')
            if width<=1000:
                check(f'Narrow compact context precedes content {tab} {width}px',page.locator('#inspector-card').bounding_box()['y']<page.locator('.workspace-main').bounding_box()['y'])
            else:
                check(f'Desktop context stays on right {tab}',page.locator('#inspector-card').bounding_box()['x']>page.locator('.workspace-main').bounding_box()['x'])
        check(f'Subtitle context specifies episode and independence {width}px', 'P1 / 1' in page.locator('#inspector-context-note').evaluate("e=>{document.querySelector('#tab-subtitles').click();return e.textContent}"))
        check(f'Compact context does not overflow {width}px',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.set_viewport_size({'width':1440,'height':1000});page.locator('#tab-analysis').click();page.locator('#archive-button').click()
    check('AI prerequisite starts same owning project archive',page.evaluate("jobs[0].kind==='video'&&jobs[0].projectId==='coast'"))
    page.locator('#archive-actions [data-cancel]').click();expect(page.locator('#global-count')).to_have_text('0');page.locator('#tab-video').click()
    page.locator('#tab-video').focus();page.keyboard.press('ArrowRight');check('Tab arrow keyboard navigation',page.locator('#tab-cover').get_attribute('aria-selected')=='true')
    page.keyboard.press('End');check('Tab End keyboard navigation',page.locator('#tab-analysis').get_attribute('aria-selected')=='true');page.keyboard.press('Home');check('Tab Home keyboard navigation',page.locator('#tab-video').get_attribute('aria-selected')=='true')
    page.locator('#preview-play').click();page.wait_for_timeout(1150);check('Static playback controls advance',page.evaluate('state.time')>=1);page.locator('#small-play').click();check('Pause control works',not page.evaluate('state.playing'))
    page.locator('#volume-button').click();check('Mute control works',page.evaluate('state.muted'))
    page.locator('#expand-button').click();check('Enlarge sample modal',page.locator('#image-dialog').get_attribute('open') is not None);page.keyboard.press('Escape');check('Modal Escape restores focus',page.evaluate("document.activeElement.id")=='expand-button')
    page.locator('#tab-cover').click();page.locator('#save-cover').click();check('Cover copy preview',page.locator('#export-title').inner_text()=='另存封面');page.locator('#export-confirm').click();check('Export explicitly simulated',page.locator('#toast-copy').inner_text().find('没有下载')>=0)
    page.locator('#tab-video').click();page.locator('#clear-source').click();check('Empty workspace rendered',page.locator('#video-empty').is_visible());check('Empty parse disabled',page.locator('#parse-button').is_disabled());check('Empty archive disabled',page.locator('#archive-button').is_disabled())
    page.locator('#source-url').fill('not a link');page.locator('#parse-button').click();check('URL validation', '请输入' in page.locator('#archive-status').inner_text())
    page.locator('#source-url').fill('https://demo.invalid/fail');page.locator('#parse-button').click();check('Parsing busy state',page.locator('#parse-button').is_disabled());expect(page.locator('#archive-status')).to_contain_text('示例解析失败');check('Parse failure exposed')
    page.locator('#sample-a').click();page.locator('#parse-button').click();expect(page.locator('#archive-button')).to_be_enabled();check('Parse retry success')
    page.locator('#archive-button').click();expect(page.locator('#global-count')).to_have_text('1');check('Mock task badge counts active job')
    page.locator('#sample-b').click();page.locator('#parse-button').click();expect(page.locator('#project-title')).to_have_text('云端之下 · 山行手记');check('Switch to B while A runs')
    page.locator('#tab-analysis').click();page.locator('#analysis-prompt').fill('保留这个要求');page.locator('[data-page="tasks"]').click();check('Navigation keeps job alive',page.evaluate('jobs[0].state')=='running')
    page.locator('#cache-open').click();check('Cache blocked during active tasks',page.locator('#cache-confirm').is_disabled());page.keyboard.press('Escape')
    page.locator('.task-detail').first.locator('summary').click();page.wait_for_timeout(600);check('Details remain open during progress',page.locator('.task-detail').first.get_attribute('open') is not None)
    page.locator('[data-page="workspace"]').click();check('Draft prompt retained',page.locator('#analysis-prompt').input_value()=='保留这个要求')
    expect(page.locator('#global-count')).to_have_text('0',timeout=10000);check('A background completion keeps B selected',page.locator('#project-title').inner_text()=='云端之下 · 山行手记');check('A result not applied to B',page.locator('#archive-tag').inner_text()=='尚未归档')
    page.locator('[data-page="tasks"]').click();page.locator('[data-view-task]').first.click();check('Explicit task result restores A',page.locator('#project-title').inner_text()=='沿着海岸，向山海之间');check('Archive result belongs to A',page.locator('#archive-tag').inner_text()=='已归档')
    page.locator('#video-quality').select_option('720');check('Quality does not change project identity',page.evaluate('state.current')=='coast');check('Independent quality archive status',page.locator('#archive-tag').inner_text()=='尚未归档')
    page.locator('#archive-button').click();page.locator('#archive-actions [data-cancel]').click();check('Cancelling intermediary state',page.evaluate("jobs[0].state")=='cancelling');expect(page.locator('#global-count')).to_have_text('0');check('Cancelled task remains listed',page.evaluate("jobs[0].state")=='cancelled')
    page.locator('[data-page="tasks"]').click();page.locator('[data-retry]').first.click();check('Retry creates new run',page.evaluate("jobs[0].state")=='running');page.locator('#task-rows [data-cancel]').first.click();expect(page.locator('#global-count')).to_have_text('0')
    page.locator('[data-filter="completed"]').click();check('Completed filter',page.locator('.task-row').count()==3);page.locator('[data-filter="active"]').click();check('Empty active filter',page.locator('.task-empty').is_visible());page.locator('[data-filter="all"]').click()
    page.locator('#cache-open').click();check('Cache confirmation enabled when idle',page.locator('#cache-confirm').is_enabled());page.locator('#cache-confirm').click();check('Cache simulation explicit', '没有删除' in page.locator('#toast-copy').inner_text())
    page.locator('#top-settings').click();page.locator('#default-quality').select_option('720');page.locator('#completion-reminder').check();check('Settings immediate session save',page.evaluate('state.settings.quality')=='720');page.keyboard.press('Escape');page.locator('#top-settings').click();page.mouse.click(5,5);check('Backdrop closes modal',page.locator('#settings-dialog').get_attribute('open') is None)
    page.locator('[data-page="workspace"]').click();page.locator('#sample-b').click();page.locator('#parse-button').click();expect(page.locator('#project-title')).to_have_text('云端之下 · 山行手记');check('Preference affects next parse',page.locator('#video-quality').input_value()=='720')
    page.locator('#tab-subtitles').click();page.locator('#subtitle-scope').select_option('custom');page.locator('#subtitle-episodes').fill('5-1');page.locator('#sub-start').click();check('Reversed episodes rejected','不能小于' in page.locator('#sub-status').inner_text());page.locator('#subtitle-episodes').fill('9');page.locator('#sub-start').click();check('Out of range episodes rejected','超出范围' in page.locator('#sub-status').inner_text())
    page.locator('#subtitle-episodes').fill('1-3,8');page.locator('#sub-start').click();check('Subtitle login gate',page.locator('#login-dialog').get_attribute('open') is not None);expect(page.locator('#qr-status')).to_contain_text('手机App');check('Unscannable demo QR clearly identified','无法真实扫码' in page.locator('.qr-note').inner_text())
    heights=[]
    for mode in ['waiting','scanned','expired','error','loading']:
        page.locator('#qr-scenario').select_option(mode);heights.append(page.locator('#qr-box').bounding_box()['height'])
    check('QR states retain panel height',max(heights)-min(heights)<1);check('Loading QR disables confirmation',page.locator('#qr-confirm').is_disabled())
    page.locator('#qr-scenario').select_option('expired');check('Expired QR disables confirmation',page.locator('#qr-confirm').is_disabled());page.locator('#qr-refresh').click();expect(page.locator('#qr-confirm')).to_be_enabled();check('QR refresh recovers');page.locator('#qr-confirm').click();check('Fake login continues captured subtitle job',page.evaluate("jobs[0].kind")=='subtitles');expect(page.locator('#global-count')).to_have_text('0');check('Requested episode indices preserved',page.locator('.episode-number').all_text_contents()==['P1','P2','P3','P8'])
    page.locator('#video-scenario').select_option('archived');page.locator('#tab-analysis').click();check('Archived AI hides archive operation',not page.locator('#archive-button').is_visible());check('Archived AI shows ready context','已归档' in page.locator('#inspector-context-note').inner_text());check('Consent still gates AI after archive',page.locator('#analysis-start').is_disabled());page.locator('#analysis-consent').check();page.locator('#analysis-start').click();expect(page.locator('#analysis-result')).to_be_visible();check('AI mock result generated without API')
    page.locator('[data-page="transcription"]').click();check('Transcription starts empty',page.locator('#transcription-start').is_disabled());page.locator('#file-input').set_input_files({'name':'bad.exe','mimeType':'application/octet-stream','buffer':b'x'});check('Unsupported file filtered',page.locator('.file-item').count()==0)
    page.locator('#use-demo-files').click();check('Demo file selection',page.locator('.file-item').count()==2);check('Batch model reuse default',page.locator('#reuse-model').is_checked());page.locator('#transcription-language').select_option('en');page.locator('[data-page="tasks"]').click();page.locator('[data-page="transcription"]').click();check('Selections retained across navigation',page.locator('.file-item').count()==2 and page.locator('#transcription-language').input_value()=='en')
    page.locator('#transcription-start').click();check('Independent batch jobs queued',page.evaluate("jobs.filter(j=>j.kind==='transcription'&&['running','queued'].includes(j.state)).length")==2);page.locator('[data-page="tasks"]').click();first=page.locator('#task-rows [data-cancel]').first;first.click();expect(page.locator('#global-count')).to_have_text('1');check('One cancellation leaves other task running');expect(page.locator('#global-count')).to_have_text('0',timeout=12000)
    completed=page.locator('.task-row').filter(has=page.locator('.task-status.completed')).first;completed.locator('[data-view-task]').click();expect(page.locator('#transcript-result')).to_be_visible();check('Transcription result recoverable from task center');page.locator('#export-srt').click();check('SRT export preview', '00:00:00,000 -->' in page.locator('#export-content').inner_text());page.keyboard.press('Escape')
    page.locator('#transcription-scenario').select_option('failed');check('Transcription failure UI','失败' in page.locator('#transcription-status').inner_text());page.locator('#transcription-scenario').select_option('cancelled');check('Transcription cancelled UI','取消' in page.locator('#transcription-status').inner_text());page.locator('#transcription-scenario').select_option('completed');check('Transcription completed UI',page.locator('#transcript-result').is_visible())
    for width in [1920,1440,1024,768,390,320]:
        page.set_viewport_size({'width':width,'height':900})
        for dest in ['workspace','transcription','tasks']:
            if width<=760:page.locator('#menu-button').click()
            page.locator(f'[data-page="{dest}"]').click()
            check(f'No horizontal overflow {width}px {dest}',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            if width<=760:check(f'Mobile menu closes after {dest} {width}px',page.locator('#menu-button').get_attribute('aria-expanded')=='false')
    page.set_viewport_size({'width':390,'height':844});page.locator('#menu-button').click();page.keyboard.press('Escape');check('Mobile menu Escape restores focus',page.evaluate('document.activeElement.id')=='menu-button');page.locator('#menu-button').click();page.locator('#side-settings').click();check('Narrow modal fits viewport',page.locator('#settings-dialog').bounding_box()['width']<=390);page.keyboard.press('Escape')
    page.locator('#menu-button').click();page.locator('[data-page="workspace"]').click();page.screenshot(path=str(ROOT/'mobile.png'))
    business_calls=page.evaluate('window.__businessCalls.length');file_reads=page.evaluate('window.__fileReads.length');page.set_viewport_size({'width':1440,'height':1000});page.reload();page.wait_for_timeout(300);page.screenshot(path=str(ROOT/'desktop.png'));check('Reload resets ephemeral tasks',page.locator('#global-count').inner_text()=='0')
    check('Zero attempted business API calls',business_calls+page.evaluate('window.__businessCalls.length')==0);check('Zero file content reads',file_reads+page.evaluate('window.__fileReads.length')==0);check('Zero business network requests',all(r['type']=='document' for r in requests));check('Zero real downloads',not downloads);check('Zero login cookies',context.cookies()==[]);check('Runtime has zero JS errors',not errors)
    page.goto((ROOT/'index.html').as_uri());check('Portable HTML works over file URL',page.locator('#project-title').inner_text()=='沿着海岸，向山海之间');check('Offline image embedded',page.locator('.sample-image').first.evaluate('(e)=>e.complete&&e.naturalWidth>0'))
    check('CSP denies network connections',"connect-src 'none'" in page.locator('meta[http-equiv="Content-Security-Policy"]').get_attribute('content'))
    browser.close()
report={'date':'2026-10-13','scope':'独立原型 / Chromium; 不代表正式业务验收','passed':len(checks),'checks':checks,'runtime_errors':errors,'network_requests':requests,'downloads':downloads}
(ROOT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(f'{len(checks)} checks passed.')
