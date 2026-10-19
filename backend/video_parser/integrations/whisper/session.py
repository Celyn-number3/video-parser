"""Optional stdin/stdout worker: one CUDA model, isolated requests, bounded idle lifetime."""
import argparse
from contextlib import redirect_stdout
import json
import os
from queue import Queue,Empty
import sys
from threading import Thread
import time
if __package__:
    from . import cli
else:
    import cli


def serve(idle_seconds=60, preloaded_model=None, initial_load_seconds=0.0):
    if os.getenv('VIDEO_PARSER_DEBUG_WORKER')=='1':
        import faulthandler
        faulthandler.enable();faulthandler.dump_traceback_later(10,file=sys.stderr)
    print('Whisper session ready',file=sys.stderr,flush=True)
    incoming=Queue(maxsize=32)
    def read():
        try:
            for line in sys.stdin:
                if len(line)>65536:break
                print('Whisper request received',file=sys.stderr,flush=True)
                incoming.put(json.loads(line))
        finally:incoming.put(None)
    Thread(target=read,daemon=True).start()
    model=preloaded_model;loads=int(model is not None);first=True
    while True:
        try:request=incoming.get(timeout=idle_seconds)
        except Empty:return 0
        if request is None:return 0
        started=time.monotonic();reused=model is not None and not first;identifier=request.get('id','')
        try:
            print('Whisper request preflight',file=sys.stderr,flush=True)
            arguments=request['arguments']
            # Reject invalid input/output before allocating GPU memory.
            cli.plan_outputs(cli.parser().parse_args(arguments))
            with open(os.devnull,'w') as sink,redirect_stdout(sink):
                load_seconds=initial_load_seconds if first else 0.0
                if model is None:
                    print('Whisper CUDA model loading',file=sys.stderr,flush=True)
                    loading=time.monotonic();model=cli.load_model();loads+=1;load_seconds=time.monotonic()-loading
                code=cli.main(arguments,model=model,initial_load_seconds=load_seconds)
            result={'id':identifier,'returncode':code,'model_load_count':loads,'model_reused':reused,'seconds':time.monotonic()-started}
        except Exception as error:
            result={'id':identifier,'returncode':1,'model_load_count':loads,'error_type':type(error).__name__}
            print('Whisper request failed: '+type(error).__name__,file=sys.stderr,flush=True)
        first=False
        print(json.dumps(result),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--idle-seconds',type=int,default=60)
    args=parser.parse_args()
    if not 1<=args.idle_seconds<=600:raise SystemExit('Idle timeout must be 1..600 seconds')
    # NumPy/OpenBLAS native DLL initialization can deadlock on Windows when another
    # thread is already blocked in stdin. Initialize the CUDA model before that reader.
    started=time.monotonic()
    print('Initializing CUDA model before stdin reader',file=sys.stderr,flush=True)
    with open(os.devnull,'w') as sink,redirect_stdout(sink):
        model=cli.load_model()
    raise SystemExit(serve(args.idle_seconds,model,time.monotonic()-started))
