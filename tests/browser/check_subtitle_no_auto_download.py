"""Browser regression against a running local workbench; all subtitle operations are mocked."""
from playwright.sync_api import sync_playwright, expect
from urllib.parse import urlsplit
import json
import os
from pathlib import Path
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(Path(__file__).resolve().parents[2] / 'runtimes/browsers'))

BASE='http://127.0.0.1:15001'
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for mode in ['completed', 'polled', 'partial', 'failed']:
        page=browser.new_page(accept_downloads=True)
        # Capture export intent without downloading fixture URLs from the live backend.
        page.add_init_script('''window.__downloadLinks=[];const original=HTMLAnchorElement.prototype.click;
            HTMLAnchorElement.prototype.click=function(){if(this.hasAttribute('download')){
            window.__downloadLinks.push(this.getAttribute('href'));return;}return original.call(this);};''')
        files=[];downloads=[];opened=[]
        page.on('download',lambda download: downloads.append(download.suggested_filename))
        def result(state):
            rows=[] if state=='running' else [{'episode':1,'status':'failed' if state=='failed' else 'downloaded','message':'fixture',
                'files':[] if state=='failed' else [{'url':f'/api/workspace/subtitles/fixture/files/{fmt}','format':fmt} for fmt in ['json','srt','md']],
                'project':None if state=='failed' else {'id':'fixture-project','location':'bilibili/fixture'}}]
            return {'id':'fixture','state':state,'title':'fixture','message':'测试完成' if state!='running' else '测试处理中','results':rows}
        def handle(route):
            path=urlsplit(route.request.url).path
            if path=='/api/workspace/bili-login/status':route.fulfill(json={'authenticated':True})
            elif path=='/api/workspace/subtitles':route.fulfill(status=202,json=result('running' if mode=='polled' else mode))
            elif path=='/api/workspace/subtitles/fixture':route.fulfill(json=result('completed'))
            elif '/subtitles/fixture/files/' in path:
                files.append(path);fmt=path.rsplit('/',1)[-1]
                route.fulfill(body='fixture',headers={'Content-Type':'application/octet-stream','Content-Disposition':f'attachment; filename="fixture.{fmt}"'})
            elif path=='/api/workspace/projects/fixture-project/open':
                opened.append(True);route.fulfill(json={'message':'模拟打开项目文件夹'})
            else:route.continue_()
        page.context.route('**/api/workspace/**',handle)
        page.goto(BASE,wait_until='networkidle')
        page.locator('#source').fill('https://www.bilibili.com/video/BV1TaqYBcEJc')
        page.locator('.subtitle-panel button.primary').click()
        expect(page.locator('.subtitle-panel .subtitle-status')).to_have_text('测试完成')
        # Ensure the former delayed browser-download scheduler does not run after completion.
        page.wait_for_timeout(1500)
        assert not files and not downloads,(mode,files,downloads)
        assert page.evaluate('window.__downloadLinks')==[]
        if mode!='failed':
            expect(page.get_by_text('字幕已保存到项目文件夹，无需再次下载。可点击“打开项目文件夹”查看。')).to_be_visible()
            page.get_by_role('button',name='打开项目文件夹',exact=True).click()
            expect(page.get_by_text('模拟打开项目文件夹')).to_be_visible();assert opened
        expect(page.get_by_role('button',name='另存字幕副本到下载文件夹')).to_have_count(0)
        print(mode,'PASS: no automatic downloads; explicit controls verified')
        page.context.unroute_all(behavior='wait');page.close()
    browser.close()
