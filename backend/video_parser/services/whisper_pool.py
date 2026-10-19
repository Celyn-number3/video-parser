"""Opt-in warm Whisper process, shared by the bounded transcription lane and batch CLI."""
import atexit
import json
from queue import Queue,Empty
import subprocess
from threading import Lock,Thread
import time
from uuid import uuid4
from video_parser.core.paths import ROOT, CACHE_DIR
from video_parser.services import task_runtime

_lock=Lock();_process=None;_responses=None;_log=None
IDLE_SECONDS=60


def _read(stream,queue):
    try:
        for line in stream:
            try:queue.put(json.loads(line))
            except ValueError:queue.put({'protocol_error':True})
    finally:queue.put(None)


def _close():
    global _process,_responses,_log
    if _process:
        task_runtime.stop_process(_process)
        if _process.stdin:_process.stdin.close()
        if _process.stdout:_process.stdout.close()
    if _log:_log.close()
    _process=None;_responses=None;_log=None


def close():
    with _lock:_close()


atexit.register(close)


def run(command, progress=None):
    global _process,_responses,_log
    from video_parser.services import transcription
    with _lock:
        if _process is None or _process.poll() is not None:
            _close()
            directory=CACHE_DIR / 'whisper';directory.mkdir(parents=True,exist_ok=True)
            _log=(directory/'session.log').open('w',encoding='utf-8')
            _responses=Queue()
            _process=subprocess.Popen([str(transcription.runtime_python()),'-X','utf8',str(transcription.TOOL_ROOT/'session.py'),
                 '--idle-seconds',str(IDLE_SECONDS)],cwd=transcription.TOOL_ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                 stderr=_log,text=True,encoding='utf-8',bufsize=1)
            Thread(target=_read,args=(_process.stdout,_responses),daemon=True,name='whisper-session-reader').start()
        process=_process;identifier=uuid4().hex;deadline=time.monotonic()+7200
        offset=(CACHE_DIR / 'whisper/session.log').stat().st_size
        try:
            task_runtime.checkpoint()
            process.stdin.write(json.dumps({'id':identifier,'arguments':command[4:]},ensure_ascii=False)+'\n');process.stdin.flush()
            while True:
                task_runtime.checkpoint()
                if progress:progress()
                if time.monotonic()>deadline:raise subprocess.TimeoutExpired(command,7200)
                try:result=_responses.get(timeout=.25)
                except Empty:continue
                if result is None or result.get('id')!=identifier:raise RuntimeError('Whisper session ended; retry explicitly')
                # Read only this request's diagnostic tail, never return it directly over HTTP.
                with (CACHE_DIR / 'whisper/session.log').open(encoding='utf-8',errors='replace') as stream:
                    stream.seek(offset);log=stream.read(256*1024)
                completed=subprocess.CompletedProcess(command,result['returncode'],stderr=log)
                completed.worker_metadata={k:result[k] for k in ('model_load_count','model_reused','seconds') if k in result}
                return completed
        except BaseException:
            _close();raise
