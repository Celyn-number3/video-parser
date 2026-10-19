"""Real crash/restart recovery with a synthetic download; no private media or platform calls."""
import json
import os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from threading import Thread,Event
import time
import requests
from video_parser.core.paths import ROOT
from video_parser.services import task_runtime,workflows

BOOTSTRAP=r'''
import os,sys
from pathlib import Path
from video_parser.services import library,workflows,subtitles,transcription,videos
root=Path(sys.argv[1]);upstream=sys.argv[2];port=int(sys.argv[3])
library.LIBRARY_ROOT=root/'library';workflows.RECORD_ROOT=root/'records';subtitles.CACHE_ROOT=root/'subtitles';transcription.OUTPUT_ROOT=root/'transcriptions'
def parse(text,**kw):
 return videos.select_quality(videos.ParsedVideo({'title':'restart fixture','platform':'douyin','video_id':text.split('/')[-1],'source_url':text,'cover_url':None,'video_url':upstream},{},[upstream],[]),'best')
videos.parse_link=parse
from video_parser.web.app import app
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=port,log_level='error')
'''

def ready(base,process):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if process.poll() is not None:raise AssertionError('Test server exited')
        try:
            if requests.get(base+'/health',timeout=.5).status_code==200:return
        except requests.RequestException:pass
        time.sleep(.05)
    raise AssertionError('Server startup timeout')


def main():
    received=Event();calls=[];owned=[];process=None
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            calls.append(1);received.set();self.send_response(200);self.send_header('Content-Length',str(10**9));self.end_headers()
            try:
                for _ in range(10000):self.wfile.write(b'x'*4096);self.wfile.flush();time.sleep(.1)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    provider=ThreadingHTTPServer(('127.0.0.1',0),Fixture);Thread(target=provider.serve_forever,daemon=True).start()
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base=f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='task-restart-') as temporary:
        root=Path(temporary);env={**os.environ,'VIDEO_LIBRARY_ROOT':str(root/'library'),'NO_PROXY':'127.0.0.1,localhost'}
        command=[sys.executable,'-X','utf8','-c',BOOTSTRAP,str(root),f'http://127.0.0.1:{provider.server_port}/hold',str(port)]
        try:
            process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env);ready(base,process)
            for number in ('10001','10002'):
                parsed=requests.post(base+'/api/workspace/parse',json={'text':'https://www.douyin.com/video/'+number},timeout=10);parsed.raise_for_status()
                job=requests.post(base+f"/api/workspace/videos/{parsed.json()['id']}/prepare-task",json={},timeout=10);job.raise_for_status();owned.append(job.json()['id'])
            assert received.wait(10);assert len(calls)==1
            task_runtime.stop_process(process)
            process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env);ready(base,process)
            states=[requests.get(base+'/api/workspace/tasks/'+identifier,timeout=5).json()['state'] for identifier in owned]
            assert states==['interrupted','interrupted'],states
            time.sleep(.5);assert len(calls)==1,'Restart silently replayed a job'
            report={'running_and_queued_after_restart':states,'provider_requests':len(calls),'automatic_resume':False,'actual_process_restart':True}
            (ROOT/'.local/work/artifacts/optimization-restart.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
        finally:
            if process:task_runtime.stop_process(process)
            for identifier in owned:
                path=workflows.CACHE_ROOT/identifier
                if path.is_dir():shutil.rmtree(path)
            provider.shutdown();provider.server_close()

if __name__=='__main__':main()
