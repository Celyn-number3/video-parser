"""Opt-in live verification for the user's public Douyin video; not part of unit discovery.
Uses an isolated test browser against the local workspace. No browser Cookie export or AI calls.
"""
import json
from pathlib import Path
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from video_parser.services import videos as cli
from video_parser.services import library as library
BASE='http://127.0.0.1:15003'
ID='7617880126232085627'
ADDRESS='https://www.douyin.com/user/self?from_tab_name=main&modal_id='+ID+'&showSubTab=video&showTab=favorite_collection'
SHARE='7.43 Bgb:/ :5pm 04/01 D@U.lC VibeCoding开发前9个步骤和开发中5个关键点 # 人工智能 # vibecoding # 大模型 # AI工具 # 姜学长 https://v.douyin.com/FjyP0wPvpis/ 复制此链接，打开Dou音搜索，直接观看视频！'


def main():
    output=ROOT/'.local/work/artifacts/douyin-diagnostics';output.mkdir(parents=True,exist_ok=True)
    report={'video_id':ID,'browser_cookies_exported':False,'paid_services_used':False,'checks':[]}
    started=time.monotonic()
    with sync_playwright() as p:
        instance=p.chromium.launch(headless=True)
        page=instance.new_page(viewport={'width':1440,'height':1100},accept_downloads=True)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(BASE);page.wait_for_load_state('networkidle')
        page.get_by_role('textbox',name='添加视频链接').fill(ADDRESS)
        with page.expect_response(lambda response:response.url==BASE+'/api/workspace/parse' and response.request.method=='POST',timeout=90000) as event:
            page.get_by_role('button',name='解析视频',exact=True).click()
        parsed_response=event.value
        assert parsed_response.status==200,parsed_response.text()
        parsed=parsed_response.json()
        assert parsed['source_url']=='https://www.douyin.com/video/'+ID
        assert 'VibeCoding开发前9个步骤' in parsed['title']
        expect(page.locator('.info-title p')).to_have_text(parsed['title'])
        assert parsed['cover_url']
        image=page.locator('.cover-stage img')
        expect(image).to_be_visible()
        page.wait_for_function("document.querySelector('.cover-stage img')?.naturalWidth > 0")
        project_id=parsed['project']['id']
        report.update(title=parsed['title'],project_id=project_id,project_location=parsed['project']['location'])
        report['checks'].append('address-bar modal URL -> real browser extraction -> exact video metadata and cover')
        quality=parsed['default_quality_id']
        if parsed.get('media'):
            prepared = parsed['media']
            report['download_performed_this_run'] = False
            expect(page.locator('.details-panel').get_by_role('status')).to_have_text('已复用归档视频', timeout=15000)
        else:
            with page.expect_response(lambda response:'/prepare' in response.url and response.request.method=='POST',timeout=240000) as prepared_event:
                page.get_by_role('button',name='下载并归档',exact=True).click()
            prepared_response=prepared_event.value
            assert prepared_response.status==200,prepared_response.text()
            prepared=prepared_response.json()
            report['download_performed_this_run'] = True
            expect(page.locator('.details-panel').get_by_role('status')).to_have_text('所选视频已归档',timeout=15000)
        project=library.get(project_id)
        file=library.resource(project_id,prepared['resource'])
        info=cli.probe(file);cli.check_video(info,require_audio=True,expected_duration=538.611)
        stream=next(item for item in info['streams'] if item['codec_type']=='video')
        assert (stream['width'],stream['height'])==(1080,1920)
        report.update(width=stream['width'],height=stream['height'],duration=float(info['format']['duration']),
                      size_bytes=file.stat().st_size,media_path=str(file),sha256=library.digest(file),
                      stream_types=sorted({item['codec_type'] for item in info['streams']}))
        report['checks'].append(('full real download -> atomic project archive' if report['download_performed_this_run'] else 'existing real archive reused') + ' -> ffprobe video+audio/duration/resolution verification')
        page.get_by_role('tab',name='视频预览').click()
        page.wait_for_function("document.querySelector('video')?.readyState >= 2",timeout=30000)
        page.locator('video').evaluate('async v=>{v.muted=true;await v.play()}')
        page.wait_for_function("document.querySelector('video').currentTime > .3",timeout=15000)
        page.locator('video').evaluate('v=>v.pause()')
        page.screenshot(path=str(output/'success-desktop.png'),full_page=True)
        report['checks'].append('workspace HTML5 playback advances; no source-site browser/profile is needed')
        with page.expect_download(timeout=15000) as download:
            page.get_by_role('button',name='导出视频',exact=True).click()
        with tempfile.TemporaryDirectory(prefix='douyin-export-check-') as directory:
            exported=Path(directory)/'export.mp4';download.value.save_as(exported)
            assert library.digest(exported)==library.digest(file)
        report['checks'].append('browser video export is byte-identical to the verified archive')
        share_response=page.request.post(BASE+'/api/workspace/parse',data={'text':SHARE},timeout=90000)
        assert share_response.status==200,share_response.text()
        shared=share_response.json()
        assert shared['project']['id']==project_id
        assert shared['source_url']==parsed['source_url']
        assert shared['media'] and shared['media']['resource']==prepared['resource']
        shared_media=page.request.post(BASE+f"/api/workspace/videos/{shared['id']}/prepare",data={'quality_id':shared['default_quality_id']},timeout=30000)
        assert shared_media.status==200,shared_media.text()
        assert shared_media.json()['resource']==prepared['resource']
        assert library.digest(file)==report['sha256']
        report['checks'].append('full copied share text -> same video/project/media -> reuse without a duplicate file')
        assert not errors,errors
        report['console_errors']=errors
        report['elapsed_seconds']=round(time.monotonic()-started,1)
        instance.close()
    (output/'live-success-2026-10-11.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
