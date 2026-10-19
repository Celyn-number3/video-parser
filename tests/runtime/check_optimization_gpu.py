"""Explicit public-fixture CUDA acceptance. No personal recordings, remote models or fallback."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
from uuid import uuid4
from video_parser.core.paths import ROOT
from video_parser.services import library,transcription,whisper_pool,task_runtime


def main():
    source=ROOT/'.local/work/artifacts/external-tools-install/jfk.flac'
    if not source.is_file():raise RuntimeError('Public JFK fixture is required; do not substitute personal recordings')
    before=library.digest(source);directory=ROOT/'.local/work/artifacts/optimization-verification'/uuid4().hex;directory.mkdir(parents=True)
    invalid=directory/'invalid.wav';invalid.write_bytes(b'not an audio file')
    env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTHONUTF8':'1'}
    command=[sys.executable,'-X','utf8','-m','video_parser','transcribe-batch',str(source),str(invalid),str(source),
             '--language','en','--output-dir',str(directory/'batch'),'--json']
    with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=env) as process:
        stdout,stderr=task_runtime.communicate(process,180)
        result=subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
    if result.returncode!=1:raise AssertionError('Expected partial batch exit 1; '+result.stderr[-1000:])
    batch=json.loads(result.stdout)
    assert batch['completed']==2 and batch['failed']==1,batch
    successes=[row for row in batch['results'] if row['state']=='completed']
    assert [row['worker']['model_load_count'] for row in successes]==[1,1]
    assert [row['worker']['model_reused'] for row in successes]==[False,True]
    assert all('country' in row['text'].lower() for row in successes)
    with patch.dict(os.environ,env),patch.object(whisper_pool,'IDLE_SECONDS',2):
        idle=transcription.transcribe(source,'en',directory/'idle',reuse_model=True)
        process=whisper_pool._process;process.wait(timeout=15)
        assert process.returncode==0,'Idle worker failed to exit normally'
        whisper_pool.close()
        long=directory/'looped-public-fixture.flac'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-stream_loop','49','-i',str(source),'-t','300','-c:a','flac',str(long)],check=True,timeout=30)
        original=library.digest(long)
        with patch.object(transcription,'OUTPUT_ROOT',directory/'cancel'):
            submitted=transcription.start(long,'en',reuse_model=True)
            deadline=time.monotonic()+15
            while whisper_pool._process is None and time.monotonic()<deadline:time.sleep(.02)
            assert whisper_pool._process is not None,'Worker never launched'
            owned=whisper_pool._process
            time.sleep(.5);assert task_runtime.cancel(submitted['id'])
            deadline=time.monotonic()+15
            while task_runtime.active_id(submitted['id']) and time.monotonic()<deadline:time.sleep(.05)
            cancelled=transcription.get(submitted['id'])
            assert cancelled.state=='cancelled',transcription.view(cancelled)
            assert owned.poll() is not None and whisper_pool._process is None
            assert library.digest(long)==original
    assert library.digest(source)==before
    report={'batch_cli_exit':result.returncode,'completed':2,'isolated_failures':1,
        'model_load_counts':[row['worker']['model_load_count'] for row in successes],
        'model_reused':[row['worker']['model_reused'] for row in successes],
        'worker_seconds':[round(row['worker']['seconds'],3) for row in successes],
        'idle_unload_verified_seconds':2,'production_default_idle_seconds':60,
        'actual_gpu_job_cancelled':True,'owned_process_exited':True,'originals_unchanged':True,
        'offline_mode':True,'outputs':directory.relative_to(ROOT).as_posix()}
    (ROOT/'.local/work/artifacts/optimization-gpu.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
