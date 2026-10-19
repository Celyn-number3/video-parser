"""Explicit check of the user's already-authorized public course P1, reusing its cache."""
import json
import os
from pathlib import Path
import time
import requests
from playwright.sync_api import sync_playwright,expect
from video_parser.core.paths import ROOT
from video_parser.services import subtitles
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'runtimes/browsers'))
BASE='http://127.0.0.1:15001'


def main():
    with sync_playwright() as manager:
        browser=manager.chromium.launch(headless=True);page=browser.new_page(accept_downloads=True);downloads=[]
        page.on('download',lambda item:downloads.append(item.suggested_filename))
        page.goto(BASE);page.locator('#source').fill('https://www.bilibili.com/video/BV1rH4y1N7BW?p=1')
        panel=page.locator('.subtitle-panel');panel.get_by_label('下载范围').select_option('current');panel.get_by_role('button',name='下载字幕',exact=True).click()
        deadline=time.monotonic()+45;identifier=None
        while time.monotonic()<deadline:
            identifier=page.evaluate("localStorage.getItem('video-parser:task:subtitles')")
            if identifier:break
            page.wait_for_timeout(100)
        assert identifier,'No subtitle task (check local login status; do not disclose Cookies)'
        result=None
        while time.monotonic()<deadline:
            result=requests.get(BASE+'/api/workspace/subtitles/'+identifier,timeout=5).json()
            if result['state'] not in ('queued','running','cancelling'):break
            page.wait_for_timeout(150)
        assert result['state']=='completed',result
        assert result['downloaded']==0 and result['existing']==1,result
        assert result['progress']=={'done':1,'total':1},result
        files=[file for row in result['results'] for file in row['files']]
        assert len(files)==3 and all('/projects/' in file['url'] for file in files)
        for file in files:
            response=requests.get(BASE+file['url'],timeout=10);assert response.status_code==200 and response.content
        page.reload();expect(page.locator('.subtitle-panel .subtitle-status')).to_contain_text('已有可用 1 集',timeout=15000)
        assert page.get_by_role('button',name='另存字幕副本到下载文件夹').count()==0
        expect(page.locator('.subtitle-panel').get_by_role('button',name='打开项目文件夹')).to_be_visible()
        assert not downloads;assert not (subtitles.CACHE_ROOT/identifier).exists(),'Successful task snapshot should be removed'
        browser.close()
    report={'course':'BV1rH4y1N7BW','episode':1,'state':result['state'],'existing':result['existing'],'downloaded':result['downloaded'],
        'validated_library_files':len(files),'automatic_browser_downloads':len(downloads),'refresh_reconnected':True,
        'successful_scratch_removed':True,'job_id':identifier,'scope':'Existing P1 cache only; no full-course download or fresh QR authentication.'}
    (ROOT/'.local/work/artifacts/optimization-live-subtitle.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
