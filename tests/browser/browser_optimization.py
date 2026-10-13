"""Built React + HTTP + disposable workers + ffmpeg, with synthetic/local providers only."""
import importlib
import json
import os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from threading import Thread,Event
import time
from unittest.mock import patch
import requests
import uvicorn
from playwright.sync_api import sync_playwright,expect
from video_parser.core.paths import ROOT
from video_parser.services import videos,library,subtitles,transcription,workflows,bili_auth,task_runtime
from video_parser.web import routes
from video_parser.web.app import app


def terminal(base,identifier):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        result=requests.get(base+'/api/workspace/tasks/'+identifier,timeout=5).json()
        if result['state'] not in task_runtime.ACTIVE:return result
        time.sleep(.1)
    raise AssertionError('Task did not settle')


def main():
    output=ROOT/'outputs/optimization-browser';output.mkdir(parents=True,exist_ok=True)
    records=[];owned=[]
    with tempfile.TemporaryDirectory(prefix='optimization-browser-') as temporary:
        root=Path(temporary);video=root/'fixture.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=320x180:rate=10',
            '-f','lavfi','-i','sine=frequency=440','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True,timeout=20)
        hold=Event();model_hold=Event();model_release=Event();state={'calls':0,'fail':True,'hold_model':False,'subtitle_args':[]}
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                data=video.read_bytes()
                if self.path=='/hold':
                    hold.set();self.send_response(200);self.send_header('Content-Length',str(len(data)*10000));self.end_headers()
                    try:
                        for _ in range(10000):self.wfile.write(data);self.wfile.flush();time.sleep(.1)
                    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
                else:
                    time.sleep(2);self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));state['calls']+=1
                assert any(item['type']=='image_url' for item in data['messages'][0]['content'])
                if state['hold_model']:model_hold.set();model_release.wait(15)
                if state['fail']:self.send_error(503);return
                result={'id':'fixture','object':'chat.completion','created':0,'model':'fixture',
                    'choices':[{'index':0,'message':{'role':'assistant','content':'合成画面验收完成。'},'finish_reason':'stop'}]}
                try:
                    encoded=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers()
                    self.wfile.write(encoded)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        provider=ThreadingHTTPServer(('127.0.0.1',0),Fixture);Thread(target=provider.serve_forever,daemon=True).start()
        upstream=f'http://127.0.0.1:{provider.server_port}'
        def parse(text,**kwargs):
            number=text.split('/')[-1]
            return videos.select_quality(videos.ParsedVideo({'title':'优化测试 '+number,'platform':'抖音','video_id':number,'source_url':text,
                'cover_url':None,'video_url':upstream+('/hold' if number=='1002' else '/video.mp4')}, {},[upstream+('/hold' if number=='1002' else '/video.mp4')],[]),'best')
        title='结构化字幕验收';raw=root/'raw'/subtitles.sanitize_title(title)
        tool=importlib.import_module('video_parser.integrations.bilibili.b站')
        def episode(number):tool.save_subtitle_files({'body':[{'from':0,'to':1,'content':'验收字幕'}]},f'P{number:02d}_fixture',raw)
        episode(1)
        def run_cli(url,episodes):
            state['subtitle_args'].append(episodes)
            return 0,{'events':[{'event':'target','title':title,'bvid':'BV1rH4y1N7BW','total':2,'single':False},
                *[{'event':'episode','episode':i,'status':'existing'} for i in (episodes or [1,2])]]}
        with patch.object(videos,'parse_link',side_effect=parse),patch.object(library,'LIBRARY_ROOT',root/'library'),\
             patch.object(workflows,'RECORD_ROOT',root/'workflow-records'),patch.object(subtitles,'CACHE_ROOT',root/'subtitle-cache'),\
             patch.object(subtitles,'download_root',return_value=root/'raw'),patch.object(subtitles,'run_cli',side_effect=run_cli),\
             patch.object(transcription,'OUTPUT_ROOT',root/'transcriptions'),patch.object(bili_auth,'status',return_value={'authenticated':True}),\
             patch.dict(os.environ,{'QWEN_API_KEY':'synthetic-fixture-key','QWEN_API_BASE_URL':upstream+'/v1','NO_PROXY':'127.0.0.1,localhost'}):
            sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(app,log_level='warning'));thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
            deadline=time.monotonic()+15
            while not server.started and time.monotonic()<deadline:time.sleep(.02)
            assert server.started;base=f'http://127.0.0.1:{port}'
            try:
                with sync_playwright() as manager:
                    browser=manager.chromium.launch(headless=True);page=browser.new_page(accept_downloads=True)
                    errors=[];downloads=[];page.on('pageerror',lambda error:errors.append(str(error)));page.on('download',lambda item:downloads.append(item))
                    page.goto(base);source=page.get_by_role('textbox',name='添加视频链接')
                    source.fill('https://www.douyin.com/video/1001');page.get_by_role('button',name='解析视频',exact=True).click()
                    expect(page.locator('.info-title')).to_contain_text('优化测试 1001',timeout=15000)
                    page.locator('.download-button').click()
                    deadline=time.monotonic()+10
                    while not workflows.jobs and time.monotonic()<deadline:time.sleep(.05)
                    first=next(iter(workflows.jobs));owned.append(first)
                    page.reload();expect(page.locator('.task-center')).to_contain_text('优化测试 1001',timeout=15000)
                    done=terminal(base,first);assert done['state']=='completed',done
                    project_id=done['project_id'];saved=library.resource(project_id,done['result']['resource']);assert saved.is_file()
                    page.goto(base+'?project='+project_id)
                    expect(page.locator('.media-meta')).to_be_visible(timeout=15000)
                    records.append('real isolated video worker, ffmpeg validation/archive, page-refresh task reconnection')
                    page.get_by_role('tab',name='AI 分析').click();page.get_by_label('同意将抽样画面发送给模型服务，并了解可能产生费用').check();page.get_by_label('抽样帧数').select_option('2')
                    page.get_by_role('button',name='开始分析').click()
                    expect(page.locator('.details-panel .status')).to_contain_text('失败',timeout=20000)
                    assert state['calls']==1,'Model SDK retried a paid operation'
                    state['fail']=False;page.get_by_role('button',name='开始分析').click()
                    expect(page.get_by_label('分析结果')).to_have_value('合成画面验收完成。',timeout=20000)
                    assert state['calls']==2;records.append('AI consent, no retry after local 503, explicit retry and archived analysis')
                    entry_id=next(key for key,value in routes.entries.items() if value.project_id==project_id)
                    before_reports=len([x for x in library.get(project_id)['resources'].values() if x['kind']=='analysis'])
                    state['hold_model']=True
                    submitted=requests.post(base+f'/api/workspace/videos/{entry_id}/analyze-task',json={'consent':True,'count':2},timeout=5).json();owned.append(submitted['id'])
                    assert model_hold.wait(10);requests.post(base+f"/api/workspace/tasks/analysis/{submitted['id']}/cancel",json={},timeout=5)
                    cancelled=terminal(base,submitted['id']);model_release.set();state['hold_model']=False
                    assert cancelled['state']=='cancelled';assert state['calls']==3
                    assert len([x for x in library.get(project_id)['resources'].values() if x['kind']=='analysis'])==before_reports
                    records.append('actual AI worker cancellation; no automatic replay or partial analysis publication')
                    source.fill('https://www.douyin.com/video/1002');page.get_by_role('button',name='解析视频',exact=True).click()
                    expect(page.locator('.info-title')).to_contain_text('优化测试 1002',timeout=15000);page.locator('.download-button').click();assert hold.wait(10)
                    row=page.locator('.task-list > li').filter(has_text='优化测试 1002');expect(row.get_by_role('button',name='取消任务')).to_be_visible(timeout=10000);row.get_by_role('button',name='取消任务').click()
                    identifier=next(job.id for job in workflows.jobs.values() if job.title=='优化测试 1002');owned.append(identifier)
                    assert terminal(base,identifier)['state']=='cancelled';records.append('browser cancel kills the running download worker')
                    source.fill('https://www.bilibili.com/video/BV1rH4y1N7BW?p=1')
                    panel=page.get_by_role('region',name='B站字幕下载');panel.get_by_label('下载范围').select_option('all');panel.get_by_role('button',name='下载字幕',exact=True).click()
                    expect(panel.get_by_role('status')).to_contain_text('未完成 1 集',timeout=15000)
                    assert not downloads;assert panel.get_by_role('button',name='另存字幕副本到下载文件夹').count()==0
                    page.reload();panel=page.get_by_role('region',name='B站字幕下载');expect(panel.get_by_role('status')).to_contain_text('未完成 1 集',timeout=15000)
                    episode(2);panel.get_by_role('button',name='重试未完成分集').click();expect(panel.get_by_role('status')).to_contain_text('未完成 0 集',timeout=15000)
                    assert state['subtitle_args'][-1]==[2];assert not downloads
                    records.append('structured subtitle partial failure, refresh restore, retry only P2, zero duplicate downloads')
                    center=page.get_by_role('region',name='任务中心');center.get_by_role('button',name='缓存管理').click();expect(page.get_by_role('heading',name='清理预览')).to_be_visible(timeout=10000)
                    assert page.get_by_role('button',name='确认清理上述临时缓存').is_disabled()
                    records.append('cache preview does not delete and excludes fresh/unknown/formal data')
                    for width in (1280,390,320):
                        page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
                    page.screenshot(path=str(output/'task-center-mobile.png'),full_page=True)
                    assert not errors,errors;records.append('320/390/1280 layout and no browser runtime errors')
                    browser.close()
            finally:
                model_release.set();server.should_exit=True;thread.join(timeout=10);sock.close()
                for identifier in owned:
                    task_runtime.cancel(identifier)
                    deadline=time.monotonic()+10
                    while task_runtime.active_id(identifier) and time.monotonic()<deadline:time.sleep(.05)
                    scratch=workflows.CACHE_ROOT/identifier
                    if scratch.is_dir():shutil.rmtree(scratch)
        provider.shutdown();provider.server_close()
    report={'checks':records,'real_external_platform_requests':0,'paid_model_requests':0,'automatic_downloads':0}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
